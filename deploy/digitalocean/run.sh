#!/usr/bin/env bash
# Refresh seattlefallbeers.com: scrape the tap lists and publish the site into
# the Apache document root. Run hourly from cron as the site's user; see
# README.md. Overridable via environment: REPO_DIR, WEB_ROOT, LOCK_FILE,
# HEALTHCHECK_URL (optional healthchecks.io ping URL).
set -uo pipefail

REPO_DIR="${REPO_DIR:-$HOME/around-the-grounds}"
WEB_ROOT="${WEB_ROOT:-/var/www/seattlefallbeers.com}"
LOCK_FILE="${LOCK_FILE:-/tmp/seattle-fall-beers.lock}"

# Published files must be world-readable for Apache.
umask 022
# uv's standalone installer puts it here.
export PATH="$HOME/.local/bin:$PATH"

cd "$REPO_DIR" || { echo "$(date "+%Y-%m-%dT%H:%M:%S%z") cannot cd to $REPO_DIR"; exit 1; }

echo "$(date "+%Y-%m-%dT%H:%M:%S%z") starting refresh"
# -n: if the previous run is still going, skip this one rather than pile up
# (exit 75). --no-sync: never change the environment from cron; run
# `uv sync` after pulls.
flock -n -E 75 "$LOCK_FILE" \
    uv run --no-sync around-the-grounds \
        --site seattle-fall-beers --output-dir "$WEB_ROOT"
status=$?
# Exit codes: 0 clean, 2 some venues failed (site still published),
# 1 nothing published (every venue failed or a write error; last copy kept),
# 75 skipped because the previous run was still going.
echo "$(date "+%Y-%m-%dT%H:%M:%S%z") finished with exit code $status"

if [ -n "${HEALTHCHECK_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL/$status" > /dev/null || true
fi
exit "$status"
