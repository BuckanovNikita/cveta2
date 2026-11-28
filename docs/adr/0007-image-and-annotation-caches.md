# Use separate identities for annotation reuse and image transfers

## Reusing annotations

Validate a cached task against its task and job metadata. Read jobs live because a change of stage or state can change the partition. The cache can be local or backed by S3. Refresh repopulates it, and off bypasses reads and writes. [Public cache modes](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_api_fetch.py) · [Cache invalidation cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_task_cache.py)

## Locating images

Fetch downloads selected frames to the configured cache or an explicit directory unless images are disabled. `s3-sync` lists a whole sync root. The root selects source objects and the ignored prefix determines local paths. Resolve destination collisions before transfers begin. Later syncs can reuse files already present. [Sync layout through the API](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_api_projects.py) · [Collision and partial-transfer cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_review_storage.py)

## Interpreting failures

Per-file failures can appear in `DownloadStats.failed`. Bucket listing can raise the original SDK exception in Python. CLI dispatch translates supported S3 failures and reports incomplete transfers. The Python guide groups S3 errors under `Cveta2Error`. [Guide at the baseline](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/commands/s3-sync.md#L132) · [Error boundary](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/cveta2/adapters/s3/errors.py) · [SIP-343](https://linear.app/sip-ds-team/issue/SIP-343/clarify-which-s3-failures-escape-the-public-python-api)
