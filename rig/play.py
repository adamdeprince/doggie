#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Adam DePrince

"""
Plays scripted input to the terminal under test through wlproxy.py, and
writes down what a program inside the terminal should receive for it.

The devices imitate real ones: the names, USB ids, tool ids, serial numbers
and layouts are those of libinput's test devices and of libwacom, and the
events are in the order and units a compositor sends them in. What follows
from them according to docs/tablet-protocol.rst, docs/gesture-protocol.rst
and docs/scroll-protocol.rst goes to the expectations file, which check.py
compares with the client's log.
"""

import argparse
import json
import socket
import time
from collections.abc import Callable
from typing import IO, Any

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
BTN_STYLUS3, BTN_STYLUS, BTN_STYLUS2 = 0x149, 0x14B, 0x14C

# Tablets, tools and pads. A serial and a hardware id stay with the pen, whichever tablet it is used on
DEVICES: dict[str, dict[str, Any]] = {
    # libinput: litest-device-wacom-intuos5-pen.c and -pad.c
    'tablet:intuos5': {'name': 'Wacom Intuos5 touch M Pen', 'vid': 0x56A, 'pid': 0x27, 'bustype': 3, 'paths': ['/dev/input/event90']},
    'tool:pen': {'type': 'pen', 'serial': 578837976, 'hwid': 0x802, 'caps': ['pressure', 'distance', 'tilt']},
    'tool:eraser': {'type': 'eraser', 'serial': 578837976, 'hwid': 0x80A, 'caps': ['pressure', 'distance', 'tilt']},
    # the Art Pen turns, the Airbrush has a wheel, the lens cursor is a puck with a wheel
    'tool:artpen': {'type': 'pen', 'serial': 0x4100B0A1, 'hwid': 0x804, 'caps': ['pressure', 'distance', 'tilt', 'rotation']},
    'tool:airbrush': {'type': 'airbrush', 'serial': 0x4100B0A2, 'hwid': 0x902, 'caps': ['pressure', 'distance', 'tilt', 'slider']},
    'tool:lens': {'type': 'lens', 'serial': 0x4100B0A3, 'hwid': 0x96, 'caps': ['wheel']},
    'pad:intuos5': {'buttons': 9, 'paths': ['/dev/input/event91'], 'groups': [{'buttons': list(range(9)), 'rings': 1, 'modes': 4}]},
    # libinput: litest-device-wacom-intuos3-pad.c, the small Intuos3 has four keys and one strip
    'pad:intuos3': {'buttons': 4, 'paths': ['/dev/input/event92'], 'groups': [{'buttons': [0, 1, 2, 3], 'strips': 1, 'modes': 1}]},
    # libinput: litest-device-huion-q620m-dial.c
    'pad:huion': {'buttons': 1, 'paths': ['/dev/input/event93'], 'groups': [{'buttons': [0], 'dials': 1, 'modes': 1}]},
    # libinput: litest-device-wacom-cintiq-pro-16-pen.c, a pen display with a three button pen
    'tablet:cintiq': {'name': 'Wacom Cintiq Pro 16 Pen', 'vid': 0x56A, 'pid': 0x350, 'bustype': 3, 'paths': ['/dev/input/event94']},
    'tool:propen': {'type': 'pen', 'serial': 297797542, 'hwid': 0x823, 'caps': ['pressure', 'distance', 'tilt']},
}


class Rig:
    def __init__(self, control: str, expect: IO[str] | None) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(control)
        self.reader = self.sock.makefile('r')
        self.expectations = expect
        self.width, self.height = 0, 0

    def command(self, **cmd: Any) -> dict[str, Any]:
        self.sock.sendall(json.dumps(cmd).encode() + b'\n')
        ans: dict[str, Any] = json.loads(self.reader.readline())
        if not ans.pop('ok'):
            raise RuntimeError(f'{cmd}: {ans["error"]}')
        return ans

    def play(self, to: str, *events: list[Any]) -> None:
        self.command(op='play', to=to, events=list(events))

    def expect(self, selector: str, note: str, **fields: Any) -> None:
        "A report the program should now get: the fields named must have these values, others are not looked at"
        if self.expectations:
            self.expectations.write(json.dumps({'selector': selector, 'note': note, 'fields': {k: str(v) for k, v in fields.items()}}) + '\n')

    def wait_for_window(self, timeout: float = 20) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            info = self.command(op='info')
            if info.get('connected') and info['surface'] and info['size'][0]:
                self.width, self.height = info['size']
                return
            time.sleep(0.1)
        raise TimeoutError('the terminal did not open a window')


def px(v: float) -> int:
    return round(v * 256)


# Sequences {{{
def setup(rig: Rig) -> None:
    "The tablets and tools, and the keyboard and pointer focus a compositor gives the only window"
    # Pads are plugged in by the sequences that use them, so that a terminal
    # that cannot cope with a pad still gets through the others
    for device, d in DEVICES.items():
        if not device.startswith('pad:'):
            rig.command(op='add', device=device, **d)
    rig.wait_for_window()
    rig.play('keyboard', ['enter', '$serial', '$surface', []], ['modifiers', '$serial', 0, 0, 0, 0])
    rig.play('pointer', ['enter', '$serial', '$surface', rig.width / 2, rig.height / 2], ['frame'])
    time.sleep(0.2)


def tool_stroke(rig: Rig, tool: str = 'pen', tablet: str = 'intuos5', kind: int = 1, extra: Callable[[int], list[list[Any]]] | None = None) -> None:
    "A tool comes into proximity, hovers, draws a diagonal with rising pressure and changing tilt, and leaves"
    t = f'tool:{tool}'
    tool_id = {'pen': 1, 'eraser': 2, 'brush': 3, 'pencil': 4, 'airbrush': 5, 'mouse': 6, 'lens': 7}[DEVICES[t]['type']]
    caps = DEVICES[t]['caps']
    has = {c: c in caps for c in ('pressure', 'distance', 'tilt')}
    x, y = 100.0, 100.0

    def axes(pressure: int, distance: int, tx: float, ty: float) -> list[list[Any]]:
        ans: list[list[Any]] = [['motion', x, y]]
        if has['pressure']:
            ans.append(['pressure', pressure])
        if has['distance']:
            ans.append(['distance', distance])
        if has['tilt']:
            ans.append(['tilt', tx, ty])
        return ans

    def report(note: str, phase: int, buttons: int, pressure: int, distance: int, tx: float, ty: float) -> None:
        f: dict[str, Any] = {'kind': 1, 'phase': phase, 'contact': 0, 'x': px(x), 'y': px(y), 'buttons': buttons, 'tool': tool_id}
        if has['pressure']:
            f['p'] = pressure
        if has['distance']:
            f['dist'] = distance
        if has['tilt']:
            f['tx'], f['ty'] = round(tx * 100), round(ty * 100)
        rig.expect('tablet-pointer', f'{tool}: {note}', **f)

    rig.play(t, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], *axes(0, 40000, 0, 0), ['frame', '$time'])
    report('enters proximity', 0, 0, 0, 40000, 0, 0)
    for i in range(3):
        time.sleep(0.008)
        x, y = x + 10, y + 5
        rig.play(t, *axes(0, 30000 - 10000 * i, 0, 0), ['frame', '$time'])
        report('hovers', 0, 0, 0, 30000 - 10000 * i, 0, 0)
    time.sleep(0.008)
    rig.play(t, ['down', '$serial'], *axes(5000, 0, 10, -5), ['frame', '$time'])
    report('tip down', 1, 1, 5000, 0, 10, -5)
    for i in range(1, 11):
        time.sleep(0.008)
        x, y = x + 20.25, y + 12.5
        events = axes(5000 + 6000 * i, 0, 10 + 4 * i, -5 - 3 * i)
        if extra:
            events += extra(i)
        rig.play(t, *events, ['frame', '$time'])
        report(f'stroke point {i}', 2, 1, 5000 + 6000 * i, 0, 10 + 4 * i, -5 - 3 * i)
    time.sleep(0.008)
    rig.play(t, ['up'], *axes(0, 0, 50, -35), ['frame', '$time'])
    report('tip up', 3, 0, 0, 0, 50, -35)
    time.sleep(0.008)
    rig.play(t, ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', f'{tool}: leaves proximity', kind=1, phase=5)
    time.sleep(0.1)


def tool_buttons(rig: Rig, tool: str = 'propen', tablet: str = 'cintiq') -> None:
    "The three side buttons of a pen, pressed while hovering and while drawing"
    t = f'tool:{tool}'
    x, y = 300, 200

    def step(note: str, phase: int, buttons: int, *events: list[Any]) -> None:
        rig.play(t, *events, ['frame', '$time'])
        rig.expect('tablet-pointer', f'{tool}: {note}', kind=1, phase=phase, x=px(x), y=px(y), buttons=buttons)
        time.sleep(0.02)

    step(
        'enters proximity',
        0,
        0,
        ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'],
        ['motion', x, y],
        ['pressure', 0],
        ['distance', 20000],
        ['tilt', 0, 0],
    )
    step('lower button while hovering', 0, 2, ['button', '$serial', BTN_STYLUS, 1])
    step('lower button released', 0, 0, ['button', '$serial', BTN_STYLUS, 0])
    step('tip down', 1, 1, ['down', '$serial'], ['pressure', 30000], ['distance', 0])
    step('upper button while drawing', 2, 1 | 4, ['button', '$serial', BTN_STYLUS2, 1])
    step('third button too', 2, 1 | 4 | 32, ['button', '$serial', BTN_STYLUS3, 1])
    step('upper button released', 2, 1 | 32, ['button', '$serial', BTN_STYLUS2, 0])
    step('third button released', 2, 1, ['button', '$serial', BTN_STYLUS3, 0])
    step('tip up', 3, 0, ['up'], ['pressure', 0])
    rig.play(t, ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', f'{tool}: leaves proximity', kind=1, phase=5)
    time.sleep(0.1)


def tool_burst(rig: Rig, tool: str = 'pen', tablet: str = 'intuos5') -> None:
    "Ten samples 5 ms apart that all arrive at once, as after a stall: their times must stay 5 ms apart"
    t = f'tool:{tool}'
    rig.play(
        t,
        ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'],
        ['motion', 400, 400],
        ['pressure', 0],
        ['distance', 0],
        ['tilt', 0, 0],
        ['frame', '$time-60'],
    )
    rig.expect('tablet-pointer', 'burst: enters proximity', kind=1, phase=0)
    events: list[list[Any]] = [['down', '$serial'], ['motion', 400, 400], ['pressure', 20000], ['frame', '$time-50']]
    for i in range(1, 10):
        events += [['motion', 400 + 8 * i, 400], ['pressure', 20000], ['frame', f'$time-{50 - 5 * i}']]
    rig.play(t, *events)
    rig.expect('tablet-pointer', 'burst: tip down', kind=1, phase=1, x=px(400))
    for i in range(1, 10):
        rig.expect('tablet-pointer', f'burst: point {i}, 5 ms after the one before', kind=1, phase=2, x=px(400 + 8 * i), dt=5)
    rig.play(t, ['up'], ['pressure', 0], ['frame', '$time'], ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', 'burst: tip up', kind=1, phase=3)
    rig.expect('tablet-pointer', 'burst: leaves proximity', kind=1, phase=5)
    time.sleep(0.1)


def pen(rig: Rig) -> None:
    tool_stroke(rig, 'pen')


def eraser(rig: Rig) -> None:
    tool_stroke(rig, 'eraser')


SEQUENCES: dict[str, Callable[[Rig], None]] = {'pen': pen, 'eraser': eraser, 'buttons': tool_buttons, 'burst': tool_burst}
# }}}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--control', required=True, help='The control socket of wlproxy.py')
    p.add_argument('--expect', help='Where to write what the program in the terminal should receive')
    p.add_argument('--wait', help='A file that appears when the program in the terminal is ready')
    p.add_argument('sequences', nargs='*', help=f'What to play, all by default: {", ".join(SEQUENCES)}')
    args = p.parse_args()
    with open(args.expect, 'w', buffering=1) if args.expect else open('/dev/null', 'w') as f:
        rig = Rig(args.control, f if args.expect else None)
        setup(rig)
        if args.wait:
            import os

            end = time.monotonic() + 20
            while not os.path.exists(args.wait):
                if time.monotonic() > end:
                    raise TimeoutError('the program in the terminal did not get ready')
                time.sleep(0.05)
        for name in args.sequences or SEQUENCES:
            if f:
                f.write(json.dumps({'sequence': name}) + '\n')
            SEQUENCES[name](rig)
            time.sleep(0.2)


if __name__ == '__main__':
    main()
