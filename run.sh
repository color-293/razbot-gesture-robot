#!/bin/sh
# (Re)start the gesture robot web app in the background.
cd "$(dirname "$0")"
pkill -f "venv/bin/python app.py"
sleep 1
setsid nohup venv/bin/python app.py "$@" > app.log 2>&1 < /dev/null &
echo "started (pid $!) - http://$(hostname -I | cut -d' ' -f1):5000"
