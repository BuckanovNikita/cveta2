# Live Infrastructure Requirements Quality Checklist

Created and reviewed 2026-11-10 against the approved k8s-infra plan, spec.md and
plan.md. These marks review requirement quality, not implementation completion.

- [x] CHK001 Namespace naming excludes every protected name and is unique per session (FR-002).
- [x] CHK002 Quota and limit range precede any workload, and every container declares resources (FR-003).
- [x] CHK003 Storage rules name `emptyDir` first and an explicit `hostpath` only where pods share data; `local-path` is excluded (FR-004).
- [x] CHK004 Host access is loopback port-forward only, with no Ingress, NodePort or host port (FR-005).
- [x] CHK005 The component set is defined by measurement and includes the chunks worker (FR-006, research R2).
- [x] CHK006 No dedicated ClearML/FiftyOne use and no GPU request (FR-007, FR-008).
- [x] CHK007 Credential generation, storage and non-printing are specified (FR-009, FR-010).
- [x] CHK008 Every environment name a test reads is listed, including the AWS names found by measurement (FR-011, contracts/environment.md).
- [x] CHK009 The retired names and helpers are enumerated with a verifiable check (FR-013, SC-005).
- [x] CHK010 Preflight outcomes keep 0/3/1 with a new, explicit meaning of UNAVAILABLE (FR-014).
- [x] CHK011 Setup and teardown are bounded, cover interruption, and report incomplete cleanup by name (FR-015, FR-016).
- [x] CHK012 Vanished namespaces and concurrent sessions are covered (FR-018, FR-019).
- [x] CHK013 The constitution conflict is identified and gated before implementation (plan, T001).
- [x] CHK014 Each removed current behavior has a recorded disposition (plan, behavior mapping).
