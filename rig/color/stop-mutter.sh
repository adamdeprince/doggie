#!/bin/sh
# Stops only the processes of the session started by start-mutter.sh
[ -f /tmp/silkie-color-run/mutter.pid ] || exit 0
sid=$(ps -o sid= -p "$(cat /tmp/silkie-color-run/mutter.pid)" 2>/dev/null | tr -d " ")
[ -n "$sid" ] && pkill -TERM -s "$sid"
sleep 1
[ -n "$sid" ] && pkill -KILL -s "$sid" 2>/dev/null
# services the private session bus activated carry its runtime dir in their environment
for p in $(pgrep -u "$(id -u)"); do (tr "\0" "\n" < /proc/$p/environ) 2>/dev/null | grep -qx "XDG_RUNTIME_DIR=/tmp/silkie-color-run" && kill "$p" 2>/dev/null; done
rm -f /tmp/silkie-color-run/mutter.pid
true
