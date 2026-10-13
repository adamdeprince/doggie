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
import os
import socket
import struct
import sys
import time
from collections.abc import Callable
from typing import IO, Any

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA = 0x110, 0x111, 0x112, 0x113, 0x114
BTN_STYLUS3, BTN_STYLUS, BTN_STYLUS2 = 0x149, 0x14B, 0x14C
SHIFT, CONTROL, ALT, SUPER = 1, 4, 8, 64  # the modifier masks of the default XKB keymap
FINGER = 1  # the source of a ring or strip event, and of a scroll made on a touchpad

# Tablets, tools and pads. A serial and a hardware id stay with the pen, whichever tablet it is used on
DEVICES: dict[str, dict[str, Any]] = {
    # libinput: litest-device-wacom-intuos5-pen.c and -pad.c
    'tablet:intuos5': {'name': 'Wacom Intuos5 touch M Pen', 'vid': 0x56A, 'pid': 0x27, 'bustype': 3, 'paths': ['/dev/input/event90']},
    'tool:pen': {'type': 'pen', 'serial': 578837976, 'hwid': 0x802, 'caps': ['pressure', 'distance', 'tilt']},
    'tool:eraser': {'type': 'eraser', 'serial': 578837976, 'hwid': 0x80A, 'caps': ['pressure', 'distance', 'tilt']},
    # the Art Pen turns, the Airbrush has a wheel, the lens cursor is a puck with buttons and a wheel
    'tool:artpen': {'type': 'pen', 'serial': 0x4100B0A1, 'hwid': 0x804, 'caps': ['pressure', 'distance', 'tilt', 'rotation']},
    'tool:airbrush': {'type': 'airbrush', 'serial': 0x4100B0A2, 'hwid': 0x902, 'caps': ['pressure', 'distance', 'tilt', 'slider']},
    'tool:lens': {'type': 'lens', 'serial': 0x4100B0A3, 'hwid': 0x96, 'caps': ['wheel']},
    'tool:spare': {'type': 'pen', 'serial': 0x4100B0A4, 'hwid': 0x802, 'caps': ['pressure', 'distance', 'tilt']},
    'pad:intuos5': {'buttons': 9, 'paths': ['/dev/input/event91'], 'groups': [{'buttons': list(range(9)), 'rings': 1, 'modes': 4}]},
    # libinput: litest-device-wacom-intuos3-pad.c, the small Intuos3 has four keys and one strip
    'pad:intuos3': {'buttons': 4, 'paths': ['/dev/input/event92'], 'groups': [{'buttons': [0, 1, 2, 3], 'strips': 1, 'modes': 1}]},
    # libinput: litest-device-huion-q620m-dial.c
    'pad:huion': {'buttons': 1, 'paths': ['/dev/input/event93'], 'groups': [{'buttons': [0], 'dials': 1, 'modes': 1}]},
    # libinput: litest-device-wacom-cintiq-pro-16-pen.c, a pen display with a three button pen
    'tablet:cintiq': {'name': 'Wacom Cintiq Pro 16 Pen', 'vid': 0x56A, 'pid': 0x350, 'bustype': 3, 'paths': ['/dev/input/event94']},
    'tool:propen': {'type': 'pen', 'serial': 297797542, 'hwid': 0x823, 'caps': ['pressure', 'distance', 'tilt']},
}
# A pad of no particular make whose controls are in two groups, with one key that is in neither
PAD_TWO: dict[str, Any] = {
    'buttons': 6, 'paths': ['/dev/input/event95'],
    'groups': [{'buttons': [0, 1, 2], 'rings': 1, 'modes': 3}, {'buttons': [4, 5], 'strips': 1, 'modes': 2}],
}
# The tablets get numbers in the order they are plugged in, which is the order they have above
TABLET_NUMBERS = {'intuos5': 1, 'cintiq': 2}
TOOL_NUMBERS = {'pen': 1, 'eraser': 2, 'brush': 3, 'pencil': 4, 'airbrush': 5, 'mouse': 6, 'lens': 7}
VALID_BITS = {'pressure': 1, 'tilt': 2, 'rotation': 4, 'slider': 8, 'distance': 32, 'wheel': 64}


class Died(Exception):
    pass


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
            if 'no client is connected' in ans['error']:
                raise Died()
            raise RuntimeError(f'{cmd}: {ans["error"]}')
        return ans

    def play(self, to: str, *events: list[Any]) -> None:
        self.command(op='play', to=to, events=list(events))

    def expect(self, selector: str, note: str, **fields: Any) -> None:
        "A report the program should now get: the fields named must have these values, others are not looked at"
        if self.expectations:
            self.mark(selector=selector, note=note, fields={k: str(v) for k, v in fields.items()})

    def mark(self, **what: Any) -> None:
        if self.expectations:
            self.expectations.write(json.dumps({**what, 'at': time.monotonic()}) + '\n')

    def alive(self) -> dict[str, Any]:
        "What the proxy knows of the terminal, which must still be connected"
        info = self.command(op='info')
        if not info.get('connected'):
            raise Died()
        return info

    def wait_for_window(self, timeout: float = 20) -> dict[str, Any]:
        end = time.monotonic() + timeout
        seen = 0.0
        while time.monotonic() < end:
            info = self.command(op='info')
            if info.get('connected') and info['surface']:
                seen = seen or time.monotonic()
                # a window that never draws is never given a size, the output's will do
                if info['size'][0] or time.monotonic() - seen > 2:
                    self.width, self.height = info['size'] if info['size'][0] else (1280, 800)
                    return info
            time.sleep(0.1)
        raise TimeoutError('the terminal did not open a window')


def px(v: float) -> int:
    return round(v * 256)


def point(rig: Rig, x: float, y: float) -> None:
    "Moves the pointer, as a hand on the mouse or touchpad does before it scrolls or pinches"
    rig.play('pointer', ['motion', '$time', x, y], ['frame'])
    time.sleep(0.02)


def setup(rig: Rig) -> None:
    "The tablets and tools, and the keyboard and pointer focus a compositor gives the only window"
    # Pads are plugged in by the sequence that uses them, so that a terminal
    # that cannot cope with a pad still gets through the others
    for device, d in DEVICES.items():
        if not device.startswith('pad:'):
            rig.command(op='add', device=device, **d)
    info = rig.wait_for_window()
    if 'wl_keyboard' in info['interfaces']:
        rig.play('keyboard', ['enter', '$serial', '$surface', []], ['modifiers', '$serial', 0, 0, 0, 0])
    if 'wl_pointer' in info['interfaces']:
        rig.play('pointer', ['enter', '$serial', '$surface', rig.width / 2, rig.height / 2], ['frame'])
    time.sleep(0.2)


# Tools {{{
def tool_number(tool: str) -> int:
    return TOOL_NUMBERS[DEVICES[f'tool:{tool}']['type']]


def tool_valid(tool: str) -> int:
    return sum(VALID_BITS[c] for c in DEVICES[f'tool:{tool}']['caps'])


def tool_axes(
    tool: str, x: float, y: float, pressure: int = 0, distance: int = 0, tilt: tuple[float, float] = (0, 0), rotation: float = 0, slider: int = 0
) -> tuple[list[list[Any]], dict[str, Any]]:
    "The events for one sample of a tool, with the axes it has, and the fields of the report they make"
    caps = DEVICES[f'tool:{tool}']['caps']
    events: list[list[Any]] = [['motion', x, y]]
    fields: dict[str, Any] = {'kind': 1, 'contact': 0, 'x': px(x), 'y': px(y), 'tool': tool_number(tool), 'valid': tool_valid(tool)}
    if 'pressure' in caps:
        events.append(['pressure', pressure])
        fields['p'] = pressure
    if 'distance' in caps:
        events.append(['distance', distance])
        fields['dist'] = distance
    if 'tilt' in caps:
        events.append(['tilt', *tilt])
        fields['tx'], fields['ty'] = round(tilt[0] * 100), round(tilt[1] * 100)
    if 'rotation' in caps:
        events.append(['rotation', rotation])
        fields['twist'] = round(rotation * 100) % 36000
    if 'slider' in caps:
        events.append(['slider', slider])
        fields['tangent'] = slider
    return events, fields


def tool_stroke(rig: Rig, tool: str = 'pen', tablet: str = 'intuos5') -> None:
    "A tool comes into proximity, hovers, draws a diagonal with every axis changing, and leaves"
    t = f'tool:{tool}'
    x, y = 100.0, 100.0

    def sample(note: str, phase: int, buttons: int, *first: list[Any], **axes: Any) -> None:
        events, fields = tool_axes(tool, x, y, **axes)
        rig.play(t, *first, *events, ['frame', '$time'])
        rig.expect('tablet-pointer', f'{tool}: {note}', phase=phase, buttons=buttons, **fields)
        time.sleep(0.008)

    rig.expect('tablet-pointer:device', f'{tool}: is described', kind=1, tool=tool_number(tool), axes=tool_valid(tool), tablet=TABLET_NUMBERS[tablet])
    sample('enters proximity', 0, 0, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], distance=40000)
    for i in range(3):
        x, y = x + 10, y + 5
        sample('hovers', 0, 0, distance=30000 - 10000 * i)
    sample('tip down', 1, 1, ['down', '$serial'], pressure=5000, tilt=(10, -5), rotation=350, slider=-60000)
    for i in range(1, 11):
        x, y = x + 20.25, y + 12.5
        sample(f'stroke point {i}', 2, 1, pressure=5000 + 6000 * i, tilt=(10 + 4 * i, -5 - 3 * i), rotation=(350 + 7.5 * i) % 360, slider=-60000 + 12000 * i)
    sample('tip up', 3, 0, ['up'], tilt=(50, -35), rotation=65, slider=60000)
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

    step('enters proximity', 0, 0, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], *tool_axes(tool, x, y, distance=20000)[0])
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


def puck(rig: Rig, tool: str = 'lens', tablet: str = 'intuos5') -> None:
    "A lens cursor: no tip, its left button draws, and it has a wheel and four more buttons"
    t = f'tool:{tool}'
    x, y = 500.0, 300.0
    base = {'kind': 1, 'tool': tool_number(tool), 'valid': tool_valid(tool)}

    def step(note: str, phase: int, buttons: int, *events: list[Any], wheel: int = 0, clicks: int = 0) -> None:
        rig.play(t, *events, ['frame', '$time'])
        rig.expect('tablet-pointer', f'{tool}: {note}', phase=phase, x=px(x), y=px(y), buttons=buttons, wheel=wheel, wclicks=clicks, **base)
        time.sleep(0.02)

    step('enters proximity', 0, 0, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], ['motion', x, y])
    step('right button while hovering', 0, 2, ['button', '$serial', BTN_RIGHT, 1])
    step('right button released', 0, 0, ['button', '$serial', BTN_RIGHT, 0])
    step('left button down', 1, 1, ['button', '$serial', BTN_LEFT, 1])
    x += 16
    step('moves with the left button', 2, 1, ['motion', x, y])
    step('wheel, one click of 15 degrees', 2, 1, ['wheel', 15, 1], wheel=1500, clicks=1)
    x += 16
    step('moves on, the wheel is at rest again', 2, 1, ['motion', x, y])
    step('wheel back two clicks', 2, 1, ['wheel', -30, -2], wheel=-3000, clicks=-2)
    step('middle button', 2, 1 | 4, ['button', '$serial', BTN_MIDDLE, 1])
    step('back button', 2, 1 | 4 | 8, ['button', '$serial', BTN_SIDE, 1])
    step('forward button', 2, 1 | 4 | 8 | 16, ['button', '$serial', BTN_EXTRA, 1])
    step('the three released', 2, 1, ['button', '$serial', BTN_MIDDLE, 0], ['button', '$serial', BTN_SIDE, 0], ['button', '$serial', BTN_EXTRA, 0])
    step('left button up', 3, 0, ['button', '$serial', BTN_LEFT, 0])
    rig.play(t, ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', f'{tool}: leaves proximity', kind=1, phase=5)
    time.sleep(0.1)


def tool_burst(rig: Rig, tool: str = 'pen', tablet: str = 'intuos5') -> None:
    "Ten samples 5 ms apart that all arrive at once, as after a stall: their times must stay 5 ms apart"
    t = f'tool:{tool}'
    rig.play(t, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], *tool_axes(tool, 400, 400)[0], ['frame', '$time-60'])
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


def tool_abort(rig: Rig, tool: str = 'pen', tablet: str = 'intuos5') -> None:
    "Strokes that do not end the usual way: a pen flicked out of range, and a tablet unplugged under a pen"
    t = f'tool:{tool}'
    events, fields = tool_axes(tool, 600, 500, pressure=30000)
    rig.play(t, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], ['down', '$serial'], *events, ['frame', '$time'])
    rig.expect('tablet-pointer', 'flick: tip down as the pen arrives', phase=1, buttons=1, **fields)
    time.sleep(0.02)
    # wlroots puts the tip going up and the tool leaving in one frame when libinput reports them together
    rig.play(t, ['up'], ['pressure', 0], ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', 'flick: the stroke ends, the tip did come up', kind=1, phase=3, buttons=0)
    rig.expect('tablet-pointer', 'flick: leaves proximity', kind=1, phase=5)
    time.sleep(0.05)

    spare = 'tool:spare'
    events, fields = tool_axes('spare', 620, 500, pressure=30000)
    rig.play(spare, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], ['down', '$serial'], *events, ['frame', '$time'])
    rig.expect('tablet-pointer', 'unplug: another pen draws', phase=1, buttons=1, **fields)
    time.sleep(0.02)
    rig.play(spare, ['removed'])
    rig.expect('tablet-pointer', 'unplug: its stroke is cancelled when the tablet goes away', kind=1, phase=4, buttons=0, p=0)
    time.sleep(0.1)


def tool_mods(rig: Rig, tool: str = 'pen', tablet: str = 'intuos5') -> None:
    "The keyboard modifiers held while a pen moves"
    t = f'tool:{tool}'
    rig.play(t, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], *tool_axes(tool, 200, 600, distance=9000)[0], ['frame', '$time'])
    rig.expect('tablet-pointer', 'mods: none held', kind=1, phase=0, mods=0)
    for held, reported, names in ((SHIFT, 1, 'shift'), (SHIFT | CONTROL, 5, 'shift and control'), (ALT | SUPER, 10, 'alt and super'), (0, 0, 'none again')):
        rig.play('keyboard', ['modifiers', '$serial', held, 0, 0, 0])
        time.sleep(0.02)
        rig.play(t, ['motion', 210, 600], ['frame', '$time'])
        rig.expect('tablet-pointer', f'mods: {names}', kind=1, phase=0, mods=reported)
        time.sleep(0.02)
    rig.play(t, ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', 'mods: leaves proximity', kind=1, phase=5)
    time.sleep(0.1)


def tool_pair(rig: Rig, tablet: str = 'intuos5') -> None:
    "A pen and a puck on the tablet at the same time, each drawing its own stroke"
    pen, lens = 'tool:pen', 'tool:lens'
    one = {'kind': 1, 'tool': tool_number('pen')}
    two = {'kind': 1, 'tool': tool_number('lens')}
    rig.play(pen, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], *tool_axes('pen', 100, 700, distance=9000)[0], ['frame', '$time'])
    rig.expect('tablet-pointer', 'pair: the pen arrives', phase=0, x=px(100), y=px(700), **one)
    rig.play(lens, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], ['motion', 900, 700], ['frame', '$time'])
    rig.expect('tablet-pointer', 'pair: the puck arrives', phase=0, x=px(900), y=px(700), **two)
    time.sleep(0.02)
    rig.play(pen, ['down', '$serial'], ['pressure', 30000], ['distance', 0], ['frame', '$time'])
    rig.expect('tablet-pointer', 'pair: the pen touches', phase=1, x=px(100), buttons=1, **one)
    rig.play(lens, ['button', '$serial', BTN_LEFT, 1], ['frame', '$time'])
    rig.expect('tablet-pointer', 'pair: the puck presses', phase=1, x=px(900), buttons=1, **two)
    for i in range(1, 4):
        time.sleep(0.01)
        rig.play(pen, ['motion', 100 + 10 * i, 700], ['frame', '$time'])
        rig.expect('tablet-pointer', f'pair: the pen moves {i}', phase=2, x=px(100 + 10 * i), buttons=1, p=30000, **one)
        rig.play(lens, ['motion', 900 - 10 * i, 700], ['frame', '$time'])
        rig.expect('tablet-pointer', f'pair: the puck moves {i}', phase=2, x=px(900 - 10 * i), buttons=1, **two)
    rig.play(pen, ['up'], ['pressure', 0], ['frame', '$time'])
    rig.expect('tablet-pointer', 'pair: the pen lifts, the puck is still down', phase=3, x=px(130), **one)
    rig.play(lens, ['motion', 860, 700], ['frame', '$time'])
    rig.expect('tablet-pointer', 'pair: the puck goes on', phase=2, x=px(860), buttons=1, **two)
    rig.play(lens, ['button', '$serial', BTN_LEFT, 0], ['frame', '$time'])
    rig.expect('tablet-pointer', 'pair: the puck releases', phase=3, **two)
    rig.play(pen, ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', 'pair: the pen leaves', phase=5, **one)
    rig.play(lens, ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', 'pair: the puck leaves', phase=5, **two)
    time.sleep(0.1)


def tool_outside(rig: Rig, tool: str = 'pen', tablet: str = 'intuos5') -> None:
    "A stroke that starts in the window and is dragged out of it on two sides: it stays captured, coordinates are not clamped"
    t = f'tool:{tool}'
    rig.play(
        t, ['proximity_in', '$serial', f'tablet:{tablet}', '$surface'], ['down', '$serial'], *tool_axes(tool, 20, 20, pressure=20000)[0], ['frame', '$time']
    )
    rig.expect('tablet-pointer', 'outside: tip down near the corner', kind=1, phase=1, x=px(20), y=px(20))
    for x, y, where in ((-30.5, -12.25, 'above and left of the window'), (rig.width + 40, 50, 'right of the window'), (60, rig.height + 25, 'below it')):
        time.sleep(0.01)
        rig.play(t, ['motion', x, y], ['frame', '$time'])
        rig.expect('tablet-pointer', f'outside: {where}', kind=1, phase=2, x=px(x), y=px(y), buttons=1)
    rig.play(t, ['up'], ['pressure', 0], ['frame', '$time'])
    rig.expect('tablet-pointer', 'outside: tip up out there', kind=1, phase=3, x=px(60), y=px(rig.height + 25))
    rig.play(t, ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', 'outside: leaves proximity', kind=1, phase=5)
    time.sleep(0.1)


# }}}


# Pads {{{
def pads(rig: Rig) -> None:
    """Three pads are plugged in: keys and a ring with four modes, keys and a strip, a key and a dial.
    What is expected is what the tablet pointer protocol says of pads: each pad is described when it comes
    to the window, and its reports are kind=3 with button and state, ring and angle, strip and pos, dial and
    delta, group and mode"""
    for device, d in DEVICES.items():
        if device.startswith('pad:'):
            rig.command(op='add', device=device, **d)
    time.sleep(0.2)
    named = rig.alive()['named']  # a terminal that drops its connection over a pad is found out here

    def pad(name: str, note: str, *events: list[Any], to: str = '', **fields: Any) -> None:
        rig.play(to or f'pad:{name}', *events)
        if fields:
            rig.expect('tablet-pointer', f'{name}: {note}', kind=3, **fields)
        time.sleep(0.02)

    def enters(name: str, mode: int = 0, **description: Any) -> None:
        "The pad gets the focus, and the compositor says what mode its group is in, as wlroots and Mutter do after every enter"
        rig.play(f'pad:{name}', ['enter', '$serial', 'tablet:intuos5', '$surface'])
        rig.expect('tablet-pointer:device', f'{name}: is described', kind=3, groups=1, tablet=TABLET_NUMBERS['intuos5'], **description)
        time.sleep(0.02)
        pad(name, f'its group is in mode {mode}', ['mode_switch', '$time', '$serial', mode], to=f'group:{name}:0', group=0, mode=mode)

    enters('intuos5', mode=2, buttons=9, rings=1, strips=0, dials=0, modes=4, bgroups='0,0,0,0,0,0,0,0,0', rgroups=0)
    for b in range(9):
        pad('intuos5', f'key {b} down', ['button', '$time', b, 1], button=b, state=1)
        pad('intuos5', f'key {b} up', ['button', '$time', b, 0], button=b, state=0)
    ring = 'ring:intuos5:0:0'
    for angle in (0, 45.5, 90, 180, 355):
        pad('intuos5', f'ring at {angle} degrees', ['source', FINGER], ['angle', angle], ['frame', '$time'], to=ring, ring=0, angle=round(angle * 100), src=1)
    pad('intuos5', 'finger off the ring', ['source', FINGER], ['stop'], ['frame', '$time'], to=ring, ring=0, stop=1, src=1)
    pad('intuos5', 'mode 2 of 4', ['mode_switch', '$time', '$serial', 1], to='group:intuos5:0', group=0, mode=1)
    pad('intuos5', 'key 0 in the new mode', ['button', '$time', 0, 1], ['button', '$time', 0, 0], button=0, state=1)
    rig.expect('tablet-pointer', 'intuos5: key 0 up', kind=3, button=0, state=0)
    # keys that are down when the pad goes elsewhere are let go, and their real releases are then not reported
    pad('intuos5', 'key 3 held', ['button', '$time', 3, 1], button=3, state=1)
    pad('intuos5', 'key 5 held', ['button', '$time', 5, 1], button=5, state=1)
    rig.play('pad:intuos5', ['leave', '$serial', '$surface'])
    rig.expect('tablet-pointer', 'intuos5: key 3 let go as the pad leaves', kind=3, button=3, state=0)
    rig.expect('tablet-pointer', 'intuos5: key 5 let go as the pad leaves', kind=3, button=5, state=0)
    time.sleep(0.02)
    rig.play('pad:intuos5', ['button', '$time', 3, 0], ['button', '$time', 5, 0])
    time.sleep(0.02)

    strip = 'strip:intuos3:0:0'
    enters('intuos3', buttons=4, rings=0, strips=1, dials=0, modes=1, bgroups='0,0,0,0', sgroups=0)
    for pos in (0, 16384, 32768, 65535):
        pad('intuos3', f'strip at {pos}', ['source', FINGER], ['position', pos], ['frame', '$time'], to=strip, strip=0, pos=pos, src=1)
    pad('intuos3', 'finger off the strip', ['source', FINGER], ['stop'], ['frame', '$time'], to=strip, strip=0, stop=1, src=1)
    pad('intuos3', 'leaves', ['leave', '$serial', '$surface'])

    dial = 'dial:huion:0:0'
    has_dial = dial in named  # version 1 of tablet-v2 has no dials, the pad is then just its key
    enters('huion', buttons=1, rings=0, strips=0, dials=1 if has_dial else 0, modes=1, bgroups=0, **({'dgroups': 0} if has_dial else {}))
    for delta, what in ((120, 'one click'), (-240, 'two clicks back'), (30, 'a quarter of a click')):
        if has_dial:
            pad('huion', f'dial {what}', ['delta', delta], ['frame', '$time'], to=dial, dial=0, delta=delta)
    if has_dial:
        pad('huion', 'dial moved twice before its frame', ['delta', 120], ['delta', 60], ['frame', '$time'], to=dial, dial=0, delta=180)
    pad('huion', 'key down', ['button', '$time', 0, 1], button=0, state=1)
    pad('huion', 'key up', ['button', '$time', 0, 0], button=0, state=0)
    pad('huion', 'leaves', ['leave', '$serial', '$surface'])
    time.sleep(0.1)


def pad_groups(rig: Rig) -> None:
    """A pad of the second tablet whose controls are in two groups: three keys and a ring in one, two keys and a
    strip in the other, and a key in neither, as one that the compositor keeps for itself is. The pad says which
    tablet it belongs to and which group each control is in, and when the compositor takes a key out of its
    group while the pad is in use, the pad is described again"""
    rig.command(op='add', device='pad:two', **PAD_TWO)
    time.sleep(0.2)
    rig.alive()
    described = dict(kind=3, tablet=TABLET_NUMBERS['cintiq'], buttons=6, rings=1, strips=1, dials=0, groups=2, modes='3,2', rgroups=0, sgroups=1)

    def pad(note: str, *events: list[Any], to: str = 'pad:two', **fields: Any) -> None:
        rig.play(to, *events)
        rig.expect('tablet-pointer', f'two: {note}', kind=3, **fields)
        time.sleep(0.02)

    rig.play('pad:two', ['enter', '$serial', 'tablet:cintiq', '$surface'])
    rig.expect('tablet-pointer:device', 'two: is described', bgroups='0,0,0,-,1,1', **described)
    time.sleep(0.02)
    pad('the first group is in mode 2', ['mode_switch', '$time', '$serial', 2], to='group:two:0', group=0, mode=2)
    pad('the second group is in mode 1', ['mode_switch', '$time', '$serial', 1], to='group:two:1', group=1, mode=1)
    pad('a key of the second group', ['button', '$time', 4, 1], ['button', '$time', 4, 0], button=4, state=1)
    rig.expect('tablet-pointer', 'two: that key up', kind=3, button=4, state=0)
    pad('the ring of the first group', ['source', FINGER], ['angle', 90], ['frame', '$time'], to='ring:two:0:0', ring=0, angle=9000, src=1)
    pad('the strip of the second group', ['source', FINGER], ['position', 32768], ['frame', '$time'], to='strip:two:1:0', strip=0, pos=32768, src=1)
    # the compositor takes key 2 for itself, and says so by listing the keys of the group again
    rig.play('group:two:0', ['buttons', struct.pack('=2I', 0, 1).hex()])
    rig.expect('tablet-pointer:device', 'two: is described again when a key leaves its group', bgroups='0,0,-,-,1,1', mode='2,1', **described)
    time.sleep(0.02)
    pad('a key of the first group afterwards', ['button', '$time', 0, 1], ['button', '$time', 0, 0], button=0, state=1)
    rig.expect('tablet-pointer', 'two: that key up', kind=3, button=0, state=0)
    rig.play('pad:two', ['leave', '$serial', '$surface'])
    time.sleep(0.1)


# }}}


# Fingers, gestures and scrolling {{{
def touch(rig: Rig) -> None:
    "A touchscreen: one finger draws, three fingers land, move and lift together, two fingers are cancelled"

    def frame(note: str, *events: list[Any], expect: list[dict[str, Any]]) -> None:
        rig.play('touch', *events, ['frame'])
        for f in expect:
            rig.expect('tablet-pointer', f'touch: {note}', kind=2, tool=0, **f)
        rig.expect('tablet-pointer', f'touch: {note}, end of the group', kind=2, phase=6)
        time.sleep(0.012)

    frame(
        'one finger down', ['down', '$serial', '$time', '$surface', 0, 200, 300], expect=[{'phase': 1, 'contact': 0, 'x': px(200), 'y': px(300), 'buttons': 1}]
    )
    for i in range(1, 5):
        frame('it moves', ['motion', '$time', 0, 200 + 12.5 * i, 300], expect=[{'phase': 2, 'contact': 0, 'x': px(200 + 12.5 * i), 'y': px(300)}])
    frame('it lifts', ['up', '$serial', '$time', 0], expect=[{'phase': 3, 'contact': 0, 'buttons': 0}])
    time.sleep(0.05)

    downs = [['down', '$serial', '$time', '$surface', i, 300 + 100 * i, 400] for i in range(3)]
    shapes = [['shape', 0, 20, 12], ['orientation', 0, 45]]
    frame(
        'three fingers down, the first with a shape',
        *downs,
        *shapes,
        expect=[
            {'phase': 1, 'contact': 0, 'x': px(300), 'buttons': 1, 'valid': 128, 'major': px(20), 'minor': px(12), 'angle': 4500},
            {'phase': 1, 'contact': 1, 'x': px(400), 'buttons': 1},
            {'phase': 1, 'contact': 2, 'x': px(500), 'buttons': 1},
        ],
    )
    for step in range(1, 4):
        frame(
            'all three move',
            *[['motion', '$time', i, 300 + 100 * i, 400 + 10 * step] for i in range(3)],
            expect=[{'phase': 2, 'contact': i, 'y': px(400 + 10 * step)} for i in range(3)],
        )
    frame('only the second moves', ['motion', '$time', 1, 410, 440], expect=[{'phase': 2, 'contact': 1, 'x': px(410), 'y': px(440)}])
    frame('all three lift', *[['up', '$serial', '$time', i] for i in range(3)], expect=[{'phase': 3, 'contact': i} for i in range(3)])
    time.sleep(0.05)

    frame(
        'two fingers down',
        ['down', '$serial', '$time', '$surface', 0, 600, 200],
        ['down', '$serial', '$time', '$surface', 1, 700, 200],
        expect=[{'phase': 1, 'contact': 0}, {'phase': 1, 'contact': 1}],
    )
    rig.play('touch', ['cancel'])
    rig.expect('tablet-pointer', 'touch: the compositor takes the fingers over, first finger', kind=2, phase=4, contact=0, buttons=0)
    rig.expect('tablet-pointer', 'touch: the compositor takes the fingers over, second finger', kind=2, phase=4, contact=1, buttons=0)
    rig.expect('tablet-pointer', 'touch: end of the cancelled group', kind=2, phase=6)
    time.sleep(0.05)

    # a tap so short that the finger lands and lifts between two frames: the program must still see it land first
    rig.play('touch', ['down', '$serial', '$time', '$surface', 7, 800, 600], ['up', '$serial', '$time', 7], ['frame'])
    rig.expect('tablet-pointer', 'touch: a tap within one frame lands', kind=2, phase=1, contact=7, x=px(800), y=px(600), buttons=1)
    rig.expect('tablet-pointer', 'touch: end of that group', kind=2, phase=6)
    rig.expect('tablet-pointer', 'touch: and lifts', kind=2, phase=3, contact=7, buttons=0)
    rig.expect('tablet-pointer', 'touch: end of that group', kind=2, phase=6)
    time.sleep(0.1)


def gestures(rig: Rig) -> None:
    "The gestures of a touchpad: a pinch that also turns, a swipe to the left, and a hold"
    at = {'x': px(rig.width / 2), 'y': px(rig.height / 2)}
    point(rig, rig.width / 2, rig.height / 2)
    rig.play('pinch', ['begin', '$serial', '$time', '$surface', 2])
    rig.expect('gesture', 'pinch begins', kind=1, phase=1, scale=0, total=1000, fingers=2, **at)
    rig.expect('gesture', 'and the rotation that goes with it', kind=2, phase=1, angle=0, total=0, fingers=2, **at)
    total = 0.0
    for scale, turn in ((1.125, 5), (1.25, 5), (1.125, -2.5)):  # scales a 24.8 fixed point number holds exactly
        time.sleep(0.012)
        rig.play('pinch', ['update', '$time', 0, 0, scale, turn])
        total += turn
        rig.expect('gesture', f'pinch to {scale}', kind=1, phase=2, total=round(scale * 1000), fingers=2)
        rig.expect('gesture', f'turned by {turn} degrees', kind=2, phase=2, angle=round(turn * 100), total=round(total * 100))
    rig.play('pinch', ['end', '$serial', '$time', 0])
    rig.expect('gesture', 'pinch ends', kind=1, phase=3)
    rig.expect('gesture', 'rotation ends', kind=2, phase=3)
    time.sleep(0.05)

    rig.play('swipe', ['begin', '$serial', '$time', '$surface', 3])
    for _ in range(5):
        time.sleep(0.012)
        rig.play('swipe', ['update', '$time', -20, 2])
    rig.play('swipe', ['end', '$serial', '$time', 0])
    rig.expect('gesture', 'a three finger swipe to the left begins', kind=3, phase=1, dx=-1, dy=0, fingers=3)
    rig.expect('gesture', 'and ends', kind=3, phase=3, dx=-1, dy=0, fingers=3)
    time.sleep(0.05)

    rig.play('pinch', ['begin', '$serial', '$time', '$surface', 2])
    rig.expect('gesture', 'a second pinch begins', kind=1, phase=1)
    rig.expect('gesture', 'with its rotation', kind=2, phase=1)
    rig.play('pinch', ['update', '$time', 0, 0, 0.75, 0])
    rig.expect('gesture', 'pinched in to three quarters', kind=1, phase=2, scale=-250, total=750)
    rig.play('pinch', ['end', '$serial', '$time', 1])
    rig.expect('gesture', 'the compositor takes the pinch over', kind=1, phase=4)
    rig.expect('gesture', 'and the rotation', kind=2, phase=4)
    time.sleep(0.05)

    for fingers, dx, dy, where in ((4, 30, -3, 'right'), (3, 2, -25, 'up'), (3, -4, 40, 'down')):
        rig.play(
            'swipe',
            ['begin', '$serial', '$time', '$surface', fingers],
            ['update', '$time', dx, dy],
            ['update', '$time', dx, dy],
            ['end', '$serial', '$time', 0],
        )
        want = {'dx': (dx > 0) - (dx < 0) if abs(dx) > abs(dy) else 0, 'dy': (dy > 0) - (dy < 0) if abs(dy) > abs(dx) else 0}
        rig.expect('gesture', f'a swipe {where} begins', kind=3, phase=1, fingers=fingers, **want)
        rig.expect('gesture', 'and ends', kind=3, phase=3, **want)
        time.sleep(0.05)
    rig.play('swipe', ['begin', '$serial', '$time', '$surface', 3], ['update', '$time', -30, 0], ['end', '$serial', '$time', 1])
    time.sleep(0.05)  # a swipe the compositor took over is not a swipe

    # fingers that come to rest and lift again, then fingers that rest and start to move, which cancels the hold
    rig.play('hold', ['begin', '$serial', '$time', '$surface', 2])
    rig.expect('gesture', 'two fingers rest on the touchpad', kind=5, phase=1, fingers=2, **at)
    time.sleep(0.05)
    rig.play('hold', ['end', '$serial', '$time', 0])
    rig.expect('gesture', 'and lift', kind=5, phase=3, fingers=2)
    time.sleep(0.05)
    rig.play('hold', ['begin', '$serial', '$time', '$surface', 3])
    rig.expect('gesture', 'three fingers rest', kind=5, phase=1, fingers=3)
    rig.play('hold', ['end', '$serial', '$time', 1])
    rig.expect('gesture', 'and begin to move', kind=5, phase=4)
    time.sleep(0.1)


def scroll(rig: Rig) -> None:
    "Two fingers scroll down on a touchpad and lift, then a wheel turns one notch each way"
    at = {'x': round(rig.width / 2), 'y': round(rig.height / 2)}
    point(rig, rig.width / 2, rig.height / 2)
    for i in range(6):
        rig.play('pointer', ['axis_source', FINGER], ['axis', '$time', 0, 4.5], ['frame'])
        rig.expect('scroll', f'finger scroll {i}, four and a half pixels down', dx=0, dy=450, src=1, phase=2 if i else 1, **at)
        time.sleep(0.012)
    rig.play('pointer', ['axis_source', FINGER], ['axis_stop', '$time', 0], ['frame'])
    rig.expect('scroll', 'the fingers lift', dx=0, dy=0, src=1, phase=3)
    rig.expect('scroll', 'and the terminal starts to coast', src=1, phase=4)
    time.sleep(1.0)  # the terminal's own momentum runs out
    rig.mark(skip='scroll')

    # the units of one notch are 120 from version 8 of wl_pointer, and one discrete step before it
    for value, note in ((15, 'down'), (-15, 'up')):
        notch = 1 if value > 0 else -1
        rig.play('pointer', ['axis_source', 0], ['axis_value120', 0, 120 * notch], ['axis', '$time', 0, value], ['frame'])
        rig.expect('scroll', f'a wheel notch {note}', dx=0, src=0, phase=0, **at)
        time.sleep(0.3)
    time.sleep(0.2)


def handover(rig: Rig) -> None:
    """The pointer rests in the middle of the window while a pen draws, is dragged out over the edge and leaves
    there. Then, without the pointer moving, two fingers pinch and scroll on the touchpad. A compositor that gives
    tablets a cursor of their own, as GNOME does, sends just this, and the pinch and the scroll belong where the
    pointer is, not where the pen was last"""
    middle = rig.width / 2, rig.height / 2
    point(rig, *middle)
    t = 'tool:pen'
    rig.play(
        t, ['proximity_in', '$serial', 'tablet:intuos5', '$surface'], ['down', '$serial'], *tool_axes('pen', 200, 150, pressure=20000)[0], ['frame', '$time']
    )
    rig.expect('tablet-pointer', 'handover: the pen draws in the corner', kind=1, phase=1, x=px(200), y=px(150))
    time.sleep(0.02)
    rig.play(t, ['motion', 200, -40], ['frame', '$time'])
    rig.expect('tablet-pointer', 'handover: is dragged out over the top edge', kind=1, phase=2, y=px(-40))
    rig.play(t, ['up'], ['pressure', 0], ['frame', '$time'])
    rig.expect('tablet-pointer', 'handover: lifts there', kind=1, phase=3)
    rig.play(t, ['proximity_out'], ['frame', '$time'])
    rig.expect('tablet-pointer', 'handover: and leaves proximity out there', kind=1, phase=5)
    time.sleep(0.1)
    rig.play('pinch', ['begin', '$serial', '$time', '$surface', 2], ['update', '$time', 0, 0, 1.25, 0], ['end', '$serial', '$time', 0])
    for phase, note in ((1, 'begins'), (2, 'grows'), (3, 'ends')):
        rig.expect('gesture', f'handover: a pinch {note} where the pointer is', kind=1, phase=phase, x=px(middle[0]), y=px(middle[1]))
    time.sleep(0.05)
    rig.play('pointer', ['axis_source', FINGER], ['axis', '$time', 0, 4.5], ['frame'])
    rig.expect('scroll', 'handover: a scroll where the pointer is', dy=450, x=round(middle[0]), y=round(middle[1]))
    rig.play('pointer', ['axis_source', FINGER], ['axis_stop', '$time', 0], ['frame'])
    time.sleep(1.0)
    rig.mark(skip='scroll')
    rig.mark(skip='gesture')  # the rotation reports that go with the pinch


# }}}


SEQUENCES: dict[str, Callable[[Rig], None]] = {
    'pen': lambda rig: tool_stroke(rig, 'pen'),
    'eraser': lambda rig: tool_stroke(rig, 'eraser'),
    'artpen': lambda rig: tool_stroke(rig, 'artpen'),
    'airbrush': lambda rig: tool_stroke(rig, 'airbrush'),
    'buttons': tool_buttons,
    'puck': puck,
    'burst': tool_burst,
    'abort': tool_abort,
    'mods': tool_mods,
    'pair': tool_pair,
    'outside': tool_outside,
    'touch': touch,
    'gestures': gestures,
    'scroll': scroll,
    'handover': handover,
    'pads': pads,
    'padgroups': pad_groups,
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--control', required=True, help='The control socket of wlproxy.py')
    p.add_argument('--expect', help='Where to write what the program in the terminal should receive')
    p.add_argument('--wait', help='A file that appears when the program in the terminal is ready')
    p.add_argument('sequences', nargs='*', help=f'What to play, all by default: {", ".join(SEQUENCES)}')
    args = p.parse_args()
    with open(args.expect or os.devnull, 'w', buffering=1) as f:
        rig = Rig(args.control, f)
        setup(rig)
        end = time.monotonic() + 20
        while args.wait and not os.path.exists(args.wait):
            if time.monotonic() > end:
                raise TimeoutError('the program in the terminal did not get ready')
            time.sleep(0.05)
        for name in args.sequences or SEQUENCES:
            rig.mark(sequence=name)
            try:
                SEQUENCES[name](rig)
                rig.alive()
            except Died:
                rig.mark(died=name)
                print(f'the terminal dropped its connection during {name}', file=sys.stderr)
                sys.exit(3)
            time.sleep(0.2)


if __name__ == '__main__':
    main()
