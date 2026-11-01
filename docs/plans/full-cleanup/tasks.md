# Cleanup maintenance tasks

- [x] T001 Inspect current code/contracts/diffs and measure baseline; preserve user work.
- [x] T002 Validate architecture planning and scope before implementation.
- [x] T003 [P] Consolidate lexical CSV tests in tests/test_output.py and dimension coverage in tests/test_review_dataset.py; batch pure per-document invariants in tests/test_docs.py preserving all paths and diagnostic details.
- [x] T004 [P] Shorten owned HTTP fixture polling in tests/test_cvat_diagnostics.py, tests/bundle/test_remote.py and tests/integration/test_clearml.py.
- [x] T005 Reorder prerequisite hooks with fail-fast semantics in .pre-commit-config.yaml; exercise actual disposable-Git failure/rewrite/success paths.
- [x] T006 Correct help/config/ignore contradictions in interfaces, docs and shared baseline; inspect portable guidance.
- [x] T007 Integrate separately specified fixes; run static, architecture, docs, full coverage/duration, mutation and live gates.
- [x] T008 Obtain fresh independent review, reconcile complete diff and validate architecture acceptance.
- [x] T009 Complete authorized commits, main merge, semantic-release evaluation and commit/tag delivery; retain dated evidence.

T003-T006 depend on T002; T007 depends on T003-T006 and both bug tracks.
T008 follows parent verification; T009 follows acceptance. This maintenance
ledger references bug tracks without duplicating their implementation status.
