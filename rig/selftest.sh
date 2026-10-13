#!/bin/bash
# License: GPLv3 Copyright: 2026, Adam DePrince
#
# Checks the proxy itself, without a terminal: tabletdump.c, a small client
# built here with libwayland, connects through wlproxy.py, the tool and pad
# sequences are played to it, and what it prints is compared with
# selftest.expected.
#
#   rig/selftest.sh run-name
#
# Needs a C compiler, wayland-scanner and the libwayland-client headers.

set -u
if [ $# -lt 1 ] || [[ ! $1 =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "usage: $0 run-name" >&2
    exit 2
fi
run=/tmp/silkie-rig-$1
here=$(dirname "$(realpath "$0")")
lock=/tmp/silkie-rig.lock
locked=
pids=()

cleanup() {
    for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null; done
    wait 2>/dev/null
    rm -f "$run"/wayland-* "$run"/control "$run"/sway-ipc.*
    [ -n "$locked" ] && rmdir "$lock"
    locked=
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

wait_for() { # a path, seconds
    for _ in $(seq $(($2 * 20))); do
        [ -e "$1" ] && return 0
        sleep 0.05
    done
    echo "timed out waiting for $1" >&2
    return 1
}

for i in $(seq 1800); do
    mkdir "$lock" 2>/dev/null && locked=1 && break
    [ "$i" = 1 ] && echo "another rig run holds $lock, waiting for up to half an hour" >&2
    sleep 1
done
[ -n "$locked" ] || { echo "gave up waiting for $lock" >&2; exit 1; }
rm -rf "$run"
mkdir -m 700 "$run" || exit 1

protocols=$(pkg-config --variable=pkgdatadir wayland-protocols 2>/dev/null || echo /usr/share/wayland-protocols)
for x in stable/tablet/tablet-v2 stable/xdg-shell/xdg-shell; do
    name=$(basename $x)
    wayland-scanner client-header "$protocols/$x.xml" "$run/$name-client-protocol.h" || exit 1
    wayland-scanner private-code "$protocols/$x.xml" "$run/$name-protocol.c" || exit 1
done
${CC:-cc} -Wall -Wextra -O1 -I"$run" -o "$run/tabletdump" "$here/tabletdump.c" "$run"/*-protocol.c $(pkg-config --cflags --libs wayland-client) || exit 1

cat >"$run/sway.conf" <<CONF
xwayland disable
swaybg_command -
swaynag_command -
default_border none
seat seat0 fallback true
output HEADLESS-1 mode --custom 1280x800 scale 1
CONF
env -u WAYLAND_DISPLAY -u DISPLAY XDG_RUNTIME_DIR="$run" WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 \
    WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman sway --config "$run/sway.conf" >"$run/sway.log" 2>&1 &
pids+=($!)
wait_for "$run/wayland-1" 10 || exit 1
python3 "$here/wlproxy.py" --listen "$run/wayland-rig" --upstream "$run/wayland-1" --control "$run/control" \
    --log "$run/proxy.log" --tablet-version "${RIG_TABLET_VERSION:-2}" 2>"$run/proxy.err" &
pids+=($!)
wait_for "$run/control" 10 || exit 1
env XDG_RUNTIME_DIR="$run" WAYLAND_DISPLAY=wayland-rig "$run/tabletdump" >"$run/dump.log" 2>"$run/dump.err" &
pids+=($!)

python3 "$here/play.py" --control "$run/control" pen puck pads || { echo "playing failed, see $run/proxy.log" >&2; exit 1; }
sleep 0.3
status=0
grep -E ' (error|warning) ' "$run/proxy.log" && status=1
[ -s "$run/dump.err" ] && { cat "$run/dump.err"; status=1; }
grep ' request ' "$run/proxy.log" | cut -d' ' -f3- | sed -E 's/\[[0-9]+, /[N, /; s/, [0-9]+\]$/, N]/' | sort | uniq -c >"$run/requests.log"
if diff -u "$here/selftest.expected" <(cat "$run/dump.log"; echo '--- requests'; cat "$run/requests.log") >"$run/selftest.diff"; then
    echo "the proxy sent what it should: $(wc -l <"$run/dump.log") events as expected"
else
    cat "$run/selftest.diff"
    status=1
fi
echo "logs are in $run"
exit $status
