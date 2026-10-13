#!/bin/sh
# force-hdr.sh true|false : switches the headless Mutter between SDR and HDR (needs --debug-control, which start-mutter.sh passes)
export DBUS_SESSION_BUS_ADDRESS=$(cat /tmp/silkie-color-run/bus-address)
exec gdbus call --session --dest org.gnome.Mutter.DebugControl --object-path /org/gnome/Mutter/DebugControl --method org.freedesktop.DBus.Properties.Set org.gnome.Mutter.DebugControl ForceHDR "<$1>"
