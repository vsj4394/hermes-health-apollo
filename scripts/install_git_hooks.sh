#!/bin/sh
set -eu

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

source_hook=$repo_root/.githooks/pre-push
target_hook=$hooks_dir/pre-push

if [ -e "$target_hook" ] && ! cmp -s "$source_hook" "$target_hook"; then
  echo "Refusing to overwrite existing pre-push hook: $target_hook" >&2
  exit 1
fi

cp "$source_hook" "$target_hook"
chmod +x "$target_hook"

echo "Installed pre-push hook: $target_hook"
