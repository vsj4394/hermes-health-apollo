#!/bin/sh
set -eu

managed_marker="Managed by Hermes Health Apollo git hook installer."

is_managed_hook() {
  hook_path=$1
  grep -q "$managed_marker" "$hook_path" \
    || grep -q "scripts/secret_scan.py" "$hook_path" \
    || grep -q "refs/heads/\\*|refs/tags/\\*" "$hook_path"
}

repo_root=$(git rev-parse --show-toplevel)
hooks_path=$(git config --get core.hooksPath || true)

if [ -n "$hooks_path" ]; then
  case "$hooks_path" in
    /*) hooks_dir=$hooks_path ;;
    *) hooks_dir=$repo_root/$hooks_path ;;
  esac
else
  hooks_dir=$(git rev-parse --git-path hooks)
  case "$hooks_dir" in
    /*) ;;
    *) hooks_dir=$repo_root/$hooks_dir ;;
  esac
fi

mkdir -p "$hooks_dir"

for hook_name in pre-commit pre-push; do
  source_hook=$repo_root/.githooks/$hook_name
  target_hook=$hooks_dir/$hook_name

  if [ -e "$target_hook" ] && ! cmp -s "$source_hook" "$target_hook"; then
    if ! is_managed_hook "$target_hook"; then
      echo "Refusing to overwrite existing $hook_name hook: $target_hook" >&2
      exit 1
    fi
  fi

  cp "$source_hook" "$target_hook"
  chmod +x "$target_hook"

  echo "Installed $hook_name hook: $target_hook"
done
