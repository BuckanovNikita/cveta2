# Triage roles

The skills speak of five triage state roles and two category roles. In this repo a state role is a Linear **status**; `ready-for-human` is the one role that also carries a label.

| Role in mattpocock/skills | In Linear                                  | Meaning                                  |
| ------------------------- | ------------------------------------------ | ---------------------------------------- |
| `needs-triage`            | status `Triage`, no `ready-for-human` label | Maintainer needs to evaluate this issue  |
| `needs-info`              | status `Backlog`                           | Waiting on reporter for more information |
| `ready-for-agent`         | status `Todo`                              | Fully specified, ready for an AFK agent  |
| `ready-for-human`         | status `Triage` + label `ready-for-human`  | Requires human implementation            |
| `wontfix`                 | status `Canceled`                          | Will not be actioned                     |

| Category role | Linear label |
| ------------- | ------------ |
| `bug`         | `Bug`        |
| `enhancement` | `Feature`    |

When a skill says to apply a triage label, set the status (and the label, for `ready-for-human`) from this table. Moving an issue out of `ready-for-human` removes the label.

"Unlabeled" and `needs-triage` are the same queue: publish an issue that has no role yet in `Triage`.

`In Progress`, `In Review`, `Done` and `Duplicate` are past triage and carry no role. Triage queries skip a wayfinder map and its children.
