GCP (dagster-gcp)
=================

.. currentmodule:: dagster_gcp

BigQuery
--------

.. autoclass:: BigQueryError

.. autoconfigurable:: bigquery_resource
  :annotation: ResourceDefinition

.. autoconfigurable:: build_bigquery_io_manager
  :annotation: IOManagerDefinition

.. autofunction:: bq_create_dataset

.. autofunction:: bq_delete_dataset

.. autofunction:: bq_op_for_queries

.. autofunction:: import_df_to_bq

.. autofunction:: import_file_to_bq

.. autofunction:: import_gcs_paths_to_bq


Dataproc
--------

.. autoconfigurable:: dataproc_op

.. autoconfigurable:: dataproc_resource
  :annotation: ResourceDefinition


GCS
---

.. autoconfigurable:: gcs_resource
  :annotation: ResourceDefinition

.. autoconfigurable:: dagster_gcp.gcs.gcs_pickle_io_manager
  :annotation: IOManagerDefinition

File Manager (Experimental)
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autoclass:: GCSFileHandle
  :members:

.. autodata:: gcs_file_manager
  :annotation: ResourceDefinition