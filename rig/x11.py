#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Adam DePrince

"""
Plays scripted input to a terminal running on an X server, through the
devices of the X server's own test driver, and writes down what a program
inside the terminal should receive for it.

The X server is started by xrun.sh with one device of the inputtest driver
per kind of hardware, each listening on a socket. Like the Wayland rig this
needs no hardware and no root, and the devices exist only inside that X
server. The driver knows a pen with pressure, without tilt, so less can be
played here than through wlproxy.py.
"""

import argparse
import os
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

from play import Rig as Expectations
from play import px

# xf86-input-inputtest-protocol.h {{{
CLIENT_VERSION, WAIT_FOR_SYNC, MOTION, PROXIMITY, BUTTON, KEY, TOUCH, GESTURE_PINCH, GESTURE_SWIPE = range(9)
TOUCH_BEGIN, TOUCH_UPDATE, TOUCH_END = 18, 19, 20  # the XInput 2 event types, which is what the driver wants
PINCH_BEGIN, PINCH_UPDATE, PINCH_END, SWIPE_BEGIN, SWIPE_UPDATE, SWIPE_END = range(27, 33)
AXIS_MAX = 0xFFFF  # the range of the position axes of the absolute devices
PRESSURE_MAX = 1000
X, Y, HSCROLL, VSCROLL, PRESSURE = range(5)


def valuators(values: dict[int, float]) -> bytes:
    mask = bytearray(8)
    vals = [0.0] * 64
    for i, v in values.items():
        mask[i // 8] |= 1 << (i % 8)
        vals[i] = v
    # has_unaccelerated, the mask, padding to the doubles, the values, the unaccelerated values
    return struct.pack('@I8s4x64d64d', 0, bytes(mask), *vals, *([0.0] * 64))


class Device:
    "One device of the inputtest driver"

    def __init__(self, path: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.send(CLIENT_VERSION, struct.pack('@HH', 1, 1))
        self.sock.recv(12)  # the version of the server

    def send(self, kind: int, body: bytes) -> None:
        self.sock.sendall(struct.pack('@Ii', 8 + len(body), kind) + body)

    def sync(self) -> None:
        "Waits until the X server has processed everything sent so far"
        self.send(WAIT_FOR_SYNC, b'')
        self.sock.recv(8)

    def motion(self, absolute: bool = True, **axes: float) -> None:
        self.send(MOTION, struct.pack('@I4x', absolute) + valuators(named(axes)))
        self.sync()

    def proximity(self, entering: bool, **axes: float) -> None:
        self.send(PROXIMITY, struct.pack('@I4x', entering) + valuators(named(axes)))
        self.sync()

    def button(self, button: int, press: bool, **axes: float) -> None:
        self.send(BUTTON, struct.pack('@iiI4x', 1, button, press) + valuators(named(axes)))
        self.sync()

    def touch(self, kind: int, touchid: int, **axes: float) -> None:
        self.send(TOUCH, struct.pack('@II', touchid, kind) + valuators(named(axes)))
        self.sync()

    def pinch(self, kind: int, fingers: int, scale: float = 1, angle: float = 0, cancelled: bool = False) -> None:
        self.send(GESTURE_PINCH, struct.pack('@HHI6d', kind, fingers, cancelled, 0, 0, 0, 0, scale, angle))
        self.sync()

    def swipe(self, kind: int, fingers: int, dx: float = 0, dy: float = 0, cancelled: bool = False) -> None:
        self.send(GESTURE_SWIPE, struct.pack('@HHI4d', kind, fingers, cancelled, dx, dy, dx, dy))
        self.sync()


def pressure(v: int) -> int:
    "What the terminal makes of a pressure, rounding halves up as C does"
    return int(v * 65535 / PRESSURE_MAX + 0.5)


def named(axes: dict[str, float]) -> dict[int, float]:
    return {{'x': X, 'y': Y, 'hscroll': HSCROLL, 'vscroll': VSCROLL, 'pressure': PRESSURE}[k]: v for k, v in axes.items()}


# }}}


class Rig(Expectations):
    def __init__(self, sockets: str, expect: str, width: int, height: int) -> None:
        self.expectations = open(expect, 'w', buffering=1) if expect else None
        self.width, self.height = width, height
        self.centred = 0
        self.display = ''
        self.udev = self.node = False
        self.devices = {name: Device(os.path.join(sockets, name)) for name in ('stylus', 'eraser', 'touchscreen', 'touchpad', 'mouse')}

    def at(self, x: float, y: float) -> dict[str, float]:
        "A position in pixels as the axis values that the X server scales to it"
        return {'x': x * (AXIS_MAX + 1) / self.width, 'y': y * (AXIS_MAX + 1) / self.height}


def centre(rig: Rig) -> tuple[float, float]:
    """Puts the pointer near the middle of the window and says where. X has one pointer, which a pen moves too.
    The place differs a little each time, as a hand never returns a mouse to the very same pixel"""
    rig.centred += 5
    x, y = rig.width / 2 + rig.centred, rig.height / 2
    rig.devices['mouse'].motion(**rig.at(x, y))
    time.sleep(0.05)
    return x, y


def setup(rig: Rig) -> None:
    # without a window manager the window under the pointer has the keyboard
    centre(rig)
    time.sleep(0.3)


def on_tablet(rig: Rig, x: float, y: float, left: float = 0, width: float = 1) -> dict[str, int]:
    """Where on its tablet a tool is when the pointer is at a pixel, as the tablet pointer protocol reports it: the
    tablet is mapped to the part of the screen that starts at left and is width wide, both fractions of the screen"""
    return {'rx': min(65535, round((x / rig.width - left) / width * (AXIS_MAX + 1))), 'ry': min(65535, round(y * (AXIS_MAX + 1) / rig.height))}


# The size of the tablet the stylus and the eraser are on, as fakeudev.c gives it for the node xrun.sh names
UDEV_TABLET = {'w': 224 * 256, 'h': 140 * 256, 'direct': 0}


def tablet_facts(rig: Rig) -> dict[str, Any]:
    """What the description of a tool says of its tablet. The size and whether it is a display come from the kernel,
    by the device node the driver names, and only with the stand-in libudev does that node lead to a tablet"""
    if not rig.node:
        return {}
    if rig.udev:
        return dict(UDEV_TABLET)
    return {k: 'absent' for k in UDEV_TABLET}


def stroke(rig: Rig, tool: str = 'stylus') -> None:
    "A pen comes into proximity, hovers, draws a diagonal with rising pressure, lifts and leaves"
    d = rig.devices[tool]
    number = {'stylus': 1, 'eraser': 2}[tool]
    x, y = 100.0, 100.0
    rig.expect('tablet-pointer:device', f'{tool}: is described', kind=1, tool=number, **tablet_facts(rig))

    def sample(note: str, phase: int, buttons: int, force: int) -> None:
        d.motion(**rig.at(x, y), pressure=force)
        rig.expect(
            'tablet-pointer', f'{tool}: {note}', kind=1, phase=phase, x=px(x), y=px(y), buttons=buttons, tool=number, p=pressure(force), **on_tablet(rig, x, y)
        )
        time.sleep(0.008)

    d.proximity(True, **rig.at(x, y), pressure=0)
    sample('enters proximity', 0, 0, 0)
    for _ in range(3):
        x, y = x + 10, y + 25
        sample('hovers', 0, 0, 0)
    d.button(1, True, **rig.at(x, y), pressure=100)
    rig.expect('tablet-pointer', f'{tool}: tip down', kind=1, phase=1, x=px(x), y=px(y), buttons=1, tool=number, p=pressure(100))
    for i in range(1, 9):
        x, y = x + 20, y + 25
        sample(f'stroke point {i}', 2, 1, 100 + 100 * i)
    d.button(1, False, **rig.at(x, y), pressure=0)
    rig.expect('tablet-pointer', f'{tool}: tip up', kind=1, phase=3, x=px(x), y=px(y), buttons=0, tool=number)
    # the X server tells XInput 2 clients nothing of a tool leaving, see docs/tablet-protocol.rst
    d.proximity(False, **rig.at(x, y), pressure=0)
    time.sleep(0.1)


def mapped(rig: Rig, tool: str = 'stylus') -> None:
    """The tablet is mapped to the middle half of the screen, as a user does who has two monitors, while the
    terminal runs. The pointer goes where the server puts it and the place on the tablet is still the tablet's"""
    if not rig.display:
        raise SystemExit('the mapped sequence needs --display, to set the mapping with xinput')
    d = rig.devices[tool]
    name = f'Rig Wacom Intuos5 touch M Pen {tool}'
    left, width = 0.25, 0.5

    def map_to(*matrix: float) -> None:
        subprocess.run(
            ['xinput', 'set-prop', name, 'Coordinate Transformation Matrix', *map(str, matrix)], env={**os.environ, 'DISPLAY': rig.display}, check=True
        )
        time.sleep(0.1)

    map_to(width, 0, left, 0, 1, 0, 0, 0, 1)
    try:
        d.proximity(True, x=0, y=0, pressure=0)
        for i, (fx, fy) in enumerate(((0.0, 0.25), (0.25, 0.5), (0.5, 0.5), (0.9, 0.75))):
            # the tool is at this fraction of the tablet, and the pointer at what the mapping makes of it
            x, y = (left + fx * width) * rig.width, fy * rig.height
            d.motion(x=fx * (AXIS_MAX + 1), y=fy * (AXIS_MAX + 1), pressure=0)
            rig.expect('tablet-pointer', f'{tool}: mapped, point {i}', kind=1, phase=0, x=px(x), y=px(y), **on_tablet(rig, x, y, left, width))
            time.sleep(0.02)
        d.proximity(False, x=0, y=0, pressure=0)
    finally:
        map_to(1, 0, 0, 0, 1, 0, 0, 0, 1)
    time.sleep(0.1)


def buttons(rig: Rig) -> None:
    "The side buttons of a pen, which are X buttons 2 and 3, and the back and forward buttons, 8 and 9"
    d = rig.devices['stylus']
    x, y = 300, 200
    d.proximity(True, **rig.at(x, y), pressure=0)
    d.motion(**rig.at(x, y), pressure=0)
    rig.expect('tablet-pointer', 'buttons: hovers', kind=1, phase=0, x=px(x), y=px(y), buttons=0)
    for button, bit, name in ((2, 2, 'lower'), (3, 4, 'upper'), (8, 8, 'back'), (9, 16, 'forward')):
        d.button(button, True, **rig.at(x, y), pressure=0)
        rig.expect('tablet-pointer', f'buttons: {name} button down', kind=1, phase=0, buttons=bit)
        d.button(button, False, **rig.at(x, y), pressure=0)
        rig.expect('tablet-pointer', f'buttons: {name} button up', kind=1, phase=0, buttons=0)
        time.sleep(0.02)
    d.button(1, True, **rig.at(x, y), pressure=500)
    rig.expect('tablet-pointer', 'buttons: tip down', kind=1, phase=1, buttons=1)
    d.button(2, True, **rig.at(x, y), pressure=500)
    rig.expect('tablet-pointer', 'buttons: lower button while drawing', kind=1, phase=2, buttons=3)
    d.button(2, False, **rig.at(x, y), pressure=500)
    rig.expect('tablet-pointer', 'buttons: released', kind=1, phase=2, buttons=1)
    d.button(1, False, **rig.at(x, y), pressure=0)
    rig.expect('tablet-pointer', 'buttons: tip up', kind=1, phase=3, buttons=0)
    d.proximity(False, **rig.at(x, y), pressure=0)
    time.sleep(0.1)


def touch(rig: Rig) -> None:
    "A touchscreen: one finger draws, then two fingers land, move and lift. XInput 2.2 has no frames, each event stands alone"
    d = rig.devices['touchscreen']

    def finger(note: str, kind: int, touchid: int, x: float, y: float, phase: int) -> None:
        d.touch(kind, touchid, **rig.at(x, y))
        rig.expect('tablet-pointer', f'touch: {note}', kind=2, phase=phase, x=px(x), y=px(y), tool=0, buttons=0 if phase == 3 else 1)
        rig.expect('tablet-pointer', f'touch: {note}, end of the group', kind=2, phase=6)
        time.sleep(0.012)

    finger('one finger down', TOUCH_BEGIN, 0, 200, 300, 1)
    for i in range(1, 5):
        finger('it moves', TOUCH_UPDATE, 0, 200 + 10 * i, 300, 2)
    finger('it lifts', TOUCH_END, 0, 240, 300, 3)
    time.sleep(0.05)
    finger('first of two fingers down', TOUCH_BEGIN, 1, 300, 400, 1)
    finger('second finger down', TOUCH_BEGIN, 2, 500, 400, 1)
    finger('the first moves', TOUCH_UPDATE, 1, 300, 450, 2)
    finger('the second moves', TOUCH_UPDATE, 2, 500, 450, 2)
    finger('the first lifts', TOUCH_END, 1, 300, 450, 3)
    finger('the second lifts', TOUCH_END, 2, 500, 450, 3)
    time.sleep(0.1)


def gestures(rig: Rig) -> None:
    "The gestures of XInput 2.4: a pinch that also turns, one that is cancelled, a three finger swipe"
    d = rig.devices['touchpad']
    x, y = centre(rig)
    at = {'x': px(x), 'y': px(y)}
    d.pinch(PINCH_BEGIN, 2)
    rig.expect('gesture', 'pinch begins', kind=1, phase=1, scale=0, total=1000, fingers=2, **at)
    rig.expect('gesture', 'and the rotation that goes with it', kind=2, phase=1, angle=0, total=0, fingers=2, **at)
    total = 0.0
    for scale, turn in ((1.125, 5), (1.25, 5), (1.125, -2.5)):
        time.sleep(0.012)
        d.pinch(PINCH_UPDATE, 2, scale, turn)
        total += turn
        rig.expect('gesture', f'pinch to {scale}', kind=1, phase=2, total=round(scale * 1000))
        rig.expect('gesture', f'turned by {turn} degrees', kind=2, phase=2, angle=round(turn * 100), total=round(total * 100))
    d.pinch(PINCH_END, 2, 1.125)
    rig.expect('gesture', 'pinch ends', kind=1, phase=3)
    rig.expect('gesture', 'rotation ends', kind=2, phase=3)
    time.sleep(0.05)
    d.pinch(PINCH_BEGIN, 2)
    rig.expect('gesture', 'a second pinch begins', kind=1, phase=1)
    rig.expect('gesture', 'with its rotation', kind=2, phase=1)
    d.pinch(PINCH_END, 2, cancelled=True)
    rig.expect('gesture', 'and is taken over', kind=1, phase=4)
    rig.expect('gesture', 'with its rotation', kind=2, phase=4)
    time.sleep(0.05)
    d.swipe(SWIPE_BEGIN, 3)
    for _ in range(4):
        d.swipe(SWIPE_UPDATE, 3, -20, 2)
    d.swipe(SWIPE_END, 3)
    rig.expect('gesture', 'a three finger swipe to the left begins', kind=3, phase=1, dx=-1, dy=0, fingers=3)
    rig.expect('gesture', 'and ends', kind=3, phase=3, dx=-1, dy=0, fingers=3)
    time.sleep(0.1)


def scroll(rig: Rig) -> None:
    """The scroll axis of a pointer device, on which 120 is one notch: a notch down, a notch up, then a notch in
    ten small steps, as a wheel with fine steps turns. A notch is five lines of 18 pixels with the default settings"""
    d = rig.devices['touchpad']
    x, y = centre(rig)
    at = {'x': round(x), 'y': round(y)}
    for step, note in ((120, 'down'), (-120, 'up')):
        d.motion(absolute=False, vscroll=step)
        rig.expect('scroll', f'a notch {note}', dx=0, dy=75 * step, src=0, phase=0, **at)
        time.sleep(0.3)
    for i in range(10):
        d.motion(absolute=False, vscroll=12)
        rig.expect('scroll', f'a tenth of a notch, {i + 1} of 10', dx=0, dy=900, src=0, **at)
        time.sleep(0.012)
    time.sleep(1.0)
    rig.mark(skip='scroll')


def mouse(rig: Rig) -> None:
    """A mouse moves in steps and stops. What a program asks of the mouse it asks with the mouse protocol, so there is
    nothing here for check.py: run the client with --mouse and read the csi lines of its log against these positions"""
    for i in range(1, 9):
        rig.devices['mouse'].motion(**rig.at(200 + 100 * i, 300))
        rig.mark(mouse=[200 + 100 * i, 300])
        time.sleep(0.05)
    time.sleep(0.2)


SEQUENCES: dict[str, Callable[[Rig], None]] = {
    'stylus': lambda rig: stroke(rig, 'stylus'),
    'eraser': lambda rig: stroke(rig, 'eraser'),
    'mapped': mapped,
    'buttons': buttons,
    'touch': touch,
    'gestures': gestures,
    'scroll': scroll,
    'mouse': mouse,
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--sockets', required=True, help='The directory with the sockets of the devices')
    p.add_argument('--expect', help='Where to write what the program in the terminal should receive')
    p.add_argument('--wait', help='A file that appears when the program in the terminal is ready')
    p.add_argument('--size', default='1280x800', help='The size of the screen and of the window that fills it')
    p.add_argument('--display', default='', help='The X display, for the sequences that change a setting of the server')
    p.add_argument('--node', action='store_true', help='The tablet devices name a device node, as the drivers of real tablets do')
    p.add_argument('--udev', action='store_true', help='The terminal has fakeudev.c for its libudev, so that node is a tablet')
    p.add_argument('sequences', nargs='*', help=f'What to play, all by default: {", ".join(SEQUENCES)}')
    args = p.parse_args()
    width, height = map(int, args.size.split('x'))
    rig = Rig(args.sockets, args.expect, width, height)
    rig.display = args.display
    rig.udev, rig.node = args.udev, args.node
    end = time.monotonic() + 30
    while args.wait and not os.path.exists(args.wait):
        if time.monotonic() > end:
            raise TimeoutError('the program in the terminal did not get ready')
        time.sleep(0.05)
    setup(rig)
    for name in args.sequences or SEQUENCES:
        rig.mark(sequence=name)
        try:
            SEQUENCES[name](rig)
        except (BrokenPipeError, ConnectionResetError):
            rig.mark(died=name)
            print(f'the X server dropped a device during {name}', file=sys.stderr)
            sys.exit(3)
        time.sleep(0.2)


if __name__ == '__main__':
    main()
