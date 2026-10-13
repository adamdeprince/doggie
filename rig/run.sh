#!/bin/bash
# License: GPLv3 Copyright: 2026, Adam DePrince
#
# Runs a built kitty tree inside a headless sway, with wlproxy.py between
# them playing the input devices, and compares what a program inside the
# terminal receives with what was played. See README.rst.
#
#   rig/run.sh /path/to/built/tree [sequence ...]

set -u
if [ $# -lt 1 ] || [ ! -x "$1/kitty/launcher/kitty" ]; then
    echo "usage: $0 /path/to/built/kitty/tree [sequence ...]" >&2
    exit 2
fi
tree=$(realpath "$1")
shift
here=$(dirname "$(realpath "$0")")
run=$(mktemp -d /tmp/silkie-rig-run.XXXXXX)
chmod 700 "$run"
pids=()

cleanup() {
    for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null; done
    wait 2>/dev/null
    rm -f "$run"/wayland-* "$run"/control "$run"/sway-ipc.*
    echo "logs are in $run"
}
trap cleanup EXIT

wait_for() { # a path, seconds
    for _ in $(seq $(($2 * 20))); do
        [ -e "$1" ] && return 0
        sleep 0.05
    done
    echo "timed out waiting for $1" >&2
    return 1
}

# The compositor: no devices, no seat, no GPU. Everything it needs is in $run
cat >"$run/sway.conf" <<EOF
xwayland disable
swaybg_command -
swaynag_command -
default_border none
seat seat0 fallback true
output HEADLESS-1 mode --custom ${RIG_SIZE:-1280x800} scale 1
EOF
env -u WAYLAND_DISPLAY -u DISPLAY XDG_RUNTIME_DIR="$run" WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 \
    WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman sway --config "$run/sway.conf" >"$run/sway.log" 2>&1 &
pids+=($!)
wait_for "$run/wayland-1" 10 || exit 1

python3 "$here/wlproxy.py" --listen "$run/wayland-rig" --upstream "$run/wayland-1" --control "$run/control" \
    --log "$run/proxy.log" --xml "$tree/glfw" --tablet-version "${RIG_TABLET_VERSION:-2}" 2>"$run/proxy.err" &
pids+=($!)
wait_for "$run/control" 10 || exit 1

# The terminal, drawing in software since the compositor does. The client inside it logs what it is sent
mesa=/usr/share/glvnd/egl_vendor.d/50_mesa.json
env -u DISPLAY XDG_RUNTIME_DIR="$run" WAYLAND_DISPLAY=wayland-rig LIBGL_ALWAYS_SOFTWARE=1 \
    ${RIG_WAYLAND_DEBUG:+WAYLAND_DEBUG=1} $([ -e $mesa ] && echo __EGL_VENDOR_LIBRARY_FILENAMES=$mesa) \
    "$tree/kitty/launcher/kitty" --config NONE -o linux_display_server=wayland -o placement_strategy=top-left \
    -o window_padding_width=0 -o confirm_os_window_close=0 --debug-input \
    python3 "$here/client.py" --log "$run/client.log" --ready "$run/ready" --stop "$run/stop" --duration 300 ${RIG_CLIENT_ARGS:-} \
    >"$run/kitty.log" 2>&1 &
kitty=$!
pids+=($kitty)

python3 "$here/play.py" --control "$run/control" --expect "$run/expect.jsonl" --wait "$run/ready" "$@"
played=$?
touch "$run/stop"
for _ in $(seq 100); do
    kill -0 $kitty 2>/dev/null || break
    sleep 0.05
done
[ $played = 0 ] || { echo "playing failed, see $run/proxy.log and $run/proxy.err" >&2; exit 1; }
grep -E ' (error|warning) ' "$run/proxy.log"
python3 "$here/check.py" "$run/client.log" "$run/expect.jsonl"
