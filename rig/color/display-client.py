#!/usr/bin/env python3
# Runs inside the terminal: asks the display protocol about the display, turns its events on and logs every reply for a while
import os, select, sys, termios, time, tty
log = open(sys.argv[1], "w")
secs = float(sys.argv[2])
fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
tty.setraw(fd)
try:
    def send(body):
        os.write(sys.stdout.fileno(), ("\x1b]777;display;" + body + "\x1b\\").encode())
    send("v=1:op=query:id=1")
    send("v=1:op=mode:mode=1")
    end = time.monotonic() + secs
    buf = b""
    while time.monotonic() < end:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            buf += os.read(fd, 4096)
            while b"\x1b\\" in buf:
                frame, buf = buf.split(b"\x1b\\", 1)
                log.write("%.2f %s\n" % (time.monotonic() - (end - secs), frame.decode("ascii", "replace").replace("\x1b", "ESC")))
                log.flush()
    send("v=1:op=mode:mode=0")
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
