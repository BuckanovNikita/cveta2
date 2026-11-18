#!/usr/bin/env bash
# Install worktree-aware dispatchers, preserving a previous foreign installation.
set -eu
cd "$(git rev-parse --show-toplevel)"
hook_dir=$(git rev-parse --path-format=absolute --git-path hooks)
mkdir -p "$hook_dir"
staged=$(mktemp -d "$hook_dir/cveta2-install.XXXXXX")
trap 'rm -rf -- "$staged"' EXIT
backup=
for hook_type in pre-commit commit-msg; do
    cat > "$staged/$hook_type" <<'HOOK'
#!/usr/bin/env bash
# cveta2 worktree dispatcher: no installation-worktree paths.
set -eu
hook_dir=$(cd "$(dirname "$0")" && pwd)
hook_type=$(basename "$0")
cd "$(git rev-parse --show-toplevel)"
if [ ! -f Taskfile.yml ] || [ ! -f scripts/git-hook.sh ]; then
    echo 'Task workflow files are missing: restore them, or commit from a checkout that has them.' >&2
    exit 1
fi
exec bash scripts/git-hook.sh "$hook_type" "$hook_dir" "$@"
HOOK
    chmod +x "$staged/$hook_type"
    # A hook identical to the one being installed is this script's own output,
    # so nothing is lost by replacing it. Anything else, including a link, a
    # hand-edited dispatcher or no hook at all, is saved for rollback first.
    installed="$hook_dir/$hook_type"
    if [ ! -L "$installed" ] && [ -f "$installed" ] && cmp -s -- "$staged/$hook_type" "$installed"; then
        :
    else
        if [ -z "$backup" ]; then
            backup=$(mktemp -d "$hook_dir/cveta2-backup.XXXXXX")
            printf 'Previous hooks are saved in: %s\n' "$backup"
        fi
        if [ -e "$installed" ] || [ -L "$installed" ]; then
            cp -P -p -- "$installed" "$backup/$hook_type"
        else
            touch "$backup/$hook_type.absent"
        fi
    fi
    mv -- "$staged/$hook_type" "$hook_dir/$hook_type"
done
if [ -n "$backup" ]; then
    printf 'Installed worktree-aware hooks. Previous hooks: %s\n' "$backup"
    printf 'Rollback: restore each saved hook; remove hooks marked .absent.\n'
else
    printf 'Worktree-aware hooks were already current. No hook was replaced, so no backup was made.\n'
fi
