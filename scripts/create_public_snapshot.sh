#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: scripts/create_public_snapshot.sh /path/to/public-snapshot" >&2
  exit 2
fi

destination=$1

if [ -e "$destination" ]; then
  echo "refusing to overwrite existing path: $destination" >&2
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "working tree has uncommitted changes; commit or stash before snapshotting" >&2
  exit 1
fi

python3 scripts/secret_scan.py

mkdir -p "$destination"
git archive --format=tar HEAD | tar -xf - -C "$destination"

(
  cd "$destination"
  git init -b main
  git add .
  python3 scripts/secret_scan.py
)

cat <<EOF
Public snapshot staged at:
  $destination

Next steps:
  cd "$destination"
  git commit -m "Release Hermes health data plugin"
  git remote add origin <PUBLIC_REPO_URL>
  git push -u origin main
EOF
