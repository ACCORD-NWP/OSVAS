#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HARPSCRIPTS_DIR="$REPO_ROOT/HARPSCRIPTS"

cd "$HARPSCRIPTS_DIR"

for patch in "$REPO_ROOT/patches/harpscripts"/*.patch; do
  echo "Applying $(basename "$patch")"
  git apply "$patch"
done

echo "All HARPSCRIPTS patches applied successfully."
