#!/usr/bin/env bash
# Refresh one Freshies site: scrape the tap lists and publish the site into
# its Apache document root. Run hourly from cron as the sites' user; see
# README.md.
#
#   run.sh <site key>        seattle-freshies, portland-freshies, or
#                            yakima-freshies (add new sites to SITES below)
#
# The document root defaults to /var/www/<host of the site's public_url>.
# Overridable via environment: REPO_DIR, WEB_ROOT, LOCK_FILE,
# QUEUE_LOCK, QUEUE_WAIT, HEALTHCHECK_URL (optional healthchecks.io ping URL).
set -uo pipefail

SITES="seattle-freshies portland-freshies yakima-freshies"
SITE_KEY="${1:-}"
REPO_DIR="${REPO_DIR:-$HOME/around-the-grounds}"

now() { date "+%Y-%m-%dT%H:%M:%S%z"; }

known=""
for site in $SITES; do
    [ "$SITE_KEY" = "$site" ] && known=yes
done
if [ -z "$known" ]; then
    [ -n "$SITE_KEY" ] && echo "$(now) not a site key: $SITE_KEY"
    echo "$(now) usage: run.sh <site key>, one of: ${SITES// /, }"
    exit 1
fi

# Published files must be world-readable for Apache.
umask 022
# uv's standalone installer puts it here.
export PATH="$HOME/.local/bin:$PATH"

cd "$REPO_DIR" || { echo "$(now) cannot cd to $REPO_DIR"; exit 1; }

if [ -z "${WEB_ROOT:-}" ]; then
    config="around_the_grounds/config/sites/$SITE_KEY.json"
    domain=$(python3 -c '
import json, sys
from urllib.parse import urlparse
print(urlparse(json.load(open(sys.argv[1])).get("public_url", "")).hostname or "")
' "$config" 2>/dev/null)
    if [ -z "$domain" ]; then
        echo "$(now) $SITE_KEY: no public_url in $REPO_DIR/$config; set WEB_ROOT"
        exit 1
    fi
    WEB_ROOT="/var/www/$domain"
fi
LOCK_FILE="${LOCK_FILE:-/tmp/$SITE_KEY.lock}"
# One scrape at a time across all sites: they share upstream hosts (Untappd,
# Google Sheets), and the scraper only spaces out its own requests. A site
# waits up to QUEUE_WAIT seconds for another site's run to finish.
QUEUE_LOCK="${QUEUE_LOCK:-/tmp/freshies-queue.lock}"
QUEUE_WAIT="${QUEUE_WAIT:-1500}"

echo "$(now) $SITE_KEY: starting refresh into $WEB_ROOT"
# -n: if this site's previous run is still going, skip this one rather than
# pile up (exit 75). --no-sync: never change the environment from cron; run
# `uv sync` after pulls.
flock -n -E 75 "$LOCK_FILE" \
    flock -w "$QUEUE_WAIT" -E 75 "$QUEUE_LOCK" \
    uv run --no-sync around-the-grounds \
        --site "$SITE_KEY" --output-dir "$WEB_ROOT"
status=$?
# Exit codes: 0 clean, 2 some venues failed (site still published),
# 1 nothing published (every venue failed or a write error; last copy kept),
# 75 skipped because this site's previous run was still going, or another
# site's run did not finish in time.
echo "$(now) $SITE_KEY: finished with exit code $status"

# healthchecks.io counts any non-zero status as a failure. A partial run (2)
# still published and a skipped run (75) is not an outage, so both ping as
# success; only 1 and unexpected codes alert.
if [ -n "${HEALTHCHECK_URL:-}" ]; then
    case "$status" in
        2|75) ping_status=0 ;;
        *) ping_status=$status ;;
    esac
    curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL/$ping_status" > /dev/null || true
fi
exit "$status"
