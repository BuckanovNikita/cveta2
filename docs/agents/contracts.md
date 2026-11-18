# Product contract authority

[Linear contract index](https://linear.app/sip-ds-team/document/cveta2-product-contract-index-0f712c7810f8) owns current product requirements. The cutover completed on 2026-11-17: the migration PR was human-merged at `783acf6eac3aff98c0d70ced407484c88225ba97`, and [SIP-66](https://linear.app/sip-ds-team/issue/SIP-66) records its acceptance and the activation of the contract documents. The source contracts at `63cd25522f29c566a25840a944f6486e7d3451ed` governed before the cutover and remain the frozen comparison baseline.

| Source | Complete topic transfer |
| --- | --- |
| `specs/baseline.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-specsbaselinemd-2331f5c7c87b) |
| `docs/dataset-contract.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-docsdataset-contractmd-ffd41fecfde2) |
| `docs/configuration.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-docsconfigurationmd-67789ec2f0b6) |
| `docs/cli.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-docsclimd-ccd8081c0258) |
| `docs/python-api.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-docspython-apimd-a72b44e6c704) |
| `docs/images-and-cache.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-docsimages-and-cachemd-533d3ab25cef) |
| `GLOSSARY.md` | [Linear document](https://linear.app/sip-ds-team/document/contract-glossarymd-a4613e4e8529) |

Every source section, identifier, condition, exception and example is included. Original language is retained to avoid translation changes; relative links point to migrated topics or immutable Git sources. Source files are recoverable at the commit above. Examples are explanatory; requirements retain their original force. Historical workflow directives embedded in the baseline do not reactivate Spec Kit.

Engineering and architecture policy remains in this directory. Russian usage guides remain maintained and must agree with Linear. The dataset contract and Spec Kit tree are historical references; the glossary remains maintained vocabulary synchronized with its Linear topic.

## Changes and outages

Propose changes in Linear issues. Promote them into the current contract only after human merge and acceptance, recording the merged SHA. No automation performs that post-merge contract update; the session that follows the merge does it. During a Linear outage, record the identity of a previously verified snapshot, continue investigation and isolated implementation, and defer requirement decisions, synchronization and merge readiness.
