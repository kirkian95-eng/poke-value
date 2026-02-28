#!/bin/bash
# Start the Pokemon TCG EV Calculator web app
cd "$(dirname "$0")"

PIDFILE=".flask.pid"
PORT=5001

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Already running (PID $(cat "$PIDFILE")) on port $PORT"
    exit 1
fi

nohup python3 app.py > flask.log 2>&1 &
echo $! > "$PIDFILE"

sleep 1
if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    PUBLIC_IP=$(curl -s --connect-timeout 2 http://169.254.169.254/opc/v1/vnics/ 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)[0].get('publicIp',''))" 2>/dev/null)
    echo "Started (PID $(cat "$PIDFILE"))"
    echo "  Local:  http://localhost:$PORT"
    [ -n "$PUBLIC_IP" ] && echo "  Public: http://$PUBLIC_IP:$PORT"
    echo "  Logs:   $(pwd)/flask.log"
    echo "  Stop:   ./stop.sh"
else
    echo "Failed to start. Check flask.log"
    rm -f "$PIDFILE"
    exit 1
fi
