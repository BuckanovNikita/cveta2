#!/usr/bin/env bash
# Session-start status for agent sessions (Claude and Codex SessionStart hooks).
# Shows parallel work that a new session should know about before editing:
# the branch against main, uncommitted changes, other worktrees and unmerged
# branches and an active live-test run tag. At most about
# ten lines; never fails the session.
set -u
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0

branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || echo "(detached)")
if read -r behind ahead < <(git rev-list --left-right --count main...HEAD 2>/dev/null); then
    echo "cveta2 session status: branch $branch, $ahead ahead of main, $behind behind"
else
    echo "cveta2 session status: branch $branch"
fi

changed=$(git status --porcelain 2>/dev/null | wc -l)
staged=$(git diff --cached --name-only 2>/dev/null | wc -l)
if [ "$changed" -gt 0 ]; then
    echo "  uncommitted: $changed paths ($staged staged) - may belong to another session; do not stage them"
fi

worktrees=$(git worktree list 2>/dev/null | tail -n +2)
if [ -n "$worktrees" ]; then
    echo "  other worktrees:"
    echo "$worktrees" | head -3 | sed 's/^/    /'
fi

unmerged=$(git branch --no-merged main --format='%(refname:short)' 2>/dev/null | grep -vx "$branch" | head -4 | paste -sd ' ' -)
if [ -n "$unmerged" ]; then
    echo "  unmerged branches: $unmerged"
fi

if [ -s tests/integration/.session ]; then
    echo "  kept live session: $(sed -n 's/.*"namespace": *"\([^"]*\)".*/\1/p' tests/integration/.session) (lifecycle stop when it is yours and done)"
fi
exit 0
