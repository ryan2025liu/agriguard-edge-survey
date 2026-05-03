#!/usr/bin/env bash
# Example sync from media-ai monorepo -> standalone Edge Survey distribution repo.
# Copy this script into your standalone repo (e.g. ./scripts/sync_from_upstream.sh).
#
# Requirements: rsync, git
#
# Usage:
#   MONO=/absolute/path/to/media-ai STAND=/absolute/path/to/agri_guard_edge_survey_dist ./sync_from_monorepo.example.sh

set -euo pipefail

: "${MONO:?Set MONO to absolute path of media-ai monorepo checkout}"
: "${STAND:?Set STAND to absolute path of standalone distribution repo}"

for d in "$MONO/agri_guard_core" "$MONO/agri_guard_edge_survey"; do
  if [[ ! -d "$d" ]]; then
    echo "missing: $d" >&2
    exit 1
  fi
done

mkdir -p "$STAND/agri_guard_core" "$STAND/agri_guard_edge_survey"

rsync -a --delete \
  --exclude ".git/" --exclude ".venv/" --exclude "*.egg-info/" \
  --exclude "__pycache__/" --exclude "build/" --exclude "dist/" \
  "$MONO/agri_guard_core/" "$STAND/agri_guard_core/"
rsync -a --delete \
  --exclude ".git/" --exclude ".venv/" --exclude "*.egg-info/" --exclude ".env" \
  --exclude "__pycache__/" --exclude "build/" --exclude "dist/" \
  "$MONO/agri_guard_edge_survey/" "$STAND/agri_guard_edge_survey/"

echo "---"
REV="$(cd "$MONO" && git rev-parse HEAD)"
printf '%s %s UTC\n' "$REV" "$(date -u +%Y-%m-%dT%H:%MZ)" > "$STAND/UPSTREAM_REVISION.txt"
echo "Wrote $STAND/UPSTREAM_REVISION.txt : $(cat "$STAND/UPSTREAM_REVISION.txt")"

echo "Done. Review with: cd \"$STAND\" && git status"
