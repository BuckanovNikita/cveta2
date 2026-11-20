# Issue tracker: Linear

Issues and specs for this repo live in Linear: team `SIP`, project `cveta2`. Use the Linear MCP tools.

Team `SIP` holds one project per repository and one number space across them: pass `team: SIP` and `project: cveta2` on every create and list.

## Conventions

- **Create an issue**: `save_issue` with `title`, `description` and a `state` from [triage-labels.md](triage-labels.md).
- **Read an issue**: `get_issue` by identifier (`SIP-123`), then `list_comments`; `get_issue` returns no discussion.
- **List issues**: `list_issues` with a `state` filter; follow `cursor` while `hasNextPage` is true.
- **Make an issue a sub-issue of a parent**: `parentId` on `save_issue`.
- **Blocking**: Linear's native relations, `blockedBy` / `blocks` on `save_issue` (append-only; `removeBlockedBy` deletes an edge). A ticket is unblocked when every blocker is Done, Canceled or Duplicate.
- **Comment on an issue**: `save_comment`.
- **Apply a triage role**: set `state`, and the label where the role has one, per [triage-labels.md](triage-labels.md).
- **Close**: comment the explanation, then set `state` to `Done` (finished) or `Canceled` (will not be actioned).
- **Merge a duplicate**: `duplicateOf` on the absorbed issue; Linear moves it to Duplicate. The connector has no delete.

## Pull requests

Code reaches `main` through GitHub PRs. End the PR title with the issue identifier, `... (SIP-123)`: Linear links the PR and moves the issue to Done when it merges.

## When a skill says "publish to the issue tracker"

Create a Linear issue in project `cveta2`.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Wayfinding operations

Used by `/wayfinder`. The **map** is one issue with **child** issues as tickets. Title and body carry what the skill calls `wayfinder:` labels.

- **Map**: an issue titled `Map: <effort>`, state `In Progress`, holding the Notes / Decisions-so-far / Fog body.
- **Child ticket**: a sub-issue of the map, state `Todo`. Its first body line is the type: `Type: research`, `prototype`, `grilling` or `task`.
- **Blocking**: see **Blocking** under Conventions.
- **Frontier query**: `list_issues` with `parentId: <map>` and `state: Todo`; drop any with an assignee or an open blocker; lowest identifier wins.
- **Claim**: `assignee: me` and `state: In Progress`, the session's first write.
- **Resolve**: `save_comment` with the answer, set `state: Done`, then append a context pointer (gist + link) to the map's Decisions-so-far.
