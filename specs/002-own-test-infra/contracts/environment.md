# Contract: variables a session exports

Every live test and helper reads these names; their values describe the current
session. Values are never printed except by `lifecycle env` into a pipe.

| Name | Value |
|---|---|
| `INTEGRATION_RUN_TAG` | the session namespace |
| `CVAT_INTEGRATION_HOST` | `http://127.0.0.1:<port>` of the CVAT backend port-forward |
| `CVAT_INTEGRATION_USER` / `CVAT_INTEGRATION_PASSWORD` | the session's regular CVAT user |
| `CVAT_INTEGRATION_ORG` | the organization that user owns |
| `CVAT_INTEGRATION_PROJECT` | `<namespace> coco8-dev` |
| `MINIO_ENDPOINT` | `http://127.0.0.1:<port>` of the MinIO port-forward |
| `MINIO_ENDPOINT_FOR_CVAT` | the in-cluster MinIO Service URL |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_REGION` | the session MinIO credentials and region |
| `MINIO_BUCKET` | the session namespace |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` / `AWS_ENDPOINT_URL` | the same MinIO, for boto's default chain |
| `CLEARML_API_HOST` / `CLEARML_FILES_HOST` | `http://127.0.0.1:<port>` of the API and file-server port-forwards |
| `CLEARML_WEB_HOST` | the API URL (no web UI is deployed) |
| `CLEARML_API_ACCESS_KEY` / `CLEARML_API_SECRET_KEY` | the session's ClearML key pair |

The names exported by the session are listed in `CVETA2_LIVE_EXPORTED`, so
`tests/conftest.py` keeps hiding them from unit tests.

Not exported any more: `INTEGRATION_SKILL_DIR`, `INTEGRATION_PROJECT`, the
helpers' `CVAT_URL/USERNAME/PASSWORD/ORG/TOKEN`, `S3_*`, `MINIO_CONSOLE` and the
CA-bundle variables `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `AWS_CA_BUNDLE`.
