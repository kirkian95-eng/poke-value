#!/usr/bin/env bash
# Zero-token EV query script for Stephen.
# Usage: query-ev.sh "set name or partial match"
# Returns: JSON with set name, EV, MSRP, value ratio, top cards
# Exit 0 = found, Exit 1 = not found, Exit 2 = no prices

set -euo pipefail

QUERY="${1:-}"

if [ -z "$QUERY" ]; then
    echo '{"error": "Usage: query-ev.sh \"set name\""}'
    exit 1
fi

python3 /home/ubuntu/pokemon-tcg-ev/query_ev.py "$QUERY"
