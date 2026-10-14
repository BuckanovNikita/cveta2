# Design decisions

- Use installed import-linter 2.13 and existing toolchain. Baseline has four passing contracts, but synthetic forbidden dependencies between foundation and infrastructure also pass; current contracts do not cover the architecture completely.
- Adopt full reorganization, as selected by the user, with compatibility at documented APIs and public top-level modules only. Remove unsupported implementation paths after migrating callers.
- Separate incoming interfaces from outgoing adapters to avoid a composition cycle.
- SDK conversion and exception translation stay in adapters; deterministic transformations of neutral CVAT records stay in application client code.
- Keep Pydantic, pandas and Loguru in inner code. Prohibit filesystem/environment/configuration/network/concurrency effects while allowing lexical paths.
- Use explicit dependency injection rather than global service lookup. Preserve concurrency/retry context propagation and exception behavior.
- Preserve public identity by reexporting canonical types. Root exports become lazy to support isolated inner imports.
- Map moved mutation functions to canonical owners and revalidate equivalent identities.
- No runtime dependency, format migration or behavioral redesign is required. Design choices are resolved.
