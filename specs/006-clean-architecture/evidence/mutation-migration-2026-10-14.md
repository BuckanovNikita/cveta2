# Mutation scope migration — 2026-10-14

Baseline: `09ded060040d87c7f13bf773349abfa1f16ffe30`. Canonical source snapshot is this worktree on 2026-10-14. Installed tool version: **mutmut 3.7.0** from `uv.lock`. This inventory covers all 40 baseline `only_mutate` files, all 402 declared functions/methods (including decorated and zero-mutable definitions), and all 219 baseline equivalent entries. No baseline function is missing from canonical mutation scope.

## Method and status

Baseline source was read from Git; canonical declarations were parsed with Python AST. Comparison removes type annotations, docstrings and function-name spelling, preserving parameters, defaults, decorators, control flow, expressions and writes. This is behavioral-source identity evidence, not a test verdict. Of the 402 declarations, 350 match after that normalization; 52 changed or gained an explicit port/settings boundary.

Installed mutmut `create_mutations()` generated edits entirely in memory with the live unchanged suppression patterns. Generation invokes neither pytest nor a mutation run and creates no generated workspace. Every migrated equivalent names a generated edit: 164 retain both normalized function AST and exact numbered edit identity; 55 have changed functions and were matched by exact mutation edit or inspected port/split context. Numbers were never inferred solely from module renames.

All changed-function equivalents were subsequently revalidated by the completed full gate recorded below. Three old COCO split-directory `parents=` equivalents moved to a shared adapter helper also used to create the output root; the full gate killed them, so their old exemptions were retired with that evidence. The completed full gate rejected no stale entries or unexplained survivors; intermediate failures and their resolution remain recorded below.

## Scope and profiles

Baseline 40 files become 58 canonical files. Split policy, filesystem and composition destinations are included rather than leaving moved logic behind public facades. `full = []` remains empty (bare cached `mutmut run`). Fast retains its seven original module families and their split destinations; selected function globs keep shared file/composition modules from pulling unrelated full-only functions into fast. SDK-creation, configuration-resolution and image-reader parts moved out of old client methods remain scoped.

Vulture exclusion moves from the old S3 protocol module to `adapters/s3/types.py`, preserving the specific opaque SDK protocol exception. No broader exclusion is introduced. The pytest `-n 0` args, test invalidation fields, rerun policy, mutation line policy and suppression patterns are unchanged.

| Baseline file | Canonical scoped owners |
|---|---|
| `cveta2/dataset_partition.py` | `cveta2.domain.partition` |
| `cveta2/_client/connection.py` | `cveta2.composition.runtime`, `cveta2.adapters.cvat.connection` |
| `cveta2/services/whats_new.py` | `cveta2.application.use_cases.whats_new`, `cveta2.domain.baseline`, `cveta2.adapters.files.dataset` |
| `cveta2/services/resolve.py` | `cveta2.application.use_cases.resolve`, `cveta2.composition.workflows` |
| `cveta2/_client/extractors.py` | `cveta2.application.client.extractors` |
| `cveta2/_client/assembly.py` | `cveta2.application.client.assembly` |
| `cveta2/models.py` | `cveta2.domain.models` |
| `cveta2/s3_utils.py` | `cveta2.adapters.s3.utils`, `cveta2.domain.paths` |
| `cveta2/projects_cache.py` | `cveta2.adapters.config.projects_cache` |
| `cveta2/services/merge.py` | `cveta2.domain.merge`, `cveta2.application.use_cases.merge`, `cveta2.adapters.files.dataset` |
| `cveta2/services/output.py` | `cveta2.adapters.files.dataset`, `cveta2.domain.output` |
| `cveta2/task_cache.py` | `cveta2.adapters.s3.task_cache`, `cveta2.composition.workflows`, `cveta2.domain.cache` |
| `cveta2/image_downloader.py` | `cveta2.adapters.cvat.storage`, `cveta2.domain.storage`, `cveta2.domain.paths`, `cveta2.adapters.files.materialization`, `cveta2.adapters.s3.download` |
| `cveta2/image_uploader.py` | `cveta2.adapters.files.image_search`, `cveta2.adapters.s3.upload` |
| `cveta2/_client_ops/write.py` | `cveta2.application.client.write` |
| `cveta2/_client_ops/task_ops.py` | `cveta2.application.client.task_ops` |
| `cveta2/_client_ops/fetch.py` | `cveta2.application.client.fetch` |
| `cveta2/_client_ops/read.py` | `cveta2.application.client.read` |
| `cveta2/_client/sdk_convert.py` | `cveta2.adapters.cvat.sdk_convert` |
| `cveta2/_client/sdk_requests.py` | `cveta2.adapters.cvat.sdk_requests` |
| `cveta2/services/upload.py` | `cveta2.application.use_cases.upload`, `cveta2.composition.workflows`, `cveta2.adapters.files.task_output` |
| `cveta2/services/convert/common.py` | `cveta2.domain.conversion`, `cveta2.adapters.files.materialization`, `cveta2.composition.conversion`, `cveta2.adapters.files.conversion`, `cveta2.application.use_cases.convert.common` |
| `cveta2/services/convert/coco.py` | `cveta2.application.use_cases.convert.coco`, `cveta2.adapters.files.conversion`, `cveta2.domain.conversion` |
| `cveta2/services/convert/yolo.py` | `cveta2.application.use_cases.convert.yolo`, `cveta2.adapters.files.conversion`, `cveta2.domain.conversion` |
| `cveta2/config.py` | `cveta2.adapters.config.settings`, `cveta2.application.settings` |
| `cveta2/api.py` | `cveta2.interfaces.api` |
| `cveta2/_client_ops/base.py` | `cveta2.application.client.base`, `cveta2.composition.client` |
| `cveta2/_client_ops/images.py` | `cveta2.application.client.images`, `cveta2.adapters.s3.images` |
| `cveta2/commands/_helpers.py` | `cveta2.interfaces.commands._helpers` |
| `cveta2/commands/interactive/primitives.py` | `cveta2.interfaces.commands.interactive.primitives` |
| `cveta2/commands/upload.py` | `cveta2.interfaces.commands.upload` |
| `cveta2/services/fetch.py` | `cveta2.composition.workflows`, `cveta2.application.use_cases.fetch`, `cveta2.adapters.files.task_output` |
| `cveta2/_concurrency.py` | `cveta2.adapters.execution.concurrency` |
| `cveta2/upload_manifest.py` | `cveta2.domain.upload`, `cveta2.adapters.files.manifests` |
| `cveta2/services/task_ops.py` | `cveta2.application.use_cases.task_ops` |
| `cveta2/_client/dtos.py` | `cveta2.application.ports.dtos` |
| `cveta2/_client/mapping.py` | `cveta2.application.client.mapping` |
| `cveta2/client.py` | `cveta2.composition.client` |
| `cveta2/commands/_bootstrap.py` | `cveta2.interfaces.commands._bootstrap` |
| `cveta2/fs_utils.py` | `cveta2.adapters.files.shared` |

## Complete function inventory

`same` means normalized AST identity; `changed` requires the behavior tests and mutation gates to revalidate the new explicit dependency boundary. Classes decorated with dataclass and property/contextmanager methods remain in the inventory even where mutmut generates no mutants.

| Baseline declaration | Canonical declaration | AST |
|---|---|---|
| `cveta2.dataset_partition._rows_are_finished` | `cveta2.domain.partition._rows_are_finished` | same |
| `cveta2.dataset_partition.completed_task_ids` | `cveta2.domain.partition.completed_task_ids` | same |
| `cveta2.dataset_partition._deleted_registry_frame` | `cveta2.domain.partition._deleted_registry_frame` | same |
| `cveta2.dataset_partition._latest_row_per_image` | `cveta2.domain.partition._latest_row_per_image` | same |
| `cveta2.dataset_partition._latest_task_per_image` | `cveta2.domain.partition._latest_task_per_image` | same |
| `cveta2.dataset_partition._split_completed` | `cveta2.domain.partition._split_completed` | same |
| `cveta2.dataset_partition._filter_deleted_images` | `cveta2.domain.partition._filter_deleted_images` | same |
| `cveta2.dataset_partition.partition_annotations_df` | `cveta2.domain.partition.partition_annotations_df` | same |
| `cveta2._client.connection.configure_data_timeout` | `cveta2.composition.runtime.configure_data_timeout` | same |
| `cveta2._client.connection.configure_network` | `cveta2.composition.runtime.configure_network` | same |
| `cveta2._client.connection.SdkClientFactory.__call__` | `cveta2.adapters.cvat.connection.SdkClientFactory.__call__` | same |
| `cveta2._client.connection._build_client_kwargs` | `cveta2.adapters.cvat.connection._build_client_kwargs` | same |
| `cveta2._client.connection.open_sdk_api` | `cveta2.adapters.cvat.connection.open_sdk_api` | same |
| `cveta2.services.whats_new.compute_baseline` | `cveta2.application.use_cases.whats_new.compute_baseline` | changed |
| `cveta2.services.whats_new.compute_cutoff` | `cveta2.domain.baseline.compute_cutoff` | same |
| `cveta2.services.whats_new._task_ids` | `cveta2.domain.baseline._task_ids` | same |
| `cveta2.services.whats_new._known_task_ids` | `cveta2.domain.baseline._known_task_ids` | changed |
| `cveta2.services.resolve.split_project_spec` | `cveta2.application.use_cases.resolve.split_project_spec` | same |
| `cveta2.services.resolve.apply_project_org` | `cveta2.application.use_cases.resolve.apply_project_org` | same |
| `cveta2.services.resolve._project_display_name` | `cveta2.application.use_cases.resolve._project_display_name` | same |
| `cveta2.services.resolve.resolve_project_spec` | `cveta2.application.use_cases.resolve.resolve_project_spec` | same |
| `cveta2.services.resolve.resolve_bare_project_spec` | `cveta2.application.use_cases.resolve.resolve_bare_project_spec` | same |
| `cveta2.services.resolve.infer_project_from_tasks` | `cveta2.application.use_cases.resolve.infer_project_from_tasks` | same |
| `cveta2.services.resolve.project_cloud_storage` | `cveta2.application.use_cases.resolve.project_cloud_storage` | changed |
| `cveta2.services.resolve.apply_sync_root_override` | `cveta2.application.use_cases.resolve.apply_sync_root_override` | changed |
| `cveta2._client.extractors._polygon_bounds` | `cveta2.application.client.extractors._polygon_bounds` | same |
| `cveta2._client.extractors._collect_shapes` | `cveta2.application.client.extractors._collect_shapes` | same |
| `cveta2._client.assembly.build_name_to_frame` | `cveta2.application.client.assembly.build_name_to_frame` | same |
| `cveta2._client.assembly.find_job_for_frame` | `cveta2.application.client.assembly.find_job_for_frame` | same |
| `cveta2._client.assembly.issue_position_from_row` | `cveta2.application.client.assembly.issue_position_from_row` | same |
| `cveta2._client.assembly.task_to_records` | `cveta2.application.client.assembly.task_to_records` | same |
| `cveta2._client.assembly.build_upload_shapes` | `cveta2.application.client.assembly.build_upload_shapes` | same |
| `cveta2._client.assembly.build_task_issues` | `cveta2.application.client.assembly.build_task_issues` | same |
| `cveta2.models.TaskInfo.format_display` | `cveta2.domain.models.TaskInfo.format_display` | same |
| `cveta2.models.LabelInfo.format_display` | `cveta2.domain.models.LabelInfo.format_display` | same |
| `cveta2.models._validate_image_name` | `cveta2.domain.models._validate_image_name` | same |
| `cveta2.models._capture_frame_path` | `cveta2.domain.models._capture_frame_path` | same |
| `cveta2.models._validate_image_path` | `cveta2.domain.models._validate_image_path` | same |
| `cveta2.models._ImageRecordBase.to_csv_row` | `cveta2.domain.models._ImageRecordBase.to_csv_row` | same |
| `cveta2.models.BBoxAnnotation.to_csv_row` | `cveta2.domain.models.BBoxAnnotation.to_csv_row` | same |
| `cveta2.models._sparse_csv_row` | `cveta2.domain.models._sparse_csv_row` | same |
| `cveta2.models.ProjectAnnotations.to_csv_rows` | `cveta2.domain.models.ProjectAnnotations.to_csv_rows` | same |
| `cveta2.models.TaskAnnotations.merge` | `cveta2.domain.models.TaskAnnotations.merge` | same |
| `cveta2.s3_utils.run_s3_transfers` | `cveta2.adapters.s3.utils.run_s3_transfers` | same |
| `cveta2.s3_utils.pick_latest_duplicate` | `cveta2.domain.paths.pick_latest_duplicate` | same |
| `cveta2.s3_utils.names_with_basename_fallback` | `cveta2.domain.paths.names_with_basename_fallback` | same |
| `cveta2.s3_utils._should_retry_s3` | `cveta2.adapters.s3.utils._should_retry_s3` | same |
| `cveta2.s3_utils.set_default_data_timeout` | `cveta2.adapters.s3.utils.set_default_data_timeout` | same |
| `cveta2.s3_utils.make_s3_client` | `cveta2.adapters.s3.utils.make_s3_client` | same |
| `cveta2.s3_utils.s3_get_bytes` | `cveta2.adapters.s3.utils.s3_get_bytes` | same |
| `cveta2.s3_utils.s3_object_exists` | `cveta2.adapters.s3.utils.s3_object_exists` | same |
| `cveta2.s3_utils.parse_sync_root` | `cveta2.domain.paths.parse_sync_root` | same |
| `cveta2.s3_utils._key_prefix_dir` | `cveta2.domain.paths._key_prefix_dir` | same |
| `cveta2.s3_utils.build_s3_key` | `cveta2.domain.paths.build_s3_key` | same |
| `cveta2.s3_utils.strip_key_prefix` | `cveta2.domain.paths.strip_key_prefix` | same |
| `cveta2.s3_utils._iter_list_pages` | `cveta2.adapters.s3.utils._iter_list_pages` | same |
| `cveta2.s3_utils._page_pairs` | `cveta2.adapters.s3.utils._page_pairs` | same |
| `cveta2.s3_utils._search_query` | `cveta2.adapters.s3.utils._search_query` | same |
| `cveta2.s3_utils._list_keys_under` | `cveta2.adapters.s3.utils._list_keys_under` | same |
| `cveta2.s3_utils._list_one_level` | `cveta2.adapters.s3.utils._list_one_level` | same |
| `cveta2.s3_utils.list_s3_objects` | `cveta2.adapters.s3.utils.list_s3_objects` | same |
| `cveta2.projects_cache.load_orgs_cache` | `cveta2.adapters.config.projects_cache.load_orgs_cache` | same |
| `cveta2.projects_cache.save_orgs_cache` | `cveta2.adapters.config.projects_cache.save_orgs_cache` | same |
| `cveta2.projects_cache.update_org_projects` | `cveta2.adapters.config.projects_cache.update_org_projects` | same |
| `cveta2.projects_cache.load_projects_cache` | `cveta2.adapters.config.projects_cache.load_projects_cache` | same |
| `cveta2.services.merge._propagate_splits` | `cveta2.domain.merge._propagate_splits` | same |
| `cveta2.services.merge._split_winners` | `cveta2.domain.merge._split_winners` | same |
| `cveta2.services.merge._merge_datasets` | `cveta2.domain.merge._merge_datasets` | same |
| `cveta2.services.merge._max_task_id_per_image` | `cveta2.domain.merge._max_task_id_per_image` | same |
| `cveta2.services.merge._resolve_by_task` | `cveta2.domain.merge._resolve_by_task` | same |
| `cveta2.services.merge.merge_datasets` | `cveta2.application.use_cases.merge.merge_datasets` | changed |
| `cveta2.services.output.read_text_utf8` | `cveta2.adapters.files.dataset.read_text_utf8` | same |
| `cveta2.services.output.write_text_utf8` | `cveta2.adapters.files.dataset.write_text_utf8` | same |
| `cveta2.services.output.read_dataset_csv` | `cveta2.adapters.files.dataset.read_dataset_csv` | same |
| `cveta2.services.output.populate_record_paths` | `cveta2.adapters.files.dataset.populate_record_paths` | same |
| `cveta2.services.output.enrich_dataframe_paths` | `cveta2.adapters.files.dataset.enrich_dataframe_paths` | same |
| `cveta2.services.output.preview_names` | `cveta2.domain.output.preview_names` | same |
| `cveta2.services.output.count_images` | `cveta2.domain.output.count_images` | same |
| `cveta2.services.output.format_counts` | `cveta2.domain.output.format_counts` | same |
| `cveta2.services.output.format_counts_ru` | `cveta2.domain.output.format_counts_ru` | same |
| `cveta2.services.output.save_csv` | `cveta2.adapters.files.dataset.save_csv` | changed |
| `cveta2.services.output.write_raw_csv` | `cveta2.adapters.files.dataset.write_raw_csv` | same |
| `cveta2.services.output._write_deleted_csv` | `cveta2.adapters.files.dataset._write_deleted_csv` | same |
| `cveta2.services.output.write_partition_csvs` | `cveta2.adapters.files.dataset.write_partition_csvs` | same |
| `cveta2.services.output.write_dataset_and_deleted` | `cveta2.adapters.files.dataset.write_dataset_and_deleted` | same |
| `cveta2.task_cache.get_task_cache_dir` | `cveta2.adapters.s3.task_cache.get_task_cache_dir` | same |
| `cveta2.task_cache.invalidate_local_entry` | `cveta2.composition.workflows.invalidate_local_entry` | changed |
| `cveta2.task_cache._s3_put_bytes` | `cveta2.adapters.s3.task_cache._s3_put_bytes` | same |
| `cveta2.task_cache._s3_delete_object` | `cveta2.adapters.s3.task_cache._s3_delete_object` | same |
| `cveta2.task_cache._client_error_code` | `cveta2.adapters.s3.task_cache._client_error_code` | same |
| `cveta2.task_cache.S3CacheBackend.__init__` | `cveta2.adapters.s3.task_cache.S3CacheBackend.__init__` | same |
| `cveta2.task_cache.S3CacheBackend.from_cloud_storage` | `cveta2.adapters.s3.task_cache.S3CacheBackend.from_cloud_storage` | same |
| `cveta2.task_cache.S3CacheBackend.get` | `cveta2.adapters.s3.task_cache.S3CacheBackend.get` | same |
| `cveta2.task_cache.S3CacheBackend.put` | `cveta2.adapters.s3.task_cache.S3CacheBackend.put` | same |
| `cveta2.task_cache.S3CacheBackend.delete` | `cveta2.adapters.s3.task_cache.S3CacheBackend.delete` | same |
| `cveta2.task_cache.S3CacheBackend._entry_key` | `cveta2.adapters.s3.task_cache.S3CacheBackend._entry_key` | same |
| `cveta2.task_cache.S3CacheBackend._disable` | `cveta2.adapters.s3.task_cache.S3CacheBackend._disable` | same |
| `cveta2.task_cache.TaskAnnotationCache.__init__` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache.__init__` | same |
| `cveta2.task_cache.TaskAnnotationCache.get` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache.get` | same |
| `cveta2.task_cache.TaskAnnotationCache.put` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache.put` | same |
| `cveta2.task_cache.TaskAnnotationCache.invalidate_local` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache.invalidate_local` | same |
| `cveta2.task_cache.TaskAnnotationCache.invalidate` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache.invalidate` | same |
| `cveta2.task_cache.TaskAnnotationCache.prune` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache.prune` | same |
| `cveta2.task_cache.TaskAnnotationCache._get_local` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache._get_local` | same |
| `cveta2.task_cache.TaskAnnotationCache._get_s3` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache._get_s3` | same |
| `cveta2.task_cache.TaskAnnotationCache._write_local` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache._write_local` | same |
| `cveta2.task_cache.TaskAnnotationCache._local_path` | `cveta2.adapters.s3.task_cache.TaskAnnotationCache._local_path` | same |
| `cveta2.task_cache._validate_envelope` | `cveta2.domain.cache._validate_envelope` | same |
| `cveta2.task_cache._task_id_from_filename` | `cveta2.domain.cache._task_id_from_filename` | same |
| `cveta2.image_downloader.parse_cloud_storage` | `cveta2.adapters.cvat.storage.parse_cloud_storage` | same |
| `cveta2.image_downloader.DownloadStats.summary` | `cveta2.domain.storage.DownloadStats.summary` | same |
| `cveta2.image_downloader._validate_relative_key` | `cveta2.domain.paths._validate_relative_key` | same |
| `cveta2.image_downloader._canonical_frame_key` | `cveta2.domain.paths._canonical_frame_key` | same |
| `cveta2.image_downloader._local_name_from_key` | `cveta2.domain.paths._local_name_from_key` | same |
| `cveta2.image_downloader._confined_destination` | `cveta2.adapters.files.materialization._confined_destination` | same |
| `cveta2.image_downloader._download_pending` | `cveta2.adapters.s3.download._download_pending` | same |
| `cveta2.image_downloader.ImageDownloader.__init__` | `cveta2.adapters.s3.download.ImageDownloader.__init__` | same |
| `cveta2.image_downloader.ImageDownloader.download` | `cveta2.adapters.s3.download.ImageDownloader.download` | same |
| `cveta2.image_downloader.ImageDownloader._collect_unique_images` | `cveta2.adapters.s3.download.ImageDownloader._collect_unique_images` | same |
| `cveta2.image_downloader.ImageDownloader._dest_path` | `cveta2.adapters.s3.download.ImageDownloader._dest_path` | same |
| `cveta2.image_downloader.ImageDownloader._filter_cached` | `cveta2.adapters.s3.download.ImageDownloader._filter_cached` | same |
| `cveta2.image_downloader.ImageDownloader._download_all` | `cveta2.adapters.s3.download.ImageDownloader._download_all` | same |
| `cveta2.image_downloader.ImageDownloader._resolve_s3_keys` | `cveta2.adapters.s3.download.ImageDownloader._resolve_s3_keys` | same |
| `cveta2.image_downloader.ImageDownloader._probe_expected_keys` | `cveta2.adapters.s3.download.ImageDownloader._probe_expected_keys` | same |
| `cveta2.image_downloader.ImageDownloader._build_project_storage_name_map` | `cveta2.adapters.s3.download.ImageDownloader._build_project_storage_name_map` | same |
| `cveta2.image_downloader._download_one_s3` | `cveta2.adapters.s3.download._download_one_s3` | same |
| `cveta2.image_downloader.S3Syncer.__init__` | `cveta2.adapters.s3.download.S3Syncer.__init__` | same |
| `cveta2.image_downloader.S3Syncer.sync` | `cveta2.adapters.s3.download.S3Syncer.sync` | same |
| `cveta2.image_uploader._build_basename_index` | `cveta2.adapters.files.image_search._build_basename_index` | same |
| `cveta2.image_uploader._match_recursive` | `cveta2.adapters.files.image_search._match_recursive` | same |
| `cveta2.image_uploader.resolve_images` | `cveta2.adapters.files.image_search.resolve_images` | same |
| `cveta2.image_uploader.build_server_file_mapping` | `cveta2.adapters.s3.upload.build_server_file_mapping` | same |
| `cveta2.image_uploader._resolve_duplicate_basenames` | `cveta2.adapters.s3.upload._resolve_duplicate_basenames` | same |
| `cveta2.image_uploader._assign_month_folder` | `cveta2.adapters.s3.upload._assign_month_folder` | same |
| `cveta2.image_uploader._upload_one_s3` | `cveta2.adapters.s3.upload._upload_one_s3` | same |
| `cveta2.image_uploader.S3Uploader.upload` | `cveta2.adapters.s3.upload.S3Uploader.upload` | same |
| `cveta2._client_ops.write._select_new_issue_rows` | `cveta2.application.client.write._select_new_issue_rows` | same |
| `cveta2._client_ops.write._issues_not_yet_on_task` | `cveta2.application.client.write._issues_not_yet_on_task` | same |
| `cveta2._client_ops.write._WriteMixin.update_project_labels` | `cveta2.application.client.write._WriteMixin.update_project_labels` | same |
| `cveta2._client_ops.write._WriteMixin.create_upload_task` | `cveta2.application.client.write._WriteMixin.create_upload_task` | same |
| `cveta2._client_ops.write._WriteMixin.upload_task_annotations` | `cveta2.application.client.write._WriteMixin.upload_task_annotations` | same |
| `cveta2._client_ops.write._WriteMixin.create_task_issues` | `cveta2.application.client.write._WriteMixin.create_task_issues` | changed |
| `cveta2._client_ops.task_ops._TaskOpsMixin.mark_frames_deleted` | `cveta2.application.client.task_ops._TaskOpsMixin.mark_frames_deleted` | same |
| `cveta2._client_ops.task_ops._TaskOpsMixin.mark_frames_deleted_by_ids` | `cveta2.application.client.task_ops._TaskOpsMixin.mark_frames_deleted_by_ids` | same |
| `cveta2._client_ops.task_ops._TaskOpsMixin._patch_deleted_frames` | `cveta2.application.client.task_ops._TaskOpsMixin._patch_deleted_frames` | same |
| `cveta2._client_ops.task_ops._TaskOpsMixin.count_task_label_shapes` | `cveta2.application.client.task_ops._TaskOpsMixin.count_task_label_shapes` | same |
| `cveta2._client_ops.task_ops._TaskOpsMixin.drop_label_annotations` | `cveta2.application.client.task_ops._TaskOpsMixin.drop_label_annotations` | same |
| `cveta2._client_ops.task_ops._TaskOpsMixin._find_label_shapes` | `cveta2.application.client.task_ops._TaskOpsMixin._find_label_shapes` | same |
| `cveta2._client_ops.task_ops._TaskOpsMixin.count_task_shapes` | `cveta2.application.client.task_ops._TaskOpsMixin.count_task_shapes` | same |
| `cveta2._client_ops.task_ops._TaskOpsMixin.delete_task` | `cveta2.application.client.task_ops._TaskOpsMixin.delete_task` | same |
| `cveta2._client_ops.task_ops._TaskOpsMixin.set_task_jobs_status` | `cveta2.application.client.task_ops._TaskOpsMixin.set_task_jobs_status` | changed |
| `cveta2._client_ops.task_ops._TaskOpsMixin.complete_task` | `cveta2.application.client.task_ops._TaskOpsMixin.complete_task` | same |
| `cveta2._client_ops.fetch._format_task_choices` | `cveta2.application.client.fetch._format_task_choices` | same |
| `cveta2._client_ops.fetch._filter_tasks_for_fetch` | `cveta2.application.client.fetch._filter_tasks_for_fetch` | same |
| `cveta2._client_ops.fetch._numeric_selector_ids` | `cveta2.application.client.fetch._numeric_selector_ids` | same |
| `cveta2._client_ops.fetch._get_task_if_present` | `cveta2.application.client.fetch._get_task_if_present` | same |
| `cveta2._client_ops.fetch._resolve_selected_tasks_by_id` | `cveta2.application.client.fetch._resolve_selected_tasks_by_id` | changed |
| `cveta2._client_ops.fetch._select_tasks_for_fetch` | `cveta2.application.client.fetch._select_tasks_for_fetch` | changed |
| `cveta2._client_ops.fetch._FetchMixin.prepare_fetch` | `cveta2.application.client.fetch._FetchMixin.prepare_fetch` | changed |
| `cveta2._client_ops.fetch._FetchMixin._resolve_one_task_selector` | `cveta2.application.client.fetch._FetchMixin._resolve_one_task_selector` | same |
| `cveta2._client_ops.fetch._FetchMixin.resolve_task_selectors` | `cveta2.application.client.fetch._FetchMixin.resolve_task_selectors` | same |
| `cveta2._client_ops.fetch._FetchMixin.fetch_one_task` | `cveta2.application.client.fetch._FetchMixin.fetch_one_task` | same |
| `cveta2._client_ops.read._ReadMixin.list_organizations` | `cveta2.application.client.read._ReadMixin.list_organizations` | same |
| `cveta2._client_ops.read._ReadMixin.list_projects` | `cveta2.application.client.read._ReadMixin.list_projects` | same |
| `cveta2._client_ops.read._ReadMixin.get_project` | `cveta2.application.client.read._ReadMixin.get_project` | same |
| `cveta2._client_ops.read._ReadMixin.list_project_tasks` | `cveta2.application.client.read._ReadMixin.list_project_tasks` | same |
| `cveta2._client_ops.read._ReadMixin.get_task` | `cveta2.application.client.read._ReadMixin.get_task` | same |
| `cveta2._client_ops.read._ReadMixin.get_task_size` | `cveta2.application.client.read._ReadMixin.get_task_size` | same |
| `cveta2._client_ops.read._ReadMixin.list_new_completed_tasks` | `cveta2.application.client.read._ReadMixin.list_new_completed_tasks` | same |
| `cveta2._client_ops.read._ReadMixin.get_project_labels` | `cveta2.application.client.read._ReadMixin.get_project_labels` | same |
| `cveta2._client_ops.read._ReadMixin.count_label_usage` | `cveta2.application.client.read._ReadMixin.count_label_usage` | changed |
| `cveta2._client_ops.read._ReadMixin.resolve_project_id` | `cveta2.application.client.read._ReadMixin.resolve_project_id` | same |
| `cveta2._client_ops.read._ReadMixin.find_project_by_name` | `cveta2.application.client.read._ReadMixin.find_project_by_name` | same |
| `cveta2._client_ops.read._ReadMixin.detect_project_cloud_storage` | `cveta2.application.client.read._ReadMixin.detect_project_cloud_storage` | same |
| `cveta2._client.sdk_convert.convert_task` | `cveta2.adapters.cvat.sdk_convert.convert_task` | same |
| `cveta2._client.sdk_convert.extract_updated_date` | `cveta2.adapters.cvat.sdk_convert.extract_updated_date` | same |
| `cveta2._client.sdk_convert.convert_label` | `cveta2.adapters.cvat.sdk_convert.convert_label` | same |
| `cveta2._client.sdk_convert._raw_frame` | `cveta2.adapters.cvat.sdk_convert._raw_frame` | same |
| `cveta2._client.sdk_convert.convert_data_meta` | `cveta2.adapters.cvat.sdk_convert.convert_data_meta` | same |
| `cveta2._client.sdk_convert.data_meta_from_dict` | `cveta2.adapters.cvat.sdk_convert.data_meta_from_dict` | same |
| `cveta2._client.sdk_convert.convert_annotations` | `cveta2.adapters.cvat.sdk_convert.convert_annotations` | same |
| `cveta2._client.sdk_convert.convert_shape` | `cveta2.adapters.cvat.sdk_convert.convert_shape` | same |
| `cveta2._client.sdk_convert.convert_attributes` | `cveta2.adapters.cvat.sdk_convert.convert_attributes` | same |
| `cveta2._client.sdk_convert.extract_creator_username` | `cveta2.adapters.cvat.sdk_convert.extract_creator_username` | same |
| `cveta2._client.sdk_requests.build_task_write_request` | `cveta2.adapters.cvat.sdk_requests.build_task_write_request` | same |
| `cveta2._client.sdk_requests.build_data_request` | `cveta2.adapters.cvat.sdk_requests.build_data_request` | same |
| `cveta2._client.sdk_requests.build_new_shapes_payload` | `cveta2.adapters.cvat.sdk_requests.build_new_shapes_payload` | same |
| `cveta2._client.sdk_requests.build_delete_shapes_payload` | `cveta2.adapters.cvat.sdk_requests.build_delete_shapes_payload` | same |
| `cveta2._client.sdk_requests.build_issue_request` | `cveta2.adapters.cvat.sdk_requests.build_issue_request` | same |
| `cveta2._client.sdk_requests.build_deleted_frames_request` | `cveta2.adapters.cvat.sdk_requests.build_deleted_frames_request` | same |
| `cveta2._client.sdk_requests._build_label_patch_request` | `cveta2.adapters.cvat.sdk_requests._build_label_patch_request` | same |
| `cveta2._client.sdk_requests.build_labels_patch_request` | `cveta2.adapters.cvat.sdk_requests.build_labels_patch_request` | same |
| `cveta2._client.sdk_requests.build_job_patch_request` | `cveta2.adapters.cvat.sdk_requests.build_job_patch_request` | same |
| `cveta2.services.upload.read_exclude_names` | `cveta2.application.use_cases.upload.read_exclude_names` | changed |
| `cveta2.services.upload.split_deleted_rows` | `cveta2.application.use_cases.upload.split_deleted_rows` | same |
| `cveta2.services.upload.filter_frames_by_labels` | `cveta2.application.use_cases.upload.filter_frames_by_labels` | same |
| `cveta2.services.upload.build_upload_plan` | `cveta2.application.use_cases.upload.build_upload_plan` | same |
| `cveta2.services.upload.validate_labels` | `cveta2.application.use_cases.upload.validate_labels` | same |
| `cveta2.services.upload.build_search_dirs` | `cveta2.application.use_cases.upload.build_search_dirs` | changed |
| `cveta2.services.upload._warn_missing_images` | `cveta2.application.use_cases.upload._warn_missing_images` | same |
| `cveta2.services.upload._stage_images` | `cveta2.application.use_cases.upload._stage_images` | changed |
| `cveta2.services.upload._verify_existing_shapes` | `cveta2.application.use_cases.upload._verify_existing_shapes` | same |
| `cveta2.services.upload._ensure_annotations` | `cveta2.application.use_cases.upload._ensure_annotations` | same |
| `cveta2.services.upload._ensure_task` | `cveta2.application.use_cases.upload._ensure_task` | changed |
| `cveta2.services.upload._record_task_id` | `cveta2.application.use_cases.upload._record_task_id` | changed |
| `cveta2.services.upload._push_to_cvat` | `cveta2.application.use_cases.upload._push_to_cvat` | changed |
| `cveta2.services.upload._resume_manifest` | `cveta2.application.use_cases.upload._resume_manifest` | changed |
| `cveta2.services.upload._fresh_manifest` | `cveta2.application.use_cases.upload._fresh_manifest` | changed |
| `cveta2.services.upload.request_fingerprint` | `cveta2.application.use_cases.upload.request_fingerprint` | same |
| `cveta2.services.upload._completed_outcome` | `cveta2.application.use_cases.upload._completed_outcome` | same |
| `cveta2.services.upload._frames_match` | `cveta2.application.use_cases.upload._frames_match` | same |
| `cveta2.services.upload._preflight_resume_target` | `cveta2.application.use_cases.upload._preflight_resume_target` | same |
| `cveta2.services.upload.upload_dataset` | `cveta2.application.use_cases.upload.upload_dataset` | changed |
| `cveta2.services.convert.common._require_positive_dimensions` | `cveta2.domain.conversion._require_positive_dimensions` | same |
| `cveta2.services.convert.common._pixel_to_yolo` | `cveta2.domain.conversion._pixel_to_yolo` | same |
| `cveta2.services.convert.common._yolo_to_pixel` | `cveta2.domain.conversion._yolo_to_pixel` | same |
| `cveta2.services.convert.common._pixel_to_coco` | `cveta2.domain.conversion._pixel_to_coco` | same |
| `cveta2.services.convert.common._OnceWarner.__init__` | `cveta2.adapters.files.materialization._OnceWarner.__init__` | same |
| `cveta2.services.convert.common._OnceWarner.warn` | `cveta2.adapters.files.materialization._OnceWarner.warn` | same |
| `cveta2.services.convert.common._copy_after_reflink_failure` | `cveta2.adapters.files.materialization._copy_after_reflink_failure` | same |
| `cveta2.services.convert.common._reflink_or_fallback_copy` | `cveta2.adapters.files.materialization._reflink_or_fallback_copy` | same |
| `cveta2.services.convert.common._link_or_copy` | `cveta2.adapters.files.materialization._link_or_copy` | same |
| `cveta2.services.convert.common._build_search_dirs` | `cveta2.composition.conversion._build_search_dirs` | changed |
| `cveta2.services.convert.common._find_image_by_stem` | `cveta2.adapters.files.conversion._find_image_by_stem` | same |
| `cveta2.services.convert.common._get_image_size` | `cveta2.adapters.files.conversion._get_image_size` | same |
| `cveta2.services.convert.common._SizeCache.__init__` | `cveta2.application.use_cases.convert.common._SizeCache.__init__` | changed |
| `cveta2.services.convert.common._SizeCache.get` | `cveta2.application.use_cases.convert.common._SizeCache.get` | changed |
| `cveta2.services.convert.common._validate_splits` | `cveta2.domain.conversion._validate_splits` | same |
| `cveta2.services.convert.common._validate_export_rows` | `cveta2.domain.conversion._validate_export_rows` | same |
| `cveta2.services.convert.common._validate_export_box` | `cveta2.domain.conversion._validate_export_box` | same |
| `cveta2.services.convert.common.prepare_export` | `cveta2.application.use_cases.convert.common.prepare_export` | changed |
| `cveta2.services.convert.common._make_csv_row_base` | `cveta2.domain.conversion._make_csv_row_base` | same |
| `cveta2.services.convert.common._make_csv_row_box` | `cveta2.domain.conversion._make_csv_row_box` | same |
| `cveta2.services.convert.common._write_csv` | `cveta2.adapters.files.conversion._write_csv` | same |
| `cveta2.services.convert.coco._write_coco_split` | `cveta2.application.use_cases.convert.coco._write_coco_split` | changed |
| `cveta2.services.convert.coco._coco_owned_paths` | `cveta2.adapters.files.conversion._coco_owned_paths` | same |
| `cveta2.services.convert.coco._owned_split_files` | `cveta2.adapters.files.conversion._owned_split_files` | same |
| `cveta2.services.convert.coco._prune_coco_output` | `cveta2.adapters.files.conversion._prune_coco_output` | same |
| `cveta2.services.convert.coco.convert_to_coco` | `cveta2.application.use_cases.convert.coco.convert_to_coco` | changed |
| `cveta2.services.convert.yolo._write_box_labels` | `cveta2.application.use_cases.convert.yolo._write_box_labels` | changed |
| `cveta2.services.convert.yolo._write_none_labels` | `cveta2.application.use_cases.convert.yolo._write_none_labels` | changed |
| `cveta2.services.convert.yolo._prune_yolo_output` | `cveta2.adapters.files.conversion._prune_yolo_output` | same |
| `cveta2.services.convert.yolo._write_dataset_yaml` | `cveta2.application.use_cases.convert.yolo._write_dataset_yaml` | changed |
| `cveta2.services.convert.yolo.convert_to_yolo` | `cveta2.application.use_cases.convert.yolo.convert_to_yolo` | changed |
| `cveta2.services.convert.yolo._parse_label_file` | `cveta2.application.use_cases.convert.yolo._parse_label_file` | changed |
| `cveta2.services.convert.yolo._normalize_class_names` | `cveta2.domain.conversion._normalize_class_names` | same |
| `cveta2.services.convert.yolo._load_yaml` | `cveta2.adapters.files.conversion._load_yaml` | same |
| `cveta2.services.convert.yolo._load_class_names_yaml` | `cveta2.adapters.files.conversion._load_class_names_yaml` | same |
| `cveta2.services.convert.yolo._yolo_fields_to_row` | `cveta2.domain.conversion._yolo_fields_to_row` | same |
| `cveta2.services.convert.yolo._resolve_dataset_root` | `cveta2.adapters.files.conversion._resolve_dataset_root` | same |
| `cveta2.services.convert.yolo._resolve_listed_image` | `cveta2.adapters.files.conversion._resolve_listed_image` | same |
| `cveta2.services.convert.yolo._images_from_split_source` | `cveta2.adapters.files.conversion._images_from_split_source` | same |
| `cveta2.services.convert.yolo._split_images` | `cveta2.adapters.files.conversion._split_images` | same |
| `cveta2.services.convert.yolo._label_path_for_image` | `cveta2.domain.conversion._label_path_for_image` | same |
| `cveta2.services.convert.yolo._from_yolo_dataset` | `cveta2.application.use_cases.convert.yolo._from_yolo_dataset` | changed |
| `cveta2.services.convert.yolo._from_yolo_predictions` | `cveta2.application.use_cases.convert.yolo._from_yolo_predictions` | changed |
| `cveta2.services.convert.yolo.convert_from_yolo` | `cveta2.application.use_cases.convert.yolo.convert_from_yolo` | changed |
| `cveta2.config._env_flag` | `cveta2.adapters.config.settings._env_flag` | same |
| `cveta2.config.is_interactive_disabled` | `cveta2.adapters.config.settings.is_interactive_disabled` | same |
| `cveta2.config.is_cache_disabled` | `cveta2.adapters.config.settings.is_cache_disabled` | same |
| `cveta2.config.should_raise_on_fetch_failure` | `cveta2.adapters.config.settings.should_raise_on_fetch_failure` | same |
| `cveta2.config.require_interactive` | `cveta2.adapters.config.settings.require_interactive` | same |
| `cveta2.config.get_config_path` | `cveta2.adapters.config.settings.get_config_path` | same |
| `cveta2.config.get_projects_cache_path` | `cveta2.adapters.config.settings.get_projects_cache_path` | same |
| `cveta2.config._load_preset_data` | `cveta2.adapters.config.settings._load_preset_data` | same |
| `cveta2.config._load_raw_yaml` | `cveta2.adapters.config.settings._load_raw_yaml` | same |
| `cveta2.config._write_raw_yaml` | `cveta2.adapters.config.settings._write_raw_yaml` | same |
| `cveta2.config.SectionConfig._wrap_raw` | `cveta2.adapters.config.settings.SectionConfig._wrap_raw` | same |
| `cveta2.config.SectionConfig._dump` | `cveta2.adapters.config.settings.SectionConfig._dump` | same |
| `cveta2.config.SectionConfig._to_raw` | `cveta2.adapters.config.settings.SectionConfig._to_raw` | same |
| `cveta2.config.SectionConfig.load` | `cveta2.adapters.config.settings.SectionConfig.load` | same |
| `cveta2.config.SectionConfig.save` | `cveta2.adapters.config.settings.SectionConfig.save` | same |
| `cveta2.config._ProjectsSection._wrap_raw` | `cveta2.adapters.config.settings._ProjectsSection._wrap_raw` | same |
| `cveta2.config._ProjectsSection._to_raw` | `cveta2.adapters.config.settings._ProjectsSection._to_raw` | same |
| `cveta2.config._parse_timeout_env` | `cveta2.adapters.config.settings._parse_timeout_env` | same |
| `cveta2.config.CvatConfig._strip_host_trailing_slash` | `cveta2.adapters.config.settings.CvatConfig._strip_host_trailing_slash` | same |
| `cveta2.config.CvatConfig._from_cvat_section` | `cveta2.adapters.config.settings.CvatConfig._from_cvat_section` | same |
| `cveta2.config.CvatConfig.from_file` | `cveta2.adapters.config.settings.CvatConfig.from_file` | same |
| `cveta2.config.CvatConfig.from_env` | `cveta2.adapters.config.settings.CvatConfig.from_env` | same |
| `cveta2.config.CvatConfig.merge` | `cveta2.adapters.config.settings.CvatConfig.merge` | same |
| `cveta2.config.CvatConfig.load` | `cveta2.adapters.config.settings.CvatConfig.load` | same |
| `cveta2.config.CvatConfig.save_to_file` | `cveta2.adapters.config.settings.CvatConfig.save_to_file` | same |
| `cveta2.config.CvatConfig.require_credentials` | `cveta2.adapters.config.settings.CvatConfig.require_credentials` | same |
| `cveta2.config._none_if_falsy` | `cveta2.application.settings._none_if_falsy` | same |
| `cveta2.config._coerce_mapping_scalars` | `cveta2.adapters.config.settings._coerce_mapping_scalars` | same |
| `cveta2.config.ImageCacheConfig.get_cache_dir` | `cveta2.adapters.config.settings.ImageCacheConfig.get_cache_dir` | same |
| `cveta2.config.ImageCacheConfig.set_cache_dir` | `cveta2.adapters.config.settings.ImageCacheConfig.set_cache_dir` | same |
| `cveta2.config.CacheConfig._drop_non_mapping_projects` | `cveta2.adapters.config.settings.CacheConfig._drop_non_mapping_projects` | same |
| `cveta2.config.CacheConfig._to_raw` | `cveta2.adapters.config.settings.CacheConfig._to_raw` | same |
| `cveta2.config.CacheConfig.for_project` | `cveta2.adapters.config.settings.CacheConfig.for_project` | same |
| `cveta2.config.cache_dir_for_project` | `cveta2.adapters.config.settings.cache_dir_for_project` | same |
| `cveta2.config.images_cache_dir_from` | `cveta2.adapters.config.settings.images_cache_dir_from` | same |
| `cveta2.config.resolve_images_cache_dir` | `cveta2.adapters.config.settings.resolve_images_cache_dir` | same |
| `cveta2.config.SyncRootsConfig.get_root` | `cveta2.adapters.config.settings.SyncRootsConfig.get_root` | same |
| `cveta2.config.IgnoreConfig._parse_entries` | `cveta2.adapters.config.settings.IgnoreConfig._parse_entries` | same |
| `cveta2.config.IgnoreConfig.get_ignored_tasks` | `cveta2.adapters.config.settings.IgnoreConfig.get_ignored_tasks` | same |
| `cveta2.config.IgnoreConfig.get_ignored_entries` | `cveta2.adapters.config.settings.IgnoreConfig.get_ignored_entries` | same |
| `cveta2.config.IgnoreConfig.get_silent_task_ids` | `cveta2.adapters.config.settings.IgnoreConfig.get_silent_task_ids` | same |
| `cveta2.config.IgnoreConfig.add_task` | `cveta2.adapters.config.settings.IgnoreConfig.add_task` | same |
| `cveta2.config.IgnoreConfig.remove_task` | `cveta2.adapters.config.settings.IgnoreConfig.remove_task` | same |
| `cveta2.config._parse_ignore_entry` | `cveta2.adapters.config.settings._parse_ignore_entry` | same |
| `cveta2.config.NetworkConfig.resolve` | `cveta2.adapters.config.settings.NetworkConfig.resolve` | same |
| `cveta2.config._parse_int_env` | `cveta2.adapters.config.settings._parse_int_env` | same |
| `cveta2.config.is_clearml_disabled` | `cveta2.adapters.config.settings.is_clearml_disabled` | same |
| `cveta2.config.ClearmlConfig._wrap_raw` | `cveta2.adapters.config.settings.ClearmlConfig._wrap_raw` | same |
| `cveta2.config.ClearmlConfig._drop_invalid_mappings` | `cveta2.adapters.config.settings.ClearmlConfig._drop_invalid_mappings` | same |
| `cveta2.config.ClearmlConfig._to_raw` | `cveta2.adapters.config.settings.ClearmlConfig._to_raw` | same |
| `cveta2.config.ClearmlConfig.get_mapping` | `cveta2.adapters.config.settings.ClearmlConfig.get_mapping` | same |
| `cveta2.api._open` | `cveta2.interfaces.api._open` | same |
| `cveta2.api._config_path` | `cveta2.interfaces.api._config_path` | same |
| `cveta2.api._cache_flags` | `cveta2.interfaces.api._cache_flags` | same |
| `cveta2.api._resolve_fetch_target` | `cveta2.interfaces.api._resolve_fetch_target` | same |
| `cveta2.api._resolve_images_dir` | `cveta2.interfaces.api._resolve_images_dir` | same |
| `cveta2.api.fetch` | `cveta2.interfaces.api.fetch` | same |
| `cveta2.api.fetch_task` | `cveta2.interfaces.api.fetch_task` | same |
| `cveta2.api.upload` | `cveta2.interfaces.api.upload` | same |
| `cveta2.api.merge` | `cveta2.interfaces.api.merge` | same |
| `cveta2.api.whats_new` | `cveta2.interfaces.api.whats_new` | same |
| `cveta2.api.s3_sync` | `cveta2.interfaces.api.s3_sync` | same |
| `cveta2.api.get_labels` | `cveta2.interfaces.api.get_labels` | same |
| `cveta2.api.update_labels` | `cveta2.interfaces.api.update_labels` | same |
| `cveta2.api.ignore` | `cveta2.interfaces.api.ignore` | same |
| `cveta2.api._resolved_task` | `cveta2.interfaces.api._resolved_task` | same |
| `cveta2.api.task_mark_deleted` | `cveta2.interfaces.api.task_mark_deleted` | same |
| `cveta2.api.task_drop_label` | `cveta2.interfaces.api.task_drop_label` | same |
| `cveta2.api.task_delete` | `cveta2.interfaces.api.task_delete` | same |
| `cveta2.api.task_set_status` | `cveta2.interfaces.api.task_set_status` | same |
| `cveta2._client_ops.base._ClientBase.__init__` | `cveta2.application.client.base._ClientBase.__init__` | changed |
| `cveta2._client_ops.base._ClientBase.__enter__` | `cveta2.application.client.base._ClientBase.__enter__` | changed |
| `cveta2._client_ops.base._ClientBase.__exit__` | `cveta2.application.client.base._ClientBase.__exit__` | same |
| `cveta2._client_ops.base._ClientBase.api` | `cveta2.application.client.base._ClientBase.api` | same |
| `cveta2._client_ops.base._ClientBase.is_ready` | `cveta2.application.client.base._ClientBase.is_ready` | same |
| `cveta2._client_ops.base._ClientBase.host` | `cveta2.application.client.base._ClientBase.host` | changed |
| `cveta2._client_ops.base._ClientBase.organization` | `cveta2.application.client.base._ClientBase.organization` | same |
| `cveta2._client_ops.base._ClientBase.default_organization` | `cveta2.application.client.base._ClientBase.default_organization` | changed |
| `cveta2._client_ops.base._ClientBase.set_organization` | `cveta2.application.client.base._ClientBase.set_organization` | same |
| `cveta2._client_ops.base._ClientBase.open_task_session` | `cveta2.application.client.base._ClientBase.open_task_session` | same |
| `cveta2._client_ops.base._ClientBase._require_api` | `cveta2.application.client.base._ClientBase._require_api` | same |
| `cveta2._client_ops.images._ImageMixin.download_images` | `cveta2.application.client.images._ImageMixin.download_images` | changed |
| `cveta2._client_ops.images._ImageMixin.sync_project_images` | `cveta2.application.client.images._ImageMixin.sync_project_images` | changed |
| `cveta2.commands._helpers.echo_cli_command` | `cveta2.interfaces.commands._helpers.echo_cli_command` | same |
| `cveta2.commands._helpers.echo_if_prompted` | `cveta2.interfaces.commands._helpers.echo_if_prompted` | same |
| `cveta2.commands._helpers.config_path_from_args` | `cveta2.interfaces.commands._helpers.config_path_from_args` | same |
| `cveta2.commands._helpers.resolve_project_from_args` | `cveta2.interfaces.commands._helpers.resolve_project_from_args` | same |
| `cveta2.commands._helpers.resolve_project` | `cveta2.interfaces.commands._helpers.resolve_project` | same |
| `cveta2.commands._helpers.resolve_project_and_cloud_storage` | `cveta2.interfaces.commands._helpers.resolve_project_and_cloud_storage` | same |
| `cveta2.commands._helpers.project_cli_spec` | `cveta2.interfaces.commands._helpers.project_cli_spec` | same |
| `cveta2.commands._helpers.require_host` | `cveta2.interfaces.commands._helpers.require_host` | same |
| `cveta2.commands.interactive.primitives._handle_cancel` | `cveta2.interfaces.commands.interactive.primitives._handle_cancel` | same |
| `cveta2.commands.interactive.primitives.confirm` | `cveta2.interfaces.commands.interactive.primitives.confirm` | same |
| `cveta2.commands.interactive.primitives.confirm_or_exit` | `cveta2.interfaces.commands.interactive.primitives.confirm_or_exit` | same |
| `cveta2.commands.interactive.primitives.text` | `cveta2.interfaces.commands.interactive.primitives.text` | same |
| `cveta2.commands.interactive.primitives.path` | `cveta2.interfaces.commands.interactive.primitives.path` | same |
| `cveta2.commands.interactive.primitives.select_one` | `cveta2.interfaces.commands.interactive.primitives.select_one` | same |
| `cveta2.commands.interactive.primitives.select_many` | `cveta2.interfaces.commands.interactive.primitives.select_many` | same |
| `cveta2.commands.interactive.primitives.prompt_password` | `cveta2.interfaces.commands.interactive.primitives.prompt_password` | same |
| `cveta2.commands.upload._available_labels` | `cveta2.interfaces.commands.upload._available_labels` | same |
| `cveta2.commands.upload._select_labels` | `cveta2.interfaces.commands.upload._select_labels` | same |
| `cveta2.commands.upload._resolve_labels` | `cveta2.interfaces.commands.upload._resolve_labels` | same |
| `cveta2.commands.upload._resolve_task_name` | `cveta2.interfaces.commands.upload._resolve_task_name` | same |
| `cveta2.commands.upload.run_upload` | `cveta2.interfaces.commands.upload.run_upload` | same |
| `cveta2.services.fetch.load_ignore_sets` | `cveta2.composition.workflows.load_ignore_sets` | same |
| `cveta2.services.fetch.fetch_project` | `cveta2.application.use_cases.fetch.fetch_project` | changed |
| `cveta2.services.fetch._promote_completed_annotations` | `cveta2.application.use_cases.fetch._promote_completed_annotations` | changed |
| `cveta2.services.fetch._promote_task` | `cveta2.application.use_cases.fetch._promote_task` | same |
| `cveta2.services.fetch.fetch_selected_tasks` | `cveta2.application.use_cases.fetch.fetch_selected_tasks` | changed |
| `cveta2.services.fetch._fetch_core` | `cveta2.application.use_cases.fetch._fetch_core` | changed |
| `cveta2.services.fetch._build_task_cache` | `cveta2.application.use_cases.fetch._build_task_cache` | changed |
| `cveta2.services.fetch._CachePolicy.read` | `cveta2.application.use_cases.fetch._CachePolicy.read` | same |
| `cveta2.services.fetch._CachePolicy.write` | `cveta2.application.use_cases.fetch._CachePolicy.write` | same |
| `cveta2.services.fetch._FetchStats.record_hit` | `cveta2.application.use_cases.fetch._FetchStats.record_hit` | same |
| `cveta2.services.fetch._FetchStats.record_fetch` | `cveta2.application.use_cases.fetch._FetchStats.record_fetch` | same |
| `cveta2.services.fetch._FetchStats.log_summary` | `cveta2.application.use_cases.fetch._FetchStats.log_summary` | same |
| `cveta2.services.fetch._retrieve_task` | `cveta2.application.use_cases.fetch._retrieve_task` | changed |
| `cveta2.services.fetch._fetch_and_save_tasks` | `cveta2.application.use_cases.fetch._fetch_and_save_tasks` | changed |
| `cveta2._concurrency._WorkersMeta.s3` | `cveta2.adapters.execution.concurrency._WorkersMeta.s3` | same |
| `cveta2._concurrency._WorkersMeta.cvat` | `cveta2.adapters.execution.concurrency._WorkersMeta.cvat` | same |
| `cveta2._concurrency.configure_workers` | `cveta2.adapters.execution.concurrency.configure_workers` | same |
| `cveta2._concurrency._capture` | `cveta2.adapters.execution.concurrency._capture` | same |
| `cveta2._concurrency.run_concurrent` | `cveta2.adapters.execution.concurrency.run_concurrent` | same |
| `cveta2.upload_manifest.UploadManifest.describe` | `cveta2.domain.upload.UploadManifest.describe` | same |
| `cveta2.upload_manifest.validate_upload_boxes` | `cveta2.domain.upload.validate_upload_boxes` | same |
| `cveta2.upload_manifest.compute_fingerprint` | `cveta2.domain.upload.compute_fingerprint` | same |
| `cveta2.upload_manifest.normalize_upload_host` | `cveta2.domain.upload.normalize_upload_host` | same |
| `cveta2.upload_manifest.get_upload_manifest_dir` | `cveta2.adapters.files.manifests.get_upload_manifest_dir` | same |
| `cveta2.upload_manifest.save_manifest` | `cveta2.adapters.files.manifests.save_manifest` | same |
| `cveta2.upload_manifest.load_manifest` | `cveta2.adapters.files.manifests.load_manifest` | same |
| `cveta2.upload_manifest.list_manifests` | `cveta2.adapters.files.manifests.list_manifests` | same |
| `cveta2.upload_manifest.delete_manifest` | `cveta2.adapters.files.manifests.delete_manifest` | same |
| `cveta2.upload_manifest.compute_mapping_identity` | `cveta2.domain.upload.compute_mapping_identity` | same |
| `cveta2.upload_manifest.new_manifest` | `cveta2.adapters.files.manifests.new_manifest` | changed |
| `cveta2.upload_manifest._read_manifest` | `cveta2.adapters.files.manifests._read_manifest` | same |
| `cveta2.services.task_ops.resolved_task` | `cveta2.application.use_cases.task_ops.resolved_task` | changed |
| `cveta2._client.mapping._build_label_maps` | `cveta2.application.client.mapping._build_label_maps` | same |
| `cveta2.commands._bootstrap.open_client` | `cveta2.interfaces.commands._bootstrap.open_client` | same |
| `cveta2.fs_utils.default_cache_base` | `cveta2.adapters.files.shared.default_cache_base` | same |
| `cveta2.fs_utils._chmod_quiet` | `cveta2.adapters.files.shared._chmod_quiet` | same |
| `cveta2.fs_utils.ensure_shared_dir` | `cveta2.adapters.files.shared.ensure_shared_dir` | same |
| `cveta2.fs_utils.write_shared_bytes` | `cveta2.adapters.files.shared.write_shared_bytes` | same |
| `cveta2.fs_utils.replace_shared_bytes` | `cveta2.adapters.files.shared.replace_shared_bytes` | same |
| `cveta2.services.merge._read_deleted_names` | `cveta2.adapters.files.dataset.read_deleted_names` | same |
| `cveta2.services.fetch._write_task_csv` | `cveta2.adapters.files.task_output.LocalWorkflowFiles.write_task_csv` | changed |

The following split destinations supplement primary declarations: application initialization delegates production defaults/credential factories to `composition.client`; image methods delegate transfer construction to `adapters.s3.images`; fetch task-directory and per-task writes use `adapters.files.task_output`; old baseline sibling IO uses `adapters.files.dataset.read_baseline_siblings`; YOLO label parsing/text and COCO payload/text helpers use `domain.conversion`; conversion output setup and persistence use `adapters.files.conversion`. These modules are scoped even when only part of an old function moved.

## Equivalent inventory and exact edits

Each row records the baseline name, generated canonical name, original expression, replacement and static disposition. Historical justifications were retained during mapping. The three killed directory-parent exemptions were later retired; the remaining live entries all received the accepted full verdict below.

| Baseline mutant | Canonical generated mutant | Original → replacement | Static evidence |
|---|---|---|
| `cveta2._client.extractors.x__polygon_bounds__mutmut_3` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_3` | `"\u043c\u0435\u043d\u0435\u0435 \u0442\u0440\u0451\u0445 \u043f\u0430\u0440 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442" → "XX\u043c\u0435\u043d\u0435\u0435 \u0442\u0440\u0451\u0445 \u043f\u0430\u0440 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442XX"` | verified static identity |
| `cveta2._client.extractors.x__polygon_bounds__mutmut_4` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_4` | `"\u043c\u0435\u043d\u0435\u0435 \u0442\u0440\u0451\u0445 \u043f\u0430\u0440 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442" → "\u041c\u0415\u041d\u0415\u0415 \u0422\u0420\u0401\u0425 \u041f\u0410\u0420 \u041a\u041e\u041e\u0420\u0414\u0418\u041d\u0410\u0422"` | verified static identity |
| `cveta2._client.extractors.x__polygon_bounds__mutmut_8` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_8` | `"\u043d\u0435\u0447\u0451\u0442\u043d\u043e\u0435 \u0447\u0438\u0441\u043b\u043e \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442" → "XX\u043d\u0435\u0447\u0451\u0442\u043d\u043e\u0435 \u0447\u0438\u0441\u043b\u043e \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442XX"` | verified static identity |
| `cveta2._client.extractors.x__polygon_bounds__mutmut_9` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_9` | `"\u043d\u0435\u0447\u0451\u0442\u043d\u043e\u0435 \u0447\u0438\u0441\u043b\u043e \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442" → "\u041d\u0415\u0427\u0401\u0422\u041d\u041e\u0415 \u0427\u0418\u0421\u041b\u041e \u041a\u041e\u041e\u0420\u0414\u0418\u041d\u0410\u0422"` | verified static identity |
| `cveta2._client.extractors.x__polygon_bounds__mutmut_14` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_14` | `"\u043d\u0435\u0447\u0438\u0441\u043b\u043e\u0432\u044b\u0435 \u0438\u043b\u0438 \u0431\u0435\u0441\u043a\u043e\u043d\u0435\u0447\u043d\u044b\u0435 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b" → "XX\u043d\u0435\u0447\u0438\u0441\u043b\u043e\u0432\u044b\u0435 \u0438\u043b\u0438 \u0431\u0435\u0441\u043a\u043e\u043d\u0435\u0447\u043d\u044b\u0435 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044bXX"` | verified static identity |
| `cveta2._client.extractors.x__polygon_bounds__mutmut_15` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_15` | `"\u043d\u0435\u0447\u0438\u0441\u043b\u043e\u0432\u044b\u0435 \u0438\u043b\u0438 \u0431\u0435\u0441\u043a\u043e\u043d\u0435\u0447\u043d\u044b\u0435 \u043a\u043e\u043e\u0440\u0434\u0438\u043d\u0430\u0442\u044b" → "\u041d\u0415\u0427\u0418\u0421\u041b\u041e\u0412\u042b\u0415 \u0418\u041b\u0418 \u0411\u0415\u0421\u041a\u041e\u041d\u0415\u0427\u041d\u042b\u0415 \u041a\u041e\u041e\u0420\u0414\u0418\u041d\u0410\u0422\u042b"` | verified static identity |
| `cveta2._client.extractors.x__polygon_bounds__mutmut_30` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_30` | `"\u043d\u0443\u043b\u0435\u0432\u0430\u044f \u0448\u0438\u0440\u0438\u043d\u0430 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0438\u0432\u0430\u044e\u0449\u0435\u0433\u043e \u043f\u0440\u044f\u043c\u043e\u0443\u0433\u043e\u043b\u044c\u043d\u0438\u043a\u0430" → "XX\u043d\u0443\u043b\u0435\u0432\u0430\u044f \u0448\u0438\u0440\u0438\u043d\u0430 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0438\u0432\u0430\u044e\u0449\u0435\u0433\u043e \u043f\u0440\u044f\u043c\u043e\u0443\u0433\u043e\u043b\u044c\u043d\u0438\u043a\u0430XX"` | verified static identity |
| `cveta2._client.extractors.x__polygon_bounds__mutmut_31` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_31` | `"\u043d\u0443\u043b\u0435\u0432\u0430\u044f \u0448\u0438\u0440\u0438\u043d\u0430 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0438\u0432\u0430\u044e\u0449\u0435\u0433\u043e \u043f\u0440\u044f\u043c\u043e\u0443\u0433\u043e\u043b\u044c\u043d\u0438\u043a\u0430" → "\u041d\u0423\u041b\u0415\u0412\u0410\u042f \u0428\u0418\u0420\u0418\u041d\u0410 \u041e\u0413\u0420\u0410\u041d\u0418\u0427\u0418\u0412\u0410\u042e\u0429\u0415\u0413\u041e \u041f\u0420\u042f\u041c\u041e\u0423\u0413\u041e\u041b\u042c\u041d\u0418\u041a\u0410"` | verified static identity |
| `cveta2._client.extractors.x__polygon_bounds__mutmut_36` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_36` | `"\u043d\u0443\u043b\u0435\u0432\u0430\u044f \u0432\u044b\u0441\u043e\u0442\u0430 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0438\u0432\u0430\u044e\u0449\u0435\u0433\u043e \u043f\u0440\u044f\u043c\u043e\u0443\u0433\u043e\u043b\u044c\u043d\u0438\u043a\u0430" → "XX\u043d\u0443\u043b\u0435\u0432\u0430\u044f \u0432\u044b\u0441\u043e\u0442\u0430 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0438\u0432\u0430\u044e\u0449\u0435\u0433\u043e \u043f\u0440\u044f\u043c\u043e\u0443\u0433\u043e\u043b\u044c\u043d\u0438\u043a\u0430XX"` | verified static identity |
| `cveta2._client.extractors.x__polygon_bounds__mutmut_37` | `cveta2.application.client.extractors.x__polygon_bounds__mutmut_37` | `"\u043d\u0443\u043b\u0435\u0432\u0430\u044f \u0432\u044b\u0441\u043e\u0442\u0430 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0438\u0432\u0430\u044e\u0449\u0435\u0433\u043e \u043f\u0440\u044f\u043c\u043e\u0443\u0433\u043e\u043b\u044c\u043d\u0438\u043a\u0430" → "\u041d\u0423\u041b\u0415\u0412\u0410\u042f \u0412\u042b\u0421\u041e\u0422\u0410 \u041e\u0413\u0420\u0410\u041d\u0418\u0427\u0418\u0412\u0410\u042e\u0429\u0415\u0413\u041e \u041f\u0420\u042f\u041c\u041e\u0423\u0413\u041e\u041b\u042c\u041d\u0418\u041a\u0410"` | verified static identity |
| `cveta2._client_ops.fetch.xǁ_FetchMixinǁ_resolve_one_task_selector__mutmut_18` | `cveta2.application.client.fetch.xǁ_FetchMixinǁ_resolve_one_task_selector__mutmut_18` | `"\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 ID \u0437\u0430\u0434\u0430\u0447\u0438." → "XX\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 ID \u0437\u0430\u0434\u0430\u0447\u0438.XX"` | verified static identity |
| `cveta2._client_ops.fetch.xǁ_FetchMixinǁ_resolve_one_task_selector__mutmut_19` | `cveta2.application.client.fetch.xǁ_FetchMixinǁ_resolve_one_task_selector__mutmut_19` | `"\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 ID \u0437\u0430\u0434\u0430\u0447\u0438." → "\u0443\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 id \u0437\u0430\u0434\u0430\u0447\u0438."` | verified static identity |
| `cveta2._client_ops.fetch.xǁ_FetchMixinǁ_resolve_one_task_selector__mutmut_20` | `cveta2.application.client.fetch.xǁ_FetchMixinǁ_resolve_one_task_selector__mutmut_20` | `"\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 ID \u0437\u0430\u0434\u0430\u0447\u0438." → "\u0423\u041a\u0410\u0416\u0418\u0422\u0415 \u0427\u0418\u0421\u041b\u041e\u0412\u041e\u0419 ID \u0417\u0410\u0414\u0410\u0427\u0418."` | verified static identity |
| `cveta2.services.upload.x_request_fingerprint__mutmut_13` | `cveta2.application.use_cases.upload.x_request_fingerprint__mutmut_13` | `"segment_size" → "XXsegment_sizeXX"` | verified static identity |
| `cveta2.services.upload.x_request_fingerprint__mutmut_14` | `cveta2.application.use_cases.upload.x_request_fingerprint__mutmut_14` | `"segment_size" → "SEGMENT_SIZE"` | verified static identity |
| `cveta2.services.upload.x_request_fingerprint__mutmut_15` | `cveta2.application.use_cases.upload.x_request_fingerprint__mutmut_15` | `"image_quality" → "XXimage_qualityXX"` | verified static identity |
| `cveta2.services.upload.x_request_fingerprint__mutmut_16` | `cveta2.application.use_cases.upload.x_request_fingerprint__mutmut_16` | `"image_quality" → "IMAGE_QUALITY"` | verified static identity |
| `cveta2.services.upload.x_request_fingerprint__mutmut_17` | `cveta2.application.use_cases.upload.x_request_fingerprint__mutmut_17` | `"mark_all_deleted" → "XXmark_all_deletedXX"` | verified static identity |
| `cveta2.services.upload.x_request_fingerprint__mutmut_18` | `cveta2.application.use_cases.upload.x_request_fingerprint__mutmut_18` | `"mark_all_deleted" → "MARK_ALL_DELETED"` | verified static identity |
| `cveta2.services.upload.x_request_fingerprint__mutmut_19` | `cveta2.application.use_cases.upload.x_request_fingerprint__mutmut_19` | `"complete" → "XXcompleteXX"` | verified static identity |
| `cveta2.services.upload.x_request_fingerprint__mutmut_20` | `cveta2.application.use_cases.upload.x_request_fingerprint__mutmut_20` | `"complete" → "COMPLETE"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_5` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_5` | `"images" → "XXimagesXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_6` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_6` | `"images" → "IMAGES"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_9` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_9` | `"deleted" → "XXdeletedXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_10` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_10` | `"deleted" → "DELETED"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_12` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_12` | `"labels" → "XXlabelsXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_13` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_13` | `"labels" → "LABELS"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_15` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_15` | `"options" → "XXoptionsXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_16` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_16` | `"options" → "OPTIONS"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_18` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_18` | `"task_name" → "XXtask_nameXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_19` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_19` | `"task_name" → "TASK_NAME"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_56` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_56` | `"annotations" → "XXannotationsXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_57` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_57` | `"annotations" → "ANNOTATIONS"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_36` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_36` | `"records" → "RECORDS"` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_43` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_43` | `json.dumps(         normalized,         sort_keys=True,         ensure_ascii=False,         default=str,         allow_nan=False,     ) → json.dumps(         normalized,         sort_keys=None,         ensure_ascii=False,         default=str,         allow_nan=False,     )` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_48` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_48` | `json.dumps(         normalized,         sort_keys=True,         ensure_ascii=False,         default=str,         allow_nan=False,     ) → json.dumps(         normalized,         ensure_ascii=False,         default=str,         allow_nan=False,     )` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_52` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_52` | `True → False` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_44` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_44` | `json.dumps(         normalized,         sort_keys=True,         ensure_ascii=False,         default=str,         allow_nan=False,     ) → json.dumps(         normalized,         sort_keys=True,         ensure_ascii=None,         default=str,         allow_nan=False,     )` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_62` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_62` | `json.dumps(intent, sort_keys=True, ensure_ascii=False) → json.dumps(intent, sort_keys=True, ensure_ascii=None)` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_49` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_49` | `json.dumps(         normalized,         sort_keys=True,         ensure_ascii=False,         default=str,         allow_nan=False,     ) → json.dumps(         normalized,         sort_keys=True,         default=str,         allow_nan=False,     )` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_53` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_53` | `False → True` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_65` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_65` | `json.dumps(intent, sort_keys=True, ensure_ascii=False) → json.dumps(intent, sort_keys=True, )` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_67` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_67` | `False → True` | verified static identity |
| `cveta2.upload_manifest.x_compute_fingerprint__mutmut_46` | `cveta2.domain.upload.x_compute_fingerprint__mutmut_46` | `json.dumps(         normalized,         sort_keys=True,         ensure_ascii=False,         default=str,         allow_nan=False,     ) → json.dumps(         normalized,         sort_keys=True,         ensure_ascii=False,         default=str,         allow_nan=None,     )` | verified static identity |
| `cveta2.upload_manifest.x_compute_mapping_identity__mutmut_2` | `cveta2.domain.upload.x_compute_mapping_identity__mutmut_2` | `"storage" → "XXstorageXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_mapping_identity__mutmut_3` | `cveta2.domain.upload.x_compute_mapping_identity__mutmut_3` | `"storage" → "STORAGE"` | verified static identity |
| `cveta2.upload_manifest.x_compute_mapping_identity__mutmut_7` | `cveta2.domain.upload.x_compute_mapping_identity__mutmut_7` | `"mapping" → "XXmappingXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_mapping_identity__mutmut_8` | `cveta2.domain.upload.x_compute_mapping_identity__mutmut_8` | `"mapping" → "MAPPING"` | verified static identity |
| `cveta2.upload_manifest.x_compute_mapping_identity__mutmut_9` | `cveta2.domain.upload.x_compute_mapping_identity__mutmut_9` | `"frames" → "XXframesXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_mapping_identity__mutmut_10` | `cveta2.domain.upload.x_compute_mapping_identity__mutmut_10` | `"frames" → "FRAMES"` | verified static identity |
| `cveta2.upload_manifest.x_compute_mapping_identity__mutmut_4` | `cveta2.domain.upload.x_compute_mapping_identity__mutmut_4` | `manifest.cs_info.model_dump(mode="json") → manifest.cs_info.model_dump(mode=None)` | verified static identity |
| `cveta2.upload_manifest.x_compute_mapping_identity__mutmut_5` | `cveta2.domain.upload.x_compute_mapping_identity__mutmut_5` | `"json" → "XXjsonXX"` | verified static identity |
| `cveta2.upload_manifest.x_compute_mapping_identity__mutmut_6` | `cveta2.domain.upload.x_compute_mapping_identity__mutmut_6` | `"json" → "JSON"` | verified static identity |
| `cveta2.services.upload.x__frames_match__mutmut_17` | `cveta2.application.use_cases.upload.x__frames_match__mutmut_17` | `shortened = False → shortened = None` | verified static identity |
| `cveta2.services.upload.x__frames_match__mutmut_21` | `cveta2.application.use_cases.upload.x__frames_match__mutmut_21` | `zip(actual, expected, strict=True) → zip(actual, expected, strict=None)` | verified static identity |
| `cveta2.services.upload.x__frames_match__mutmut_24` | `cveta2.application.use_cases.upload.x__frames_match__mutmut_24` | `zip(actual, expected, strict=True) → zip(actual, expected, )` | verified static identity |
| `cveta2.services.upload.x__frames_match__mutmut_25` | `cveta2.application.use_cases.upload.x__frames_match__mutmut_25` | `True → False` | verified static identity |
| `cveta2.services.upload.x__resume_manifest__mutmut_14` | `cveta2.application.use_cases.upload.x__resume_manifest__mutmut_14` | `"\u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u043d\u0435 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 \u043f\u043e\u043b\u043d\u043e\u0433\u043e \u043d\u0430\u043c\u0435\u0440\u0435\u043d\u0438\u044f; " → "XX\u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u043d\u0435 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 \u043f\u043e\u043b\u043d\u043e\u0433\u043e \u043d\u0430\u043c\u0435\u0440\u0435\u043d\u0438\u044f; XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x__resume_manifest__mutmut_15` | `cveta2.application.use_cases.upload.x__resume_manifest__mutmut_15` | `"\u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u043d\u0435 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 \u043f\u043e\u043b\u043d\u043e\u0433\u043e \u043d\u0430\u043c\u0435\u0440\u0435\u043d\u0438\u044f; " → "\u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u043d\u0435 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 \u043f\u043e\u043b\u043d\u043e\u0433\u043e \u043d\u0430\u043c\u0435\u0440\u0435\u043d\u0438\u044f; "` | changed: unique edit candidate |
| `cveta2.services.upload.x__resume_manifest__mutmut_17` | `cveta2.application.use_cases.upload.x__resume_manifest__mutmut_17` | `"\u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u043d\u0435\u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e." → "XX\u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u043d\u0435\u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e.XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x__resume_manifest__mutmut_18` | `cveta2.application.use_cases.upload.x__resume_manifest__mutmut_18` | `"\u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u043d\u0435\u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e." → "\u041f\u0420\u041e\u0414\u041e\u041b\u0416\u0415\u041d\u0418\u0415 \u041d\u0415\u0411\u0415\u0417\u041e\u041f\u0410\u0421\u041d\u041e."` | changed: unique edit candidate |
| `cveta2.services.upload.x__resume_manifest__mutmut_28` | `cveta2.application.use_cases.upload.x__resume_manifest__mutmut_28` | `"\n" → "XX\nXX"` | changed: unique edit candidate |
| `cveta2._client_ops.fetch.x__resolve_selected_tasks_by_id__mutmut_12` | `cveta2.application.client.fetch.x__resolve_selected_tasks_by_id__mutmut_12` | `run_concurrent(     task_ids,     lambda task_id: _get_task_if_present(api, task_id),     max_workers=Workers.cvat,     catch=(),     desc="Resolving tasks",     unit="task", ) → run_concurrent(     task_ids,     lambda task_id: _get_task_if_present(api, task_id),     max_workers=Workers.cvat,     catch=(),     desc=None,     unit="task", )` | changed: reviewed edit mapping |
| `cveta2._client_ops.fetch.xǁ_FetchMixinǁfetch_one_task__mutmut_22` | `cveta2.application.client.fetch.xǁ_FetchMixinǁfetch_one_task__mutmut_22` | `issues = [] → issues = None` | verified static identity |
| `cveta2._client_ops.write.x__issues_not_yet_on_task__mutmut_34` | `cveta2.application.client.write.x__issues_not_yet_on_task__mutmut_34` | `zip(position, issue.position, strict=True) → zip(position, issue.position, strict=None)` | verified static identity |
| `cveta2._client_ops.write.x__issues_not_yet_on_task__mutmut_37` | `cveta2.application.client.write.x__issues_not_yet_on_task__mutmut_37` | `zip(position, issue.position, strict=True) → zip(position, issue.position, )` | verified static identity |
| `cveta2._client_ops.write.x__issues_not_yet_on_task__mutmut_38` | `cveta2.application.client.write.x__issues_not_yet_on_task__mutmut_38` | `True → False` | verified static identity |
| `cveta2._client_ops.write.xǁ_WriteMixinǁcreate_task_issues__mutmut_26` | `cveta2.application.client.write.xǁ_WriteMixinǁcreate_task_issues__mutmut_26` | `already = len(built.issues) - len(pending) → already = None` | changed: unique edit candidate |
| `cveta2._client_ops.write.xǁ_WriteMixinǁcreate_task_issues__mutmut_27` | `cveta2.application.client.write.xǁ_WriteMixinǁcreate_task_issues__mutmut_27` | `len(built.issues) - len(pending) → len(built.issues) + len(pending)` | changed: unique edit candidate |
| `cveta2._client_ops.write.xǁ_WriteMixinǁcreate_task_issues__mutmut_32` | `cveta2.application.client.write.xǁ_WriteMixinǁcreate_task_issues__mutmut_32` | `run_concurrent(     pending,     api.create_issue,     max_workers=Workers.cvat,     catch=(),     desc="Creating issues",     unit="issue", ) → run_concurrent(     pending,     api.create_issue,     max_workers=Workers.cvat,     catch=(),     desc=None,     unit="issue", )` | changed: reviewed edit mapping |
| `cveta2.upload_manifest.xǁUploadManifestǁdescribe__mutmut_2` | `cveta2.domain.upload.xǁUploadManifestǁdescribe__mutmut_2` | `'—' → 'XX—XX'` | verified static identity |
| `cveta2.upload_manifest.x_validate_upload_boxes__mutmut_46` | `cveta2.domain.upload.x_validate_upload_boxes__mutmut_46` | `", " → "XX, XX"` | verified static identity |
| `cveta2.upload_manifest.x_validate_upload_boxes__mutmut_48` | `cveta2.domain.upload.x_validate_upload_boxes__mutmut_48` | `row.get('image_name', '?') → row.get('image_name', None)` | verified static identity |
| `cveta2.upload_manifest.x_validate_upload_boxes__mutmut_50` | `cveta2.domain.upload.x_validate_upload_boxes__mutmut_50` | `row.get('image_name', '?') → row.get('image_name', )` | verified static identity |
| `cveta2.upload_manifest.x_validate_upload_boxes__mutmut_53` | `cveta2.domain.upload.x_validate_upload_boxes__mutmut_53` | `'?' → 'XX?XX'` | verified static identity |
| `cveta2.upload_manifest.x_save_manifest__mutmut_13` | `cveta2.adapters.files.manifests.x_save_manifest__mutmut_13` | `"\u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430; \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d\u043d\u043e\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u043f\u0435\u0440\u0435\u0434 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435\u043c." → "XX\u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430; \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d\u043d\u043e\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u043f\u0435\u0440\u0435\u0434 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435\u043c.XX"` | verified static identity |
| `cveta2.upload_manifest.x_save_manifest__mutmut_14` | `cveta2.adapters.files.manifests.x_save_manifest__mutmut_14` | `"\u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430; \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d\u043d\u043e\u0435 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u043f\u0435\u0440\u0435\u0434 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435\u043c." → "\u041d\u0415 \u0412\u042b\u041f\u041e\u041b\u041d\u0415\u041d\u0410; \u041f\u0420\u041e\u0412\u0415\u0420\u042c\u0422\u0415 \u0421\u041e\u0425\u0420\u0410\u041d\u0401\u041d\u041d\u041e\u0415 \u0421\u041e\u0421\u0422\u041e\u042f\u041d\u0418\u0415 \u041f\u0415\u0420\u0415\u0414 \u041f\u0420\u041e\u0414\u041e\u041b\u0416\u0415\u041d\u0418\u0415\u041c."` | verified static identity |
| `cveta2._client_ops.read.xǁ_ReadMixinǁfind_project_by_name__mutmut_19` | `cveta2.application.client.read.xǁ_ReadMixinǁfind_project_by_name__mutmut_19` | `"\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 ID \u043f\u0440\u043e\u0435\u043a\u0442\u0430." → "XX\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 ID \u043f\u0440\u043e\u0435\u043a\u0442\u0430.XX"` | verified static identity |
| `cveta2._client_ops.read.xǁ_ReadMixinǁfind_project_by_name__mutmut_20` | `cveta2.application.client.read.xǁ_ReadMixinǁfind_project_by_name__mutmut_20` | `"\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 ID \u043f\u0440\u043e\u0435\u043a\u0442\u0430." → "\u0443\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 id \u043f\u0440\u043e\u0435\u043a\u0442\u0430."` | verified static identity |
| `cveta2._client_ops.read.xǁ_ReadMixinǁfind_project_by_name__mutmut_21` | `cveta2.application.client.read.xǁ_ReadMixinǁfind_project_by_name__mutmut_21` | `"\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e\u0432\u043e\u0439 ID \u043f\u0440\u043e\u0435\u043a\u0442\u0430." → "\u0423\u041a\u0410\u0416\u0418\u0422\u0415 \u0427\u0418\u0421\u041b\u041e\u0412\u041e\u0419 ID \u041f\u0420\u041e\u0415\u041a\u0422\u0410."` | verified static identity |
| `cveta2.services.upload.x__verify_existing_shapes__mutmut_58` | `cveta2.application.use_cases.upload.x__verify_existing_shapes__mutmut_58` | `"(\u0447\u0430\u0441\u0442\u0438\u0447\u043d\u044b\u0435 \u0438\u043b\u0438 \u0438\u0437\u043c\u0435\u043d\u0451\u043d\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435). \u0417\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u043f\u043e\u0432\u0442\u043e\u0440\u044f\u0435\u0442\u0441\u044f." → "XX(\u0447\u0430\u0441\u0442\u0438\u0447\u043d\u044b\u0435 \u0438\u043b\u0438 \u0438\u0437\u043c\u0435\u043d\u0451\u043d\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435). \u0417\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u043f\u043e\u0432\u0442\u043e\u0440\u044f\u0435\u0442\u0441\u044f.XX"` | verified static identity |
| `cveta2.services.upload.x__verify_existing_shapes__mutmut_59` | `cveta2.application.use_cases.upload.x__verify_existing_shapes__mutmut_59` | `"(\u0447\u0430\u0441\u0442\u0438\u0447\u043d\u044b\u0435 \u0438\u043b\u0438 \u0438\u0437\u043c\u0435\u043d\u0451\u043d\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435). \u0417\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u043f\u043e\u0432\u0442\u043e\u0440\u044f\u0435\u0442\u0441\u044f." → "(\u0447\u0430\u0441\u0442\u0438\u0447\u043d\u044b\u0435 \u0438\u043b\u0438 \u0438\u0437\u043c\u0435\u043d\u0451\u043d\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435). \u0437\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u043f\u043e\u0432\u0442\u043e\u0440\u044f\u0435\u0442\u0441\u044f."` | verified static identity |
| `cveta2.services.upload.x__verify_existing_shapes__mutmut_60` | `cveta2.application.use_cases.upload.x__verify_existing_shapes__mutmut_60` | `"(\u0447\u0430\u0441\u0442\u0438\u0447\u043d\u044b\u0435 \u0438\u043b\u0438 \u0438\u0437\u043c\u0435\u043d\u0451\u043d\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435). \u0417\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u043f\u043e\u0432\u0442\u043e\u0440\u044f\u0435\u0442\u0441\u044f." → "(\u0427\u0410\u0421\u0422\u0418\u0427\u041d\u042b\u0415 \u0418\u041b\u0418 \u0418\u0417\u041c\u0415\u041d\u0401\u041d\u041d\u042b\u0415 \u0414\u0410\u041d\u041d\u042b\u0415). \u0417\u0410\u041f\u0418\u0421\u042c \u041d\u0415 \u041f\u041e\u0412\u0422\u041e\u0420\u042f\u0415\u0422\u0421\u042f."` | verified static identity |
| `cveta2.services.upload.x__ensure_task__mutmut_5` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_5` | `"\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 CVAT \u0432\u0440\u0443\u0447\u043d\u0443\u044e; " → "XX\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 CVAT \u0432\u0440\u0443\u0447\u043d\u0443\u044e; XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_6` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_6` | `"\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d. \u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 CVAT \u0432\u0440\u0443\u0447\u043d\u0443\u044e; " → "\u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d. \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 cvat \u0432\u0440\u0443\u0447\u043d\u0443\u044e; "` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_8` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_8` | `"\u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u043d\u043e\u0432\u043e\u0439 \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e." → "XX\u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u043d\u043e\u0432\u043e\u0439 \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e.XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_9` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_9` | `"\u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u043d\u043e\u0432\u043e\u0439 \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e." → "\u0410\u0412\u0422\u041e\u041c\u0410\u0422\u0418\u0427\u0415\u0421\u041a\u041e\u0415 \u0421\u041e\u0417\u0414\u0410\u041d\u0418\u0415 \u041d\u041e\u0412\u041e\u0419 \u0417\u0410\u0414\u0410\u0427\u0418 \u041d\u0415\u0411\u0415\u0417\u041e\u041f\u0410\u0421\u041d\u041e."` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_42` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_44` | `"\u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c \u043d\u0435\u043b\u044c\u0437\u044f; \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0430." → "XX\u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c \u043d\u0435\u043b\u044c\u0437\u044f; \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0430.XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_43` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_45` | `"\u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c \u043d\u0435\u043b\u044c\u0437\u044f; \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0430." → "\u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c \u043d\u0435\u043b\u044c\u0437\u044f; \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0430."` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_44` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_46` | `"\u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c \u043d\u0435\u043b\u044c\u0437\u044f; \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0430." → "\u041f\u0420\u041e\u0414\u041e\u041b\u0416\u0418\u0422\u042c \u041d\u0415\u041b\u042c\u0417\u042f; \u0417\u0410\u0414\u0410\u0427\u0410 \u041d\u0415 \u0418\u0417\u041c\u0415\u041d\u0415\u041d\u0410."` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_59` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_61` | `"\u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430." → "XX\u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430.XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_60` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_62` | `"\u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430." → "\u0417\u0410\u041f\u0418\u0421\u042c \u0417\u0410\u041f\u0420\u0415\u0429\u0415\u041d\u0410."` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_64` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_66` | `"\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d. \u0414\u043e\u0436\u0434\u0438\u0442\u0435\u0441\u044c \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438 \u0438\u043b\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0437\u0430\u0434\u0430\u0447\u0443 \u0432\u0440\u0443\u0447\u043d\u0443\u044e. " → "XX\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d. \u0414\u043e\u0436\u0434\u0438\u0442\u0435\u0441\u044c \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438 \u0438\u043b\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0437\u0430\u0434\u0430\u0447\u0443 \u0432\u0440\u0443\u0447\u043d\u0443\u044e. XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_65` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_67` | `"\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d. \u0414\u043e\u0436\u0434\u0438\u0442\u0435\u0441\u044c \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438 \u0438\u043b\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0437\u0430\u0434\u0430\u0447\u0443 \u0432\u0440\u0443\u0447\u043d\u0443\u044e. " → "\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d. \u0434\u043e\u0436\u0434\u0438\u0442\u0435\u0441\u044c \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438 \u0438\u043b\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0437\u0430\u0434\u0430\u0447\u0443 \u0432\u0440\u0443\u0447\u043d\u0443\u044e. "` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_67` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_69` | `"\u0417\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0443\u0434\u0430\u043b\u0435\u043d\u0430, \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u0430\u044f \u0437\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f." → "XX\u0417\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0443\u0434\u0430\u043b\u0435\u043d\u0430, \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u0430\u044f \u0437\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f.XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_68` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_70` | `"\u0417\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0443\u0434\u0430\u043b\u0435\u043d\u0430, \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u0430\u044f \u0437\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f." → "\u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0443\u0434\u0430\u043b\u0435\u043d\u0430, \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u0430\u044f \u0437\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f."` | changed: unique edit candidate |
| `cveta2.services.upload.x__ensure_task__mutmut_69` | `cveta2.application.use_cases.upload.x__ensure_task__mutmut_71` | `"\u0417\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0443\u0434\u0430\u043b\u0435\u043d\u0430, \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u0430\u044f \u0437\u0430\u043f\u0438\u0441\u044c \u043d\u0435 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f." → "\u0417\u0410\u0414\u0410\u0427\u0410 \u041d\u0415 \u0423\u0414\u0410\u041b\u0415\u041d\u0410, \u041f\u041e\u0412\u0422\u041e\u0420\u041d\u0410\u042f \u0417\u0410\u041f\u0418\u0421\u042c \u041d\u0415 \u0412\u042b\u041f\u041e\u041b\u041d\u042f\u0415\u0422\u0421\u042f."` | changed: unique edit candidate |
| `cveta2.services.upload.x__completed_outcome__mutmut_5` | `cveta2.application.use_cases.upload.x__completed_outcome__mutmut_5` | `"\u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u043e\u0439 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0435\u043d\u043e; \u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430." → "XX\u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u043e\u0439 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0435\u043d\u043e; \u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430.XX"` | verified static identity |
| `cveta2.services.upload.x__completed_outcome__mutmut_6` | `cveta2.application.use_cases.upload.x__completed_outcome__mutmut_6` | `"\u0421\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u043e\u0439 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0435\u043d\u043e; \u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430." → "\u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d\u043d\u043e\u0439 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u043f\u043e\u0432\u0440\u0435\u0436\u0434\u0435\u043d\u043e; \u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430."` | verified static identity |
| `cveta2.services.upload.x__preflight_resume_target__mutmut_3` | `cveta2.application.use_cases.upload.x__preflight_resume_target__mutmut_3` | `"ID \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d; \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e." → "XXID \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d; \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e.XX"` | verified static identity |
| `cveta2.services.upload.x__preflight_resume_target__mutmut_4` | `cveta2.application.use_cases.upload.x__preflight_resume_target__mutmut_4` | `"ID \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d; \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e." → "id \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d; \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e."` | verified static identity |
| `cveta2.services.upload.x__preflight_resume_target__mutmut_5` | `cveta2.application.use_cases.upload.x__preflight_resume_target__mutmut_5` | `"ID \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d; \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e." → "ID \u0417\u0410\u0414\u0410\u0427\u0418 \u041d\u0415\u0418\u0417\u0412\u0415\u0421\u0422\u0415\u041d; \u041f\u0420\u041e\u0414\u041e\u041b\u0416\u0415\u041d\u0418\u0415 \u0417\u0410\u041f\u0420\u0415\u0429\u0415\u041d\u041e."` | verified static identity |
| `cveta2.services.upload.x__preflight_resume_target__mutmut_26` | `cveta2.application.use_cases.upload.x__preflight_resume_target__mutmut_26` | `"\u0435\u0449\u0451 \u043d\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430; \u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430." → "XX\u0435\u0449\u0451 \u043d\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430; \u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430.XX"` | verified static identity |
| `cveta2.services.upload.x__preflight_resume_target__mutmut_27` | `cveta2.application.use_cases.upload.x__preflight_resume_target__mutmut_27` | `"\u0435\u0449\u0451 \u043d\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430; \u0437\u0430\u043f\u0438\u0441\u044c \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u0430." → "\u0415\u0429\u0401 \u041d\u0415 \u0417\u0410\u0412\u0415\u0420\u0428\u0415\u041d\u0410; \u0417\u0410\u041f\u0418\u0421\u042c \u0417\u0410\u041f\u0420\u0415\u0429\u0415\u041d\u0410."` | verified static identity |
| `cveta2.services.upload.x_upload_dataset__mutmut_27` | `cveta2.application.use_cases.upload.x_upload_dataset__mutmut_29` | `"\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d; \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 CVAT \u0432\u0440\u0443\u0447\u043d\u0443\u044e. " → "XX\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d; \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 CVAT \u0432\u0440\u0443\u0447\u043d\u0443\u044e. XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x_upload_dataset__mutmut_28` | `cveta2.application.use_cases.upload.x_upload_dataset__mutmut_30` | `"\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d; \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 CVAT \u0432\u0440\u0443\u0447\u043d\u0443\u044e. " → "\u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u0437\u0430\u0434\u0430\u0447\u0438 \u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u0435\u043d; \u043f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 cvat \u0432\u0440\u0443\u0447\u043d\u0443\u044e. "` | changed: unique edit candidate |
| `cveta2.services.upload.x_upload_dataset__mutmut_30` | `cveta2.application.use_cases.upload.x_upload_dataset__mutmut_32` | `"\u041d\u043e\u0432\u0430\u044f \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u0451\u0442\u0441\u044f." → "XX\u041d\u043e\u0432\u0430\u044f \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u0451\u0442\u0441\u044f.XX"` | changed: unique edit candidate |
| `cveta2.services.upload.x_upload_dataset__mutmut_31` | `cveta2.application.use_cases.upload.x_upload_dataset__mutmut_33` | `"\u041d\u043e\u0432\u0430\u044f \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u0451\u0442\u0441\u044f." → "\u043d\u043e\u0432\u0430\u044f \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u0451\u0442\u0441\u044f."` | changed: unique edit candidate |
| `cveta2.services.upload.x_upload_dataset__mutmut_32` | `cveta2.application.use_cases.upload.x_upload_dataset__mutmut_34` | `"\u041d\u043e\u0432\u0430\u044f \u0437\u0430\u0434\u0430\u0447\u0430 \u043d\u0435 \u0441\u043e\u0437\u0434\u0430\u0451\u0442\u0441\u044f." → "\u041d\u041e\u0412\u0410\u042f \u0417\u0410\u0414\u0410\u0427\u0410 \u041d\u0415 \u0421\u041e\u0417\u0414\u0410\u0401\u0422\u0421\u042f."` | changed: unique edit candidate |
| `cveta2.services.upload.x_upload_dataset__mutmut_37` | `cveta2.application.use_cases.upload.x_upload_dataset__mutmut_39` | `"Cloud storage \u043f\u0440\u043e\u0435\u043a\u0442\u0430 \u0438\u0437\u043c\u0435\u043d\u0451\u043d; \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e \u0434\u043e \u0437\u0430\u043f\u0438\u0441\u0438." → "XXCloud storage \u043f\u0440\u043e\u0435\u043a\u0442\u0430 \u0438\u0437\u043c\u0435\u043d\u0451\u043d; \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e \u0434\u043e \u0437\u0430\u043f\u0438\u0441\u0438.XX"` | changed: unique edit candidate |
| `cveta2.services.convert.yolo.x_convert_to_yolo__mutmut_79` | `cveta2.application.use_cases.convert.yolo.x_convert_to_yolo__mutmut_63` | `box_df[["image_name", "split"]].itertuples(index=False, name=None) → box_df[["image_name", "split"]].itertuples(index=None, name=None)` | changed: unique edit candidate |
| `cveta2.services.convert.yolo.x_convert_to_yolo__mutmut_81` | `cveta2.application.use_cases.convert.yolo.x_convert_to_yolo__mutmut_65` | `box_df[["image_name", "split"]].itertuples(index=False, name=None) → box_df[["image_name", "split"]].itertuples(index=False, )` | changed: unique edit candidate |
| `cveta2.services.convert.coco.x_convert_to_coco__mutmut_35` | `cveta2.adapters.files.conversion.x__prepare_coco_split__mutmut_1` | `split_dir.mkdir(parents=True, exist_ok=True) → split_dir.mkdir(parents=None, exist_ok=True)` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x_convert_to_coco__mutmut_37` | `cveta2.adapters.files.conversion.x__prepare_coco_split__mutmut_3` | `split_dir.mkdir(parents=True, exist_ok=True) → split_dir.mkdir(exist_ok=True)` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x_convert_to_coco__mutmut_39` | `cveta2.adapters.files.conversion.x__prepare_coco_split__mutmut_5` | `True → False` | changed: reviewed edit mapping |
| `cveta2.services.convert.yolo.x__parse_label_file__mutmut_38` | `cveta2.domain.conversion.x__parse_label_text__mutmut_36` | `3 → 4` | changed: reviewed edit mapping |
| `cveta2.services.convert.yolo.x__parse_label_file__mutmut_53` | `cveta2.domain.conversion.x__parse_label_text__mutmut_51` | `valid = False → valid = None` | changed: reviewed edit mapping |
| `cveta2.services.convert.yolo.x__write_box_labels__mutmut_37` | `cveta2.domain.conversion.x_yolo_label_text__mutmut_13` | `_require_positive_dimensions(img_w, img_h, name_s) → _require_positive_dimensions(img_w, img_h, None)` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x__coco_owned_paths__mutmut_28` | `cveta2.adapters.files.conversion.x__coco_owned_paths__mutmut_28` | `ctx.df[["image_name", "split"]].itertuples(     index=False, name=None ) → ctx.df[["image_name", "split"]].itertuples(     index=None, name=None )` | verified static identity |
| `cveta2.services.convert.coco.x__coco_owned_paths__mutmut_30` | `cveta2.adapters.files.conversion.x__coco_owned_paths__mutmut_30` | `ctx.df[["image_name", "split"]].itertuples(     index=False, name=None ) → ctx.df[["image_name", "split"]].itertuples(     index=False, )` | verified static identity |
| `cveta2.services.convert.coco.x__prune_coco_output__mutmut_2` | `cveta2.adapters.files.conversion.x__prune_coco_output__mutmut_2` | `ctx.df[["image_name", "split"]].itertuples(     index=False, name=None ) → ctx.df[["image_name", "split"]].itertuples(     index=None, name=None )` | verified static identity |
| `cveta2.services.convert.coco.x__prune_coco_output__mutmut_4` | `cveta2.adapters.files.conversion.x__prune_coco_output__mutmut_4` | `ctx.df[["image_name", "split"]].itertuples(     index=False, name=None ) → ctx.df[["image_name", "split"]].itertuples(     index=False, )` | verified static identity |
| `cveta2.services.convert.coco.x__owned_split_files__mutmut_26` | `cveta2.adapters.files.conversion.x__owned_split_files__mutmut_26` | `"." → "XX.XX"` | verified static identity |
| `cveta2.services.convert.common.x__link_or_copy__mutmut_53` | `cveta2.adapters.files.materialization.x__link_or_copy__mutmut_53` | `Cveta2Error(f"\u041d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u044b\u0439 link-mode: {mode!r}") → Cveta2Error(None)` | verified static identity |
| `cveta2.services.convert.common.x__validate_export_rows__mutmut_43` | `cveta2.domain.conversion.x__validate_export_rows__mutmut_43` | `"." → "XX.XX"` | verified static identity |
| `cveta2.services.convert.common.x__validate_export_rows__mutmut_47` | `cveta2.domain.conversion.x__validate_export_rows__mutmut_47` | `"\x00" → "XX\x00XX"` | verified static identity |
| `cveta2.services.output.x_read_dataset_csv__mutmut_15` | `cveta2.adapters.files.dataset.x_read_dataset_csv__mutmut_15` | `stream.read(65536) → stream.read(None)` | verified static identity |
| `cveta2.services.output.x_read_dataset_csv__mutmut_16` | `cveta2.adapters.files.dataset.x_read_dataset_csv__mutmut_16` | `65536 → 65537` | verified static identity |
| `cveta2.services.convert.common.x__validate_splits__mutmut_40` | `cveta2.domain.conversion.x__validate_splits__mutmut_40` | `"\u0414\u043e\u043f\u0443\u0441\u0442\u0438\u043c\u044b train, val, test." → "XX\u0414\u043e\u043f\u0443\u0441\u0442\u0438\u043c\u044b train, val, test.XX"` | verified static identity |
| `cveta2.services.convert.common.x__validate_splits__mutmut_41` | `cveta2.domain.conversion.x__validate_splits__mutmut_41` | `"\u0414\u043e\u043f\u0443\u0441\u0442\u0438\u043c\u044b train, val, test." → "\u0434\u043e\u043f\u0443\u0441\u0442\u0438\u043c\u044b train, val, test."` | verified static identity |
| `cveta2.services.convert.common.x__validate_splits__mutmut_42` | `cveta2.domain.conversion.x__validate_splits__mutmut_42` | `"\u0414\u043e\u043f\u0443\u0441\u0442\u0438\u043c\u044b train, val, test." → "\u0414\u041e\u041f\u0423\u0421\u0422\u0418\u041c\u042b TRAIN, VAL, TEST."` | verified static identity |
| `cveta2.image_downloader.xǁS3Syncerǁsync__mutmut_27` | `cveta2.adapters.s3.download.xǁS3Syncerǁsync__mutmut_27` | `_local_name_from_key(key, local_root, original=key) → _local_name_from_key(key, local_root, original=None)` | verified static identity |
| `cveta2.image_downloader.xǁS3Syncerǁsync__mutmut_41` | `cveta2.adapters.s3.download.xǁS3Syncerǁsync__mutmut_41` | `destinations[resolved] = key → destinations[resolved] = None` | verified static identity |
| `cveta2.image_downloader.xǁS3Syncerǁsync__mutmut_51` | `cveta2.adapters.s3.download.xǁS3Syncerǁsync__mutmut_51` | `Cveta2Error(     f"\u041a\u043e\u043d\u0444\u043b\u0438\u043a\u0442 \u043d\u0430\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0439 S3: {destination} \u0432\u043b\u043e\u0436\u0435\u043d \u0432 \u0434\u0440\u0443\u0433\u043e\u0439 \u0444\u0430\u0439\u043b" ) → Cveta2Error(     None )` | verified static identity |
| `cveta2.config.x_cache_dir_for_project__mutmut_47` | `cveta2.adapters.config.settings.x_cache_dir_for_project__mutmut_47` | `Cveta2Error(     f"\u041f\u0443\u0442\u044c \u043a\u044d\u0448\u0430 \u043f\u0440\u043e\u0435\u043a\u0442\u0430 {project_name!r} \u0432\u044b\u0445\u043e\u0434\u0438\u0442 \u0437\u0430 \u043a\u043e\u0440\u0435\u043d\u044c {root}" ) → Cveta2Error(     None )` | verified static identity |
| `cveta2._client_ops.base.xǁ_ClientBaseǁ__exit____mutmut_6` | `cveta2.application.client.base.xǁ_ClientBaseǁ__exit____mutmut_6` | `stack.__exit__(exc_type, exc_val, exc_tb) → stack.__exit__(exc_type, exc_val, None)` | verified static identity |
| `cveta2.commands.upload.x__select_labels__mutmut_11` | `cveta2.interfaces.commands.upload.x__select_labels__mutmut_11` | `interactive.Choice(title=label, value=label) → interactive.Choice(title=label, value=None)` | verified static identity |
| `cveta2.commands.upload.x__select_labels__mutmut_13` | `cveta2.interfaces.commands.upload.x__select_labels__mutmut_13` | `interactive.Choice(title=label, value=label) → interactive.Choice(title=label, )` | verified static identity |
| `cveta2.services.convert.common.xǁ_OnceWarnerǁ__init____mutmut_1` | `cveta2.adapters.files.materialization.xǁ_OnceWarnerǁ__init____mutmut_1` | `self._warned = False → self._warned = None` | verified static identity |
| `cveta2.services.convert.common.x__reflink_or_fallback_copy__mutmut_10` | `cveta2.adapters.files.materialization.x__reflink_or_fallback_copy__mutmut_10` | `_copy_after_reflink_failure(src, dst, exc) → _copy_after_reflink_failure(src, dst, None)` | verified static identity |
| `cveta2.services.convert.common.x__make_csv_row_base__mutmut_4` | `cveta2.domain.conversion.x__make_csv_row_base__mutmut_4` | `dict.fromkeys(CSV_COLUMNS, None) → dict.fromkeys(CSV_COLUMNS, )` | verified static identity |
| `cveta2.services.convert.yolo.x__write_dataset_yaml__mutmut_26` | `cveta2.domain.conversion.x_yolo_dataset_text__mutmut_19` | `yaml.dump(yaml_data, **_YAML_DUMP) → yaml.dump(yaml_data, )` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x__write_coco_split__mutmut_152` | `cveta2.domain.conversion.x_coco_metadata_text__mutmut_3` | `json.dumps(coco_json, **_JSON_DUMP) → json.dumps(coco_json, )` | changed: reviewed edit mapping |
| `cveta2.services.convert.yolo.x__from_yolo_predictions__mutmut_34` | `cveta2.application.use_cases.convert.yolo.x__from_yolo_predictions__mutmut_38` | `missing_images.append(label_path.stem) → missing_images.append(None)` | changed: unique edit candidate |
| `cveta2.services.convert.coco.x__write_coco_split__mutmut_10` | `cveta2.domain.conversion.x_coco_split_data__mutmut_10` | `enumerate(     sorted(split_df["image_name"].unique()), start=1 ) → enumerate(     sorted(split_df["image_name"].unique()), )` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x__write_coco_split__mutmut_14` | `cveta2.domain.conversion.x_coco_split_data__mutmut_14` | `1 → 2` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x__write_coco_split__mutmut_50` | `cveta2.domain.conversion.x_coco_split_data__mutmut_42` | `0 → 1` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x__write_coco_split__mutmut_77` | `cveta2.domain.conversion.x_coco_split_data__mutmut_69` | `1 → 2` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x__write_coco_split__mutmut_56` | `cveta2.domain.conversion.x_coco_split_data__mutmut_48` | `continue → break` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x__write_coco_split__mutmut_130` | `cveta2.domain.conversion.x_coco_split_data__mutmut_122` | `sorted(label_map.items(), key=lambda x: x[1]) → sorted(label_map.items(), key=None)` | changed: reviewed edit mapping |
| `cveta2.services.convert.coco.x__write_coco_split__mutmut_132` | `cveta2.domain.conversion.x_coco_split_data__mutmut_124` | `sorted(label_map.items(), key=lambda x: x[1]) → sorted(label_map.items(), )` | changed: reviewed edit mapping |
| `cveta2.config.x__env_flag__mutmut_6` | `cveta2.adapters.config.settings.x__env_flag__mutmut_6` | `"" → "XXXX"` | verified static identity |
| `cveta2.config.xǁSectionConfigǁ_dump__mutmut_5` | `cveta2.adapters.config.settings.xǁSectionConfigǁ_dump__mutmut_5` | `"json" → "XXjsonXX"` | verified static identity |
| `cveta2.config.xǁSectionConfigǁ_dump__mutmut_6` | `cveta2.adapters.config.settings.xǁSectionConfigǁ_dump__mutmut_6` | `"json" → "JSON"` | verified static identity |
| `cveta2.task_cache.xǁS3CacheBackendǁ__init____mutmut_6` | `cveta2.adapters.s3.task_cache.xǁS3CacheBackendǁ__init____mutmut_6` | `self._disabled = False → self._disabled = None` | verified static identity |
| `cveta2.task_cache.xǁS3CacheBackendǁget__mutmut_11` | `cveta2.adapters.s3.task_cache.xǁS3CacheBackendǁget__mutmut_11` | `self._disable(e) → self._disable(None)` | verified static identity |
| `cveta2.task_cache.xǁS3CacheBackendǁget__mutmut_12` | `cveta2.adapters.s3.task_cache.xǁS3CacheBackendǁget__mutmut_12` | `self._disable(e) → self._disable(None)` | verified static identity |
| `cveta2.task_cache.xǁS3CacheBackendǁput__mutmut_10` | `cveta2.adapters.s3.task_cache.xǁS3CacheBackendǁput__mutmut_10` | `self._disable(e) → self._disable(None)` | verified static identity |
| `cveta2.task_cache.xǁS3CacheBackendǁdelete__mutmut_11` | `cveta2.adapters.s3.task_cache.xǁS3CacheBackendǁdelete__mutmut_11` | `Cveta2Error(     f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0443\u0434\u0430\u043b\u0438\u0442\u044c S3-\u043a\u044d\u0448 \u0437\u0430\u0434\u0430\u0447\u0438 {task_id}: {e}" ) → Cveta2Error(     None )` | verified static identity |
| `cveta2.services.fetch.x__promote_completed_annotations__mutmut_36` | `cveta2.application.use_cases.fetch.x__promote_completed_annotations__mutmut_39` | `run_concurrent(     tasks,     promote,     max_workers=Workers.cvat,     catch=(),     desc="Accepting completed annotations",     unit="task", ) → run_concurrent(     tasks,     promote,     max_workers=Workers.cvat,     catch=(),     desc=None,     unit="task", )` | changed: reviewed edit mapping |
| `cveta2.task_cache.xǁTaskAnnotationCacheǁ_get_local__mutmut_6` | `cveta2.adapters.s3.task_cache.xǁTaskAnnotationCacheǁ_get_local__mutmut_6` | `_validate_envelope(raw, task, source=_SOURCE_LOCAL) → _validate_envelope(raw, task, source=None)` | verified static identity |
| `cveta2.task_cache.xǁTaskAnnotationCacheǁ_get_s3__mutmut_8` | `cveta2.adapters.s3.task_cache.xǁTaskAnnotationCacheǁ_get_s3__mutmut_8` | `_validate_envelope(raw, task, source=_SOURCE_S3) → _validate_envelope(raw, task, source=None)` | verified static identity |
| `cveta2.image_downloader.x__download_pending__mutmut_22` | `cveta2.adapters.s3.download.x__download_pending__mutmut_22` | `stats.downloaded += ok → stats.downloaded = ok` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_download_all__mutmut_2` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_download_all__mutmut_2` | `stats.failed += len(pending) → stats.failed = len(pending)` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_download_all__mutmut_37` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_download_all__mutmut_37` | `stats.failed += len(missing) → stats.failed = len(missing)` | verified static identity |
| `cveta2.image_downloader.x_parse_cloud_storage__mutmut_11` | `cveta2.adapters.cvat.storage.x_parse_cloud_storage__mutmut_11` | `"" → "XXXX"` | verified static identity |
| `cveta2.image_downloader.x__download_pending__mutmut_5` | `cveta2.adapters.s3.download.x__download_pending__mutmut_5` | `run_s3_transfers(     pending,     lambda t: _download_one_s3(s3_client, bucket, t.key, t.path),     lambda t: f"{t.name} (key={t.key})",     desc=progress.desc,     unit=progress.unit, ) → run_s3_transfers(     pending,     lambda t: _download_one_s3(s3_client, bucket, t.key, t.path),     lambda t: f"{t.name} (key={t.key})",     desc=None,     unit=progress.unit, )` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_filter_cached__mutmut_8` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_filter_cached__mutmut_8` | `run_concurrent(     entries,     lambda entry: self._dest_path(entry[1], project_cloud_storage).is_file(),     max_workers=Workers.s3,     catch=(),     desc="Checking local cache",     unit="img", ) → run_concurrent(     entries,     lambda entry: self._dest_path(entry[1], project_cloud_storage).is_file(),     max_workers=Workers.s3,     catch=(),     desc=None,     unit="img", )` | verified static identity |
| `cveta2.image_uploader.xǁS3Uploaderǁupload__mutmut_31` | `cveta2.adapters.s3.upload.xǁS3Uploaderǁupload__mutmut_31` | `run_s3_transfers(     to_upload,     lambda t: _upload_one_s3(s3, t.path, cs_info.bucket, t.key),     lambda t: f"{t.name} (key={t.key})",     desc=_UPLOAD_DESC,     unit=_UPLOAD_UNIT, ) → run_s3_transfers(     to_upload,     lambda t: _upload_one_s3(s3, t.path, cs_info.bucket, t.key),     lambda t: f"{t.name} (key={t.key})",     desc=None,     unit=_UPLOAD_UNIT, )` | verified static identity |
| `cveta2.s3_utils.x_list_s3_objects__mutmut_29` | `cveta2.adapters.s3.utils.x_list_s3_objects__mutmut_29` | `run_concurrent(     folders,     lambda folder: _list_keys_under(s3_client, bucket, prefix, folder),     max_workers=Workers.s3,     catch=(),     desc="Listing S3 prefixes",     unit="prefix", ) → run_concurrent(     folders,     lambda folder: _list_keys_under(s3_client, bucket, prefix, folder),     max_workers=Workers.s3,     catch=(),     desc=None,     unit="prefix", )` | verified static identity |
| `cveta2.services.fetch.x__fetch_and_save_tasks__mutmut_37` | `cveta2.application.use_cases.fetch.x__fetch_and_save_tasks__mutmut_32` | `run_concurrent(     ctx.tasks,     process,     max_workers=Workers.cvat,     catch=(),     desc="Processing tasks",     unit="task", ) → run_concurrent(     ctx.tasks,     process,     max_workers=Workers.cvat,     catch=(),     desc=None,     unit="task", )` | changed: reviewed edit mapping |
| `cveta2._client_ops.task_ops.xǁ_TaskOpsMixinǁset_task_jobs_status__mutmut_15` | `cveta2.application.client.task_ops.xǁ_TaskOpsMixinǁset_task_jobs_status__mutmut_15` | `run_concurrent(     jobs,     lambda job: api.update_job(job.id, stage=stage, state=state),     max_workers=Workers.cvat,     catch=(),     desc="Updating jobs",     unit="job", ) → run_concurrent(     jobs,     lambda job: api.update_job(job.id, stage=stage, state=state),     max_workers=Workers.cvat,     catch=(),     desc=None,     unit="job", )` | changed: reviewed edit mapping |
| `cveta2.image_downloader.xǁImageDownloaderǁ_probe_expected_keys__mutmut_13` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_probe_expected_keys__mutmut_13` | `run_concurrent(     keys,     lambda key: s3_object_exists(s3_client, project_cloud_storage.bucket, key),     max_workers=Workers.s3,     catch=(),     desc="Locating images on S3",     unit="img", ) → run_concurrent(     keys,     lambda key: s3_object_exists(s3_client, project_cloud_storage.bucket, key),     max_workers=Workers.s3,     catch=(),     desc=None,     unit="img", )` | verified static identity |
| `cveta2.s3_utils.x_run_s3_transfers__mutmut_17` | `cveta2.adapters.s3.utils.x_run_s3_transfers__mutmut_17` | `zip(items, outcomes, strict=True) → zip(items, outcomes, strict=None)` | verified static identity |
| `cveta2.s3_utils.x_run_s3_transfers__mutmut_20` | `cveta2.adapters.s3.utils.x_run_s3_transfers__mutmut_20` | `zip(items, outcomes, strict=True) → zip(items, outcomes, )` | verified static identity |
| `cveta2.s3_utils.x_run_s3_transfers__mutmut_21` | `cveta2.adapters.s3.utils.x_run_s3_transfers__mutmut_21` | `True → False` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_filter_cached__mutmut_25` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_filter_cached__mutmut_25` | `zip(     entries, cached_flags, strict=True ) → zip(     entries, cached_flags, strict=None )` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_filter_cached__mutmut_28` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_filter_cached__mutmut_28` | `zip(     entries, cached_flags, strict=True ) → zip(     entries, cached_flags, )` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_filter_cached__mutmut_29` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_filter_cached__mutmut_29` | `True → False` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_probe_expected_keys__mutmut_33` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_probe_expected_keys__mutmut_33` | `zip(     entries, keys, found, strict=True ) → zip(     entries, keys, found, strict=None )` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_probe_expected_keys__mutmut_37` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_probe_expected_keys__mutmut_37` | `zip(     entries, keys, found, strict=True ) → zip(     entries, keys, found, )` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_probe_expected_keys__mutmut_38` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_probe_expected_keys__mutmut_38` | `True → False` | verified static identity |
| `cveta2.image_downloader.x__canonical_frame_key__mutmut_25` | `cveta2.domain.paths.x__canonical_frame_key__mutmut_25` | `_validate_relative_key(key, original=frame_ref) → _validate_relative_key(key, original=None)` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_dest_path__mutmut_13` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_dest_path__mutmut_13` | `_local_name_from_key(full_key, local_root, original=frame_ref) → _local_name_from_key(full_key, local_root, original=None)` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_dest_path__mutmut_19` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_dest_path__mutmut_19` | `_confined_destination(self._target_dir, local_name, original=frame_ref) → _confined_destination(self._target_dir, local_name, original=None)` | verified static identity |
| `cveta2.image_downloader.xǁImageDownloaderǁ_resolve_s3_keys__mutmut_33` | `cveta2.adapters.s3.download.xǁImageDownloaderǁ_resolve_s3_keys__mutmut_33` | `name_to_key.get(canonical) → name_to_key.get(None)` | verified static identity |
| `cveta2.image_downloader.xǁS3Syncerǁsync__mutmut_21` | `cveta2.adapters.s3.download.xǁS3Syncerǁsync__mutmut_21` | `_validate_relative_key(key, original=key) → _validate_relative_key(key, original=None)` | verified static identity |
| `cveta2.image_downloader.xǁS3Syncerǁsync__mutmut_34` | `cveta2.adapters.s3.download.xǁS3Syncerǁsync__mutmut_34` | `_confined_destination(     self._target_dir, local_name, original=key ) → _confined_destination(     self._target_dir, local_name, original=None )` | verified static identity |
| `cveta2.services.convert.yolo.x__resolve_dataset_root__mutmut_2` | `cveta2.adapters.files.conversion.x__resolve_dataset_root__mutmut_2` | `"" → "XXXX"` | verified static identity |
| `cveta2.services.convert.yolo.x__split_images__mutmut_5` | `cveta2.adapters.files.conversion.x__split_images__mutmut_5` | `Cveta2Error(     f"\u041e\u0448\u0438\u0431\u043a\u0430: \u043f\u0443\u0442\u044c split \u0434\u043e\u043b\u0436\u0435\u043d \u0431\u044b\u0442\u044c \u0441\u0442\u0440\u043e\u043a\u043e\u0439 \u0438\u043b\u0438 \u0441\u043f\u0438\u0441\u043a\u043e\u043c \u0441\u0442\u0440\u043e\u043a, "     f"\u043f\u043e\u043b\u0443\u0447\u0435\u043d\u043e {entry!r}" ) → Cveta2Error(     None )` | verified static identity |
| `cveta2._client.assembly.x_build_task_issues__mutmut_4` | `cveta2.application.client.assembly.x_build_task_issues__mutmut_4` | `"records" → "RECORDS"` | verified static identity |
| `cveta2._client.assembly.x_build_upload_shapes__mutmut_11` | `cveta2.application.client.assembly.x_build_upload_shapes__mutmut_11` | `"records" → "RECORDS"` | verified static identity |
| `cveta2.fs_utils.x_ensure_shared_dir__mutmut_6` | `cveta2.adapters.files.shared.x_ensure_shared_dir__mutmut_6` | `break → return` | verified static identity |
| `cveta2._concurrency.x_run_concurrent__mutmut_26` | `cveta2.adapters.execution.concurrency.x_run_concurrent__mutmut_26` | `pool.shutdown(wait=False, cancel_futures=True) → pool.shutdown(wait=None, cancel_futures=True)` | verified static identity |
| `cveta2._concurrency.x_run_concurrent__mutmut_28` | `cveta2.adapters.execution.concurrency.x_run_concurrent__mutmut_28` | `pool.shutdown(wait=False, cancel_futures=True) → pool.shutdown(cancel_futures=True)` | verified static identity |
| `cveta2._concurrency.x_run_concurrent__mutmut_30` | `cveta2.adapters.execution.concurrency.x_run_concurrent__mutmut_30` | `False → True` | verified static identity |
| `cveta2.services.fetch.x_fetch_selected_tasks__mutmut_5` | `cveta2.application.use_cases.fetch.x_fetch_selected_tasks__mutmut_5` | `_fetch_core(client, target, options, prune_cache=False) → _fetch_core(client, target, options, prune_cache=None)` | changed: reviewed edit mapping |
| `cveta2.services.fetch.x__fetch_and_save_tasks__mutmut_52` | `cveta2.application.use_cases.fetch.x__fetch_and_save_tasks__mutmut_43` | `is not → is` | changed: reviewed edit mapping |
| `cveta2.services.fetch.x__fetch_core__mutmut_9` | `cveta2.application.use_cases.fetch.x__fetch_core__mutmut_9` | `client.prepare_fetch(     project_id,     completed_only=options.completed_only,     ignore_task_ids=options.ignore_task_ids,     silent_task_ids=options.silent_task_ids,     task_selector=options.task_selector,     project_name=project_name, ) → client.prepare_fetch(     project_id,     completed_only=options.completed_only,     ignore_task_ids=options.ignore_task_ids,     silent_task_ids=options.silent_task_ids,     task_selector=options.task_selector,     project_name=None, )` | changed: unique edit candidate |
| `cveta2.services.fetch.x__fetch_core__mutmut_15` | `cveta2.application.use_cases.fetch.x__fetch_core__mutmut_15` | `client.prepare_fetch(     project_id,     completed_only=options.completed_only,     ignore_task_ids=options.ignore_task_ids,     silent_task_ids=options.silent_task_ids,     task_selector=options.task_selector,     project_name=project_name, ) → client.prepare_fetch(     project_id,     completed_only=options.completed_only,     ignore_task_ids=options.ignore_task_ids,     silent_task_ids=options.silent_task_ids,     task_selector=options.task_selector,     )` | changed: unique edit candidate |
| `cveta2.services.whats_new.x__known_task_ids__mutmut_13` | `cveta2.adapters.files.dataset.x_read_baseline_siblings__mutmut_9` | `pd.read_csv(sibling, **CSV_READ_OPTIONS) → pd.read_csv(sibling, )` | changed: reviewed edit mapping |
| `cveta2._client.assembly.x_task_to_records__mutmut_93` | `cveta2.application.client.assembly.x_task_to_records__mutmut_93` | `"" → "XXXX"` | verified static identity |
| `cveta2._client.assembly.x_task_to_records__mutmut_99` | `cveta2.application.client.assembly.x_task_to_records__mutmut_99` | `"" → "XXXX"` | verified static identity |
| `cveta2.services.convert.yolo.x__prune_yolo_output__mutmut_3` | `cveta2.adapters.files.conversion.x__prune_yolo_output__mutmut_3` | `ctx.df[["image_name", "split"]].itertuples(     index=False, name=None ) → ctx.df[["image_name", "split"]].itertuples(     index=None, name=None )` | verified static identity |
| `cveta2.services.convert.yolo.x__prune_yolo_output__mutmut_5` | `cveta2.adapters.files.conversion.x__prune_yolo_output__mutmut_5` | `ctx.df[["image_name", "split"]].itertuples(     index=False, name=None ) → ctx.df[["image_name", "split"]].itertuples(     index=False, )` | verified static identity |
| `cveta2.api.x_whats_new__mutmut_21` | `cveta2.interfaces.api.x_whats_new__mutmut_21` | `c.list_new_completed_tasks(     project_id, baseline.cutoff, baseline.known_task_ids ) → c.list_new_completed_tasks(     project_id, None, baseline.known_task_ids )` | verified static identity |
| `cveta2.dataset_partition.x__latest_row_per_image__mutmut_6` | `cveta2.domain.partition.x__latest_row_per_image__mutmut_6` | `df.assign(_row_order=list(range(len(df)))) → df.assign(_row_order=None)` | verified static identity |
| `cveta2.dataset_partition.x__latest_row_per_image__mutmut_20` | `cveta2.domain.partition.x__latest_row_per_image__mutmut_20` | `ordered.drop_duplicates(     subset=["image_name"], keep="first" ) → ordered.drop_duplicates(     subset=["image_name"], )` | verified static identity |
| `cveta2.dataset_partition.x__latest_task_per_image__mutmut_2` | `cveta2.domain.partition.x__latest_task_per_image__mutmut_2` | `(     df[["image_name", "task_id"]]     .assign(_is_deleted=0)     .drop_duplicates(subset=["image_name", "task_id"]) ) → (     df[["image_name", "task_id"]]     .assign(_is_deleted=0)     .drop_duplicates(subset=None) )` | verified static identity |
| `cveta2.dataset_partition.x__latest_task_per_image__mutmut_3` | `cveta2.domain.partition.x__latest_task_per_image__mutmut_3` | `df[["image_name", "task_id"]]     .assign(_is_deleted=0) → df[["image_name", "task_id"]]     .assign(_is_deleted=None)` | verified static identity |
| `cveta2.dataset_partition.x__latest_task_per_image__mutmut_17` | `cveta2.domain.partition.x__latest_task_per_image__mutmut_17` | `pd.concat(     [registry[latest_from_df.columns], latest_from_df],     ignore_index=True, ) → pd.concat(     [registry[latest_from_df.columns], latest_from_df],     ignore_index=None, )` | verified static identity |
| `cveta2.dataset_partition.x__latest_task_per_image__mutmut_19` | `cveta2.domain.partition.x__latest_task_per_image__mutmut_19` | `pd.concat(     [registry[latest_from_df.columns], latest_from_df],     ignore_index=True, ) → pd.concat(     [registry[latest_from_df.columns], latest_from_df],     )` | verified static identity |
| `cveta2.dataset_partition.x__latest_task_per_image__mutmut_20` | `cveta2.domain.partition.x__latest_task_per_image__mutmut_20` | `True → False` | verified static identity |
| `cveta2.dataset_partition.x__split_completed__mutmut_14` | `cveta2.domain.partition.x__split_completed__mutmut_14` | `completed_non_deleted.merge(latest_completed, on="image_name", how="left") → completed_non_deleted.merge(latest_completed, on=None, how="left")` | verified static identity |
| `cveta2.dataset_partition.x__split_completed__mutmut_17` | `cveta2.domain.partition.x__split_completed__mutmut_17` | `completed_non_deleted.merge(latest_completed, on="image_name", how="left") → completed_non_deleted.merge(latest_completed, how="left")` | verified static identity |
| `cveta2.dataset_partition.x__split_completed__mutmut_18` | `cveta2.domain.partition.x__split_completed__mutmut_18` | `completed_non_deleted.merge(latest_completed, on="image_name", how="left") → completed_non_deleted.merge(latest_completed, on="image_name", )` | verified static identity |
| `cveta2.dataset_partition.x_partition_annotations_df__mutmut_58` | `cveta2.domain.partition.x_partition_annotations_df__mutmut_58` | `pd.concat([obsolete_deleted, obsolete_stale], ignore_index=True) → pd.concat([obsolete_deleted, obsolete_stale], ignore_index=None)` | verified static identity |
| `cveta2.dataset_partition.x_partition_annotations_df__mutmut_60` | `cveta2.domain.partition.x_partition_annotations_df__mutmut_60` | `pd.concat([obsolete_deleted, obsolete_stale], ignore_index=True) → pd.concat([obsolete_deleted, obsolete_stale], )` | verified static identity |
| `cveta2.dataset_partition.x_partition_annotations_df__mutmut_61` | `cveta2.domain.partition.x_partition_annotations_df__mutmut_61` | `True → False` | verified static identity |

### Changed-function proof notes

- Runner caption removals preserve the same call operands, catch policy and worker count after canonicalizing `run_concurrent` to the injected runner and `Workers.cvat` to the resolved worker setting. Only `desc` becomes `None`; no execution argument is ignored in the application.
- Error-text equivalents are matched to the same distinct refusal literals and mutations; unchanged task/project checks and no-write refusal tests still observe the relevant behavior.
- YOLO parser numeric/falsey equivalents moved to `_parse_label_text`; coordinate guards and the sole `if not valid` consumer remain intact.
- The positive-dimension diagnostic moved to `yolo_label_text` after export prevalidation. Payload/yaml dump options moved to `coco_metadata_text` and `yolo_dataset_text`; parsed output contracts remain the observation.
- COCO image/annotation counters, unmapped-name guard and sorted categories moved to `coco_split_data`; IDs remain unique and references track their image IDs. Matching integer mutations used the enclosing enumerate or `ann_id` statement, never value-only matching.
- Fetch cache-summary guard selection was disambiguated by the enclosing `if policy.cache is not None: stats.log_summary()` statement; the unrelated result-presence guard is excluded.
- The three `convert_to_coco` directory-parent entries map to `_prepare_coco_split` mutations 1, 3 and 5. Generated mutation 5 changes `parents=True` to `False`; mutation 6 changes `exist_ok` and is explicitly excluded. The helper also creates the output root now, so former equivalents may become killable and must be retired only with evidence.
- Baseline sibling CSV options moved to `read_baseline_siblings`, matched to the exact `pd.read_csv(sibling, **CSV_READ_OPTIONS)` argument deletion.

## Executed checks and remaining acceptance

- AST inventory: all 402 baseline declarations mapped, zero missing/ambiguous declarations.
- Pure mutmut generation: all 219 candidate names matched to live generated edits; no mutation run executed during mapping.
- TOML scope/profile validation found no missing/duplicate paths, kept full = [], and found no legacy allowlist keys. Completed fast/full results appear below.
- Public invocation-time policy regression fix: 43 focused tests passed, Ruff passed, composition client mypy passed. A new recording test observes late failure-policy and worker changes for fetch, job updates and issue creation; it asserts execution policy rather than progress-caption wording.

### Gate setup and first fast result

The first attempt stopped during stats with `ModuleNotFoundError: scripts` in the architecture negative fixtures. Approved `also_copy = ["scripts"]` supplies the checker to the generated workspace; existing documentation-copy skip behavior remains unchanged. The restart passed stats, clean tests and forced-failure detection without skipping architecture tests.

The first completed fast gate reported 31 not-killed mutants, 18 justified entries, and 13 unexplained results: 11 uncovered mutants in the extracted `composition.workflows.apply_sync_root_override` boundary and two project-name argument drops. New behavior tests exercise selected config/project lookup, storage identity preservation, and explicit-root suppression of configuration reads. Both new tests and the five client architecture tests pass (7 total); tests assert effect/selection behavior rather than progress captions.

The two project-name drops are now individually justified: composition already used the name to resolve `configured_root`, and the remaining application reader uses it solely for diagnostics. Existing root/storage choices, remote calls and transfers are unchanged. New test coverage required recreating the task-owned generated `mutants/` workspace so the stats association incorporates the new tests. The rerun uses `UV_NO_SYNC=1 ./scripts/mutation_test.sh --profile fast --max-children 4`; full follows serially. No passing gate is yet claimed.

Same installed mutmut in-memory generation counted 7596 baseline edits and 7996 canonical edits; the configured ratchet has expanded after split destinations were included. Counts describe generated scope, not killed or accepted mutants.

Exact mutation snippets encode non-ASCII diagnostic literals as Python Unicode escapes, preserving their decoded semantic values while keeping this English evidence artifact portable.

### Fast profile accepted

Final fast gate exited zero with 749 checked mutants: 728 killed and 21 individually justified survivors. It reported zero `no tests`, stale justifications, unexplained mutants or timeouts and printed `No unexplained mutants escaped.` The third newly justified survivor is the same diagnostic-only project-name forwarding in `composition.workflows.apply_sync_root_override`; exact generated diff was inspected. Documentation checks passed (189 tests) after escaping the evidence's diagnostic literals.

Before full execution the generated workspace is recreated again to associate the latest compatibility tests (live client config getters and lazy root discovery) with the final code. Fast results are recorded as their executed snapshot; full validates the newer final snapshot from scratch.

### Full profile triage and consolidated rerun

The first complete final-source full run checked all 7,996 mutants: 7,749 killed, 247 survived, zero uncovered/not-checked/skipped/timeouts. Its gate rejected 28 unexplained survivors and three stale directory-parent entries. All three directory-parent mutants were killed: `adapters.files.conversion.x__prepare_coco_split__mutmut_1`, `_3`, and `_5`. The helper now also creates the output root, and `test_empty_coco_export_creates_output_root` exercises a nested missing parent. Those old split-only equivalences are retired from the live table; their original mappings remain above as migration history. This tightens the allowlist without changing scope.

Behavior gaps were addressed with supplied-port tests: default fetch includes unfinished tasks and preserves its context default; default issue creation does not silently enable deduplication; default conversion passes automatic materialization and reuses first-image dimensions; default merge lets new rows win; a single explicit upload root survives normalization; default manifests do not claim complete intent; task-context exit preserves the project identity used for invalidation; label counting propagates unexpected exceptions unchanged and keeps reads on the caller thread. The mutable public config regression now also checks the prepared fetch context host, observing the host-refresh mutant.

Twenty focused tests passed (14 mutation-regression cases plus six client-architecture cases); the new regression module passed Ruff, formatting and mypy. Three inspected generated mutants were independently substituted in an isolated process: invalidation project-name drop, counting catch=None, and counting workers=2 were each rejected by the corresponding behavioral test. No source was patched for those probes.

Thirteen further equivalents were individually inspected, in addition to the earlier three resolved project-name forwards:

| Exact canonical mutants | Proof |
|---|---|
| `composition.client.xǁCvatClientǁ__init____mutmut_14`, `_18` | Initial host snapshot is unobserved: the public getter reads config live, and prepare_fetch refreshes host before the application consumes it. Credentials and organization are unaffected. |
| `composition.client.xǁCvatClientǁ__init____mutmut_16`, `_20` | Initial worker value is overwritten before prepare_fetch, job updates or issue creation; label counting remains explicitly sequential and does not consume it. |
| `composition.client.xǁCvatClientǁ__init____mutmut_17`, `_21` | Initial failure flag is overwritten from runtime before the prepared context consumes it. |
| `application.client.base.xǁ_ClientBaseǁ__enter____mutmut_3`, `_4`, `_5`, `_6` | Only the fixed internal missing-factory diagnostic changes. RuntimeError, entry refusal and absence of API/session effects remain unchanged. |
| `application.client.read.xǁ_ReadMixinǁcount_label_usage__mutmut_24` | Only the progress caption becomes None; caller-thread execution, error propagation, counting and skipped-task summaries remain unchanged. |
| `composition.workflows.x_build_search_dirs__mutmut_6` | Project name is dropped after cache-directory resolution; its remaining consumer is an empty-search diagnostic. |
| `application.use_cases.convert.yolo.x__write_box_labels__mutmut_38` | Image name reaches only the invalid-dimension diagnostic. Export validation requires positive integral dimensions before the writer; label content and materialization use unchanged operands. |

The live table now has 232 exact equivalent entries: 219 historical entries migrated, three retired with kill evidence, and 16 newly justified boundary/diagnostic entries. All 58 files and 402 baseline declaration mappings remain in scope. The consolidated full rerun regenerates stats from the final code/tests using `UV_NO_SYNC=1 ./scripts/mutation_test.sh --profile full --max-children 8`. Its accepted result appears below.

### Final full acceptance

The consolidated full command exited **0** and printed **`No unexplained mutants escaped.`** All **7,996** generated mutants were checked: **7,764 killed**, **232 individually justified survivors**, **0 uncovered**, **0 not checked**, **0 skipped**, **0 timeouts**, **0 stale equivalents**, and **0 unexplained survivors**. Whole-scope score is **97.1%**; the gate criterion remains zero unexplained results rather than a score threshold. The run used fresh stats after the final source/tests and completed at 35.33 mutations/second.

The final scope is **58 canonical files**, preserving **all 402 baseline declarations** and increasing same-tool generated edits from **7,596 to 7,996**. No suppression patterns, test assertions from the baseline, source paths, cached-test invalidation rules, or profile gate semantics were weakened. The new mutation regression module contains 14 behavior cases; the focused combination with client architecture checks passed 20 cases, and independent review accepted the final test/equivalence delta without findings. Documentation checks passed 193 cases after the evidence updates preceding this final acceptance section.

The three retired directory-parent equivalents remain killed; all 232 current equivalent keys exactly match live survivors. The earlier accepted fast snapshot checked 749 mutants (728 killed, 21 individually justified); the parent owns the final pre-commit fast rerun and remaining hooks after this handoff. No mutation process remains running.
