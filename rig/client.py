#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Adam DePrince

"""
The program that runs inside the terminal under test. It asks the terminal
what it supports, turns on the OSC 777 input extensions and writes every
frame the terminal sends to a log, one per line, with the time it arrived.

It knows nothing about what the frames mean: a selector, an op or a field it
has never heard of is logged like any other, so it keeps working while the
protocols change.
"""

import argparse
import os
import select
import sys
import termios
import time
import tty
from typing import IO

ST = '\x1b\\'


class Log:
    def __init__(self, f: IO[str]) -> None:
        self.f = f

    def __call__(self, kind: str, text: str) -> None:
        # CLOCK_MONOTONIC, the clock Wayland and X11 event times are on
        self.f.write(f'{time.monotonic():.6f} {kind} {text}\n')


class Reader:
    """Splits the terminal's input stream into escape sequences and text"""

    def __init__(self, log: Log) -> None:
        self.buf = b''
        self.log = log
        self.frames = 0

    def feed(self, data: bytes) -> None:
        self.buf += data
        while self.buf:
            n = self.take()
            if n == 0:
                return
            self.buf = self.buf[n:]

    def take(self) -> int:
        b = self.buf
        if b[:1] != b'\x1b':
            n = b.find(b'\x1b')
            n = len(b) if n < 0 else n
            self.log('text', repr(b[:n])[2:-1])
            return n
        if len(b) < 2:
            return 0
        if b[1:2] in b']P_^X':  # OSC, DCS, APC, PM, SOS: up to ST or BEL
            ends = [(i, n) for i, n in ((b.find(b'\x1b\\', 2), 2), (b.find(b'\x07', 2), 1)) if i >= 0]
            if not ends:
                return 0
            i, n = min(ends)
            body = b[2:i].decode('utf-8', 'replace')
            if b[1:2] == b']' and body.startswith('777;'):
                self.frames += 1
                self.log('osc777', body[4:])
            else:
                self.log('esc' + chr(b[1]), body)
            return i + n
        if b[1:2] == b'[':
            for i in range(2, len(b)):
                if 0x40 <= b[i] <= 0x7E:
                    self.log('csi', b[2 : i + 1].decode('ascii', 'replace'))
                    return i + 1
            return 0
        self.log('esc', repr(b[1:2])[2:-1])
        return 2


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--log', required=True, help='Where to write the frames')
    p.add_argument('--ready', help='A file to create once the modes have been requested')
    p.add_argument('--stop', help='Exit when this file exists')
    p.add_argument('--duration', type=float, default=60, help='Exit after this many seconds')
    p.add_argument('--tablet', default='3,31', help='tablet-pointer modes to request, in order; the terminal keeps the last one it accepts. 0 for none')
    p.add_argument('--gesture', default='1,3', help='gesture modes to request, in order. 0 for none')
    p.add_argument('--scroll', default='1', help='scroll modes to request, in order. 0 for none')
    p.add_argument('--mouse', action='store_true', help='Also turn on SGR pixel mouse reporting, to see what falls back to the mouse')
    args = p.parse_args()

    fd = os.open(os.ctermid(), os.O_RDWR | os.O_NOCTTY)
    old = termios.tcgetattr(fd)
    selectors = {'tablet-pointer': args.tablet, 'gesture': args.gesture, 'scroll': args.scroll}
    with open(args.log, 'w', buffering=1) as f:
        log = Log(f)
        reader = Reader(log)

        def send(text: str) -> None:
            log('sent', text.replace('\x1b', 'ESC'))
            os.write(fd, text.encode())

        def frame(selector: str, body: str) -> None:
            send(f'\x1b]777;{selector};{body}{ST}')

        def pump(seconds: float) -> None:
            end = time.monotonic() + seconds
            while (left := end - time.monotonic()) > 0:
                if select.select([fd], [], [], min(left, 0.05))[0]:
                    reader.feed(os.read(fd, 65536))
                if args.stop and os.path.exists(args.stop):
                    return

        tty.setraw(fd)
        try:
            for i, selector in enumerate(('caps', 'tablet-pointer', 'gesture', 'scroll', 'haptic', 'display', 'frame', 'latency')):
                frame(selector, f'v=1:op=query:id={i + 1}')
            pump(0.3)
            for selector, modes in selectors.items():
                for mode in modes.split(','):
                    if int(mode):
                        frame(selector, f'v=1:op=mode:mode={mode}')
                frame(selector, 'v=1:op=mode')  # read back what the terminal kept
                frame(selector, f'v=1:op=query:id={100 + len(selector)}')
            if args.mouse:
                send('\x1b[?1003h\x1b[?1016h')
            pump(0.3)
            if args.ready:
                with open(args.ready, 'w') as r:
                    r.write(f'{reader.frames}\n')
            pump(args.duration)
        finally:
            for selector, modes in selectors.items():
                if modes != '0':
                    frame(selector, 'v=1:op=mode:mode=0')
            if args.mouse:
                send('\x1b[?1003l\x1b[?1016l')
            pump(0.2)
            log('done', f'{reader.frames} frames')
            termios.tcsetattr(fd, termios.TCSAFLUSH, old)
            os.close(fd)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
