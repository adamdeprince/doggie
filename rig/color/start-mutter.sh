#!/bin/sh
# Starts a headless Mutter with one virtual monitor in a private runtime dir and session bus.
# The Wayland socket is $XDG_RUNTIME_DIR/silkie-color-0
export XDG_RUNTIME_DIR=/tmp/silkie-color-run
mkdir -p -m 700 "$XDG_RUNTIME_DIR"
rm -f "$XDG_RUNTIME_DIR"/silkie-color-0* "$XDG_RUNTIME_DIR"/bus-address
unset WAYLAND_DISPLAY DISPLAY
# defaults only: nothing is read from or written to the user's dconf database
export GSETTINGS_BACKEND=memory
exec dbus-run-session -- sh -c "echo \$DBUS_SESSION_BUS_ADDRESS > $XDG_RUNTIME_DIR/bus-address; exec gnome-shell --headless --wayland --no-x11 --mode=user --debug-control --wayland-display silkie-color-0 --virtual-monitor ${1:-1920x1080}"
