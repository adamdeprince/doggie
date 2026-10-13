#!/bin/sh
# Starts a headless sway (no color management global) in a private runtime dir, socket $XDG_RUNTIME_DIR/wayland-1
export XDG_RUNTIME_DIR=/tmp/silkie-color-run-sway
mkdir -p -m 700 "$XDG_RUNTIME_DIR"
unset WAYLAND_DISPLAY DISPLAY SWAYSOCK
export WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1
exec sway -c /dev/null
