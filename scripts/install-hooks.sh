#!/usr/bin/env bash
# Install worktree-aware dispatchers, preserving a previous foreign installation.
set -eu
cd "$(git rev-parse --show-toplevel)"
hook_dir=$(git rev-parse --path-format=absolute --git-path hooks)
mkdir -p "$hook_dir"
marker='# cveta2 worktree dispatcher: no installation-worktree paths.'
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
root=$(git rev-parse --show-toplevel)
cd "$root"
export UV_PROJECT_ENVIRONMENT="$root/.venv"
# A deleted working-tree file must not masquerade as a legacy checkout.
if [ -f Taskfile.yml ] || git cat-file -e HEAD:Taskfile.yml 2>/dev/null ||
    git cat-file -e :Taskfile.yml 2>/dev/null; then
    if [ ! -f Taskfile.yml ] || [ ! -f scripts/git-hook.sh ]; then
        echo 'Task workflow files are missing; restore them before committing.' >&2
        exit 1
    fi
    exec bash scripts/git-hook.sh "$hook_type" "$hook_dir" "$@"
fi
# Older worktrees keep their own prek configuration and environment.
exec uv run --locked prek hook-impl --hook-dir "$hook_dir" --script-version 4 --hook-type "$hook_type" -- "$@"
HOOK
    chmod +x "$staged/$hook_type"
    # An installed dispatcher is this script's own output, recoverable from the
    # repository, so only a foreign or absent hook is saved for rollback.
    if [ -e "$hook_dir/$hook_type" ] && grep -qxF -- "$marker" "$hook_dir/$hook_type"; then
        :
    else
        if [ -z "$backup" ]; then
            backup=$(mktemp -d "$hook_dir/cveta2-backup.XXXXXX")
        fi
        if [ -e "$hook_dir/$hook_type" ]; then
            cp -p -- "$hook_dir/$hook_type" "$backup/$hook_type"
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
    printf 'Refreshed worktree-aware hooks. No foreign hook was replaced, so no backup was made.\n'
fi
