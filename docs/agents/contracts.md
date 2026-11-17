# Product contract authority

[Linear contract index](https://linear.app/sip-ds-team/document/cveta2-product-contract-index-migration-draft-0f712c7810f8) owns current product requirements after human merge and acceptance of [SIP-66](https://linear.app/sip-ds-team/issue/SIP-66). Documents remain migration drafts until that cutover; source contracts at `63cd25522f29c566a25840a944f6486e7d3451ed` govern beforehand. This branch implements the approved transition, not an early authority switch.

| Source | Complete topic transfer |
| --- | --- |
| `specs/baseline.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-draft-specsbaselinemd-2331f5c7c87b) |
| `docs/dataset-contract.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-draft-docsdataset-contractmd-ffd41fecfde2) |
| `docs/configuration.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-draft-docsconfigurationmd-67789ec2f0b6) |
| `docs/cli.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-draft-docsclimd-ccd8081c0258) |
| `docs/python-api.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-draft-docspython-apimd-a72b44e6c704) |
| `docs/images-and-cache.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-draft-docsimages-and-cachemd-533d3ab25cef) |
| `GLOSSARY.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-draft-glossarymd-a4613e4e8529) |

Every source section, identifier, condition, exception and example is included. Original language is retained to avoid translation changes; relative links point to migrated topics or immutable Git sources. Source files are recoverable at the commit above. Examples are explanatory; requirements retain their original force. Historical workflow directives embedded in the baseline do not reactivate Spec Kit.

Engineering and architecture policy remains in this directory. Russian usage guides remain maintained and must agree with Linear. The dataset contract and Spec Kit tree become historical references; the glossary remains maintained vocabulary synchronized with its Linear topic.

## Changes and outages

Propose changes in Linear issues. Promote them into the current contract only after human merge and acceptance, recording the merged SHA. During a Linear outage, record the identity of a previously verified snapshot, continue investigation and isolated implementation, and defer requirement decisions, synchronization and merge readiness.

## Cutover checklist

The migration issue stays open until its PR is human-merged and acceptance is satisfied. Verify the merged SHA and independent contract-transfer review, then update the index and all topic draft notices/titles, record activation and reconcile issue status. Until then keep drafts visible. A future session must perform this step if the merge happens after this session ends; do not imply an automatic watcher exists.
