from contextlib import contextmanager
from typing import Optional, Sequence, Type, cast

import duckdb
from dagster import Field, IOManagerDefinition, OutputContext, StringSource, io_manager
from dagster._core.definitions.time_window_partitions import TimeWindow
from dagster._core.storage.db_io_manager import (
    DbClient,
    DbIOManager,
    DbTypeHandler,
    TablePartitionDimension,
    TableSlice,
)
from dagster._utils.backoff import backoff

DUCKDB_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def build_duckdb_io_manager(
    type_handlers: Sequence[DbTypeHandler], default_load_type: Optional[Type] = None
) -> IOManagerDefinition:
    """
    Builds an IO manager definition that reads inputs from and writes outputs to DuckDB.

    Args:
        type_handlers (Sequence[DbTypeHandler]): Each handler defines how to translate between
            DuckDB tables and an in-memory type - e.g. a Pandas DataFrame. If only
            one DbTypeHandler is provided, it will be used as teh default_load_type.
        default_load_type (Type): When an input has no type annotation, load it as this type.

    Returns:
        IOManagerDefinition

    Examples:
        .. code-block:: python

            from dagster_duckdb import build_duckdb_io_manager
            from dagster_duckdb_pandas import DuckDBPandasTypeHandler

            @asset(
                key_prefix=["my_schema"]  # will be used as the schema in duckdb
            )
            def my_table() -> pd.DataFrame:  # the name of the asset will be the table name
                ...

            duckdb_io_manager = build_duckdb_io_manager([DuckDBPandasTypeHandler()])

            @repository
            def my_repo():
                return with_resources(
                    [my_table],
                    {"io_manager": duckdb_io_manager.configured({"database": "my_db.duckdb"})}
                )

    If you do not provide a schema, Dagster will determine a schema based on the assets and ops using
    the IO Manager. For assets, the schema will be determined from the asset key. For ops, the schema can be
    specified by including a "schema" entry in output metadata. If none of these is provided, the schema will
    default to "public".

    .. code-block:: python

        @op(
            out={"my_table": Out(metadata={"schema": "my_schema"})}
        )
        def make_my_table() -> pd.DataFrame:
            ...

    To only use specific columns of a table as input to a downstream op or asset, add the metadata "columns" to the
    In or AssetIn.

    .. code-block:: python

        @asset(
            ins={"my_table": AssetIn("my_table", metadata={"columns": ["a"]})}
        )
        def my_table_a(my_table: pd.DataFrame):
            # my_table will just contain the data from column "a"
            ...

    """

    @io_manager(
        config_schema={
            "database": Field(StringSource, description="Path to the DuckDB database."),
            "schema": Field(
                StringSource, description="Name of the schema to use.", is_required=False
            ),
        }
    )
    def duckdb_io_manager(init_context):
        """IO Manager for storing outputs in a DuckDB database.

        Assets will be stored in the schema and table name specified by their AssetKey.
        Subsequent materializations of an asset will overwrite previous materializations of that asset.
        Op outputs will be stored in the schema specified by output metadata (defaults to public) in a
        table of the name of the output.
        """
        return DbIOManager(
            type_handlers=type_handlers,
            db_client=DuckDbClient(),
            io_manager_name="DuckDBIOManager",
            database=init_context.resource_config["database"],
            schema=init_context.resource_config.get("schema"),
            default_load_type=default_load_type,
        )

    return duckdb_io_manager


class DuckDbClient(DbClient):
    @staticmethod
    def delete_table_slice(context: OutputContext, table_slice: TableSlice, connection) -> None:
        try:
            connection.execute(_get_cleanup_statement(table_slice))
        except duckdb.CatalogException:
            # table doesn't exist yet, so ignore the error
            pass

    @staticmethod
    def ensure_schema_exists(context: OutputContext, table_slice: TableSlice, connection) -> None:
        connection.execute(f"create schema if not exists {table_slice.schema};")

    @staticmethod
    def get_select_statement(table_slice: TableSlice) -> str:
        col_str = ", ".join(table_slice.columns) if table_slice.columns else "*"

        if table_slice.partition_dimensions and len(table_slice.partition_dimensions) > 0:
            query = f"SELECT {col_str} FROM {table_slice.schema}.{table_slice.table} WHERE\n"
            partition_where = " AND\n".join(
                _static_where_clause(partition_dimension)
                if isinstance(partition_dimension.partition, str)
                else _time_window_where_clause(partition_dimension)
                for partition_dimension in table_slice.partition_dimensions
            )
            return query + partition_where
        else:
            return f"""SELECT {col_str} FROM {table_slice.schema}.{table_slice.table}"""

    @staticmethod
    @contextmanager
    def connect(context, _):
        conn = backoff(
            fn=duckdb.connect,
            retry_on=(RuntimeError, duckdb.IOException),
            kwargs={"database": context.resource_config["database"], "read_only": False},
            max_retries=10,
        )

        yield conn

        conn.close()


def _get_cleanup_statement(table_slice: TableSlice) -> str:
    """
    Returns a SQL statement that deletes data in the given table to make way for the output data
    being written.
    """
    if table_slice.partition_dimensions and len(table_slice.partition_dimensions) > 0:
        query = f"DELETE FROM {table_slice.schema}.{table_slice.table} WHERE\n"

        partition_where = " AND\n".join(
            _static_where_clause(partition_dimension)
            if isinstance(partition_dimension.partition, str)
            else _time_window_where_clause(partition_dimension)
            for partition_dimension in table_slice.partition_dimensions
        )
        return query + partition_where
    else:
        return f"DELETE FROM {table_slice.schema}.{table_slice.table}"


def _time_window_where_clause(table_partition: TablePartitionDimension) -> str:
    partition = cast(TimeWindow, table_partition.partition)
    start_dt, end_dt = partition
    start_dt_str = start_dt.strftime(DUCKDB_DATETIME_FORMAT)
    end_dt_str = end_dt.strftime(DUCKDB_DATETIME_FORMAT)
    return f"""{table_partition.partition_expr} >= '{start_dt_str}' AND {table_partition.partition_expr} < '{end_dt_str}'"""


def _static_where_clause(table_partition: TablePartitionDimension) -> str:
    return f"""{table_partition.partition_expr} = '{table_partition.partition}'"""
