#!/usr/bin/env bash
# Fetch V. S. Apte's Sanskrit-Hindi dictionary XML from the Samsaadhanii repo
# using a sparse, shallow checkout (only MT/data/hi/Apte_dict, ~24 MB).
#
# The commit is pinned so the build is reproducible and the expected counts in
# pipeline/expected.json stay valid. Override with SCL_COMMIT=<sha> to update.
set -euo pipefail

SCL_REPO="${SCL_REPO:-https://github.com/samsaadhanii/scl}"
SCL_COMMIT="${SCL_COMMIT:-1ec51dc4cbfecf271e4f3cb0bba41f25b5921572}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/data/raw/scl"

if [ ! -d "$DEST/.git" ]; then
  mkdir -p "$DEST"
  git -C "$DEST" init -q
  git -C "$DEST" remote add origin "$SCL_REPO"
  git -C "$DEST" sparse-checkout set --no-cone /MT/data/hi/Apte_dict/ /COPYING /README.md
fi
git -C "$DEST" fetch -q --depth 1 --filter=blob:none origin "$SCL_COMMIT"
git -C "$DEST" checkout -q --detach FETCH_HEAD
echo "$SCL_COMMIT" > "$DEST/.source-commit"
echo "Fetched $(ls "$DEST/MT/data/hi/Apte_dict"/*.xml | wc -l) XML files at $SCL_COMMIT into $DEST"
