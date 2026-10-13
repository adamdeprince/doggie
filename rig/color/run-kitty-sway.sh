#!/bin/sh
tree=$1; secs=$2; shift 2
export XDG_RUNTIME_DIR=/tmp/silkie-color-run-sway WAYLAND_DISPLAY=wayland-1
unset DISPLAY DBUS_SESSION_BUS_ADDRESS
exec timeout -s INT "$secs" "$tree/kitty/launcher/kitty" --config NONE -o linux_display_server=wayland "$@"
