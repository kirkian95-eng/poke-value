#!/bin/bash
# Stop the Pokemon TCG EV Calculator web app
cd "$(dirname "$0")"

PIDFILE=".flask.pid"

if [ ! -f "$PIDFILE" ]; then
    echo "No PID file found. Is the app running?"
    exit 1
fi

PID=$(cat "$PIDFILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "Stopped (PID $PID)"
else
    echo "Process $PID not running (stale PID file)"
fi
rm -f "$PIDFILE"
