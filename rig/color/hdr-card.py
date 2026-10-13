#!/usr/bin/env python3
"""A test card for HDR and wide gamut output, to be looked at on a real display.

Run it inside the terminal under test, with HDR turned on there, for example:

    kitty -o hdr=always python3 rig/color/hdr-card.py

It asks the terminal for its HDR headroom several times, since a display fades
its extended range in, and draws patches whose brightness and color are known,
with a note beside each of what a correct display of it looks like. With
--log FILE what the terminal answered is also written to FILE, and with
--seconds N it leaves by itself. Otherwise press q or Enter to leave.
"""

import argparse
import base64
import binascii
import os
import re
import select
import struct
import sys
import termios
import time
import tty
import zlib

ESC = '\x1b'
ST = ESC + '\\'
LEVELS = (100, 150, 200, 300, 400)


def out(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def read_until(fd: int, done: re.Pattern[bytes], timeout: float) -> bytes:
    buf = b''
    end = time.monotonic() + timeout
    while not done.search(buf):
        left = end - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            break
        buf += os.read(fd, 4096)
    return buf


def ask(fd: int) -> tuple[str, str]:
    'The headroom the terminal reports and its answer to the display query, empty when it gives none'
    name = binascii.hexlify(b'kitty-query-hdr_headroom').decode()
    # the reply to the device attributes request marks the end of the replies, every terminal sends one
    out(f'{ESC}P+q{name}{ST}{ESC}]777;display;v=1:op=query:id=1{ST}{ESC}[c')
    buf = read_until(fd, re.compile(rb'\x1b\[\?[0-9;]*c'), 1.0)
    headroom = display = ''
    m = re.search(rb'\x1bP1\+r[0-9a-fA-F]+=([0-9a-fA-F]*)\x1b\\', buf)
    if m:
        headroom = binascii.unhexlify(m.group(1)).decode('utf-8', 'replace')
    m = re.search(rb'\x1b\]777;display;([^\x07\x1b]*)', buf)
    if m:
        display = m.group(1).decode('utf-8', 'replace')
    return headroom, display


def ramp(peak: float, tone_map: bool, columns: int) -> str:
    'An f=64 image that goes from black on the left to peak times SDR white on the right, in linear light'
    w, h = 640, 16
    row = b''.join(struct.pack('<4e', v, v, v, 1.0) for v in (peak * x / (w - 1) for x in range(w)))
    payload = base64.standard_b64encode(zlib.compress(row * h)).decode()
    ans, first = [], True
    while payload:
        chunk, payload = payload[:4096], payload[4096:]
        ctl = f'a=T,f=64,s={w},v={h},o=z,q=2,C=1,c={columns},r=2,T={1 if tone_map else 0},' if first else ''
        ans.append(f'{ESC}_G{ctl}m={1 if payload else 0};{chunk}{ST}')
        first = False
    return ''.join(ans)


def ticks(peak: float, columns: int) -> str:
    line = [' '] * (columns + 4)
    for v in range(1, int(peak) + 1):
        label = f'{v}x'
        at = max(0, round(columns * v / peak) - len(label))
        line[at : at + len(label)] = label
    return ''.join(line).rstrip()


def card(columns: int) -> list[str]:
    block = ' ' * 8
    white_bg = f'{ESC}[48;2;255;255;255m'
    white_fg = f'{ESC}[38;2;255;255;255m'
    reset = f'{ESC}[m'
    ramp_columns = max(20, min(64, columns - 6))
    lines = [
        '',
        '1  White backgrounds at 100, 150, 200, 300 and 400 percent of SDR white (SGR 57).',
        '   Right: every block is brighter than the one to its left, until the headroom is reached.',
        '   Wrong: all the same, which means no HDR; or the first block differs from ordinary white.',
        '   ' + ' '.join(f'{white_bg}{ESC}[57:{pct}m{block}{reset}' for pct in LEVELS) + f'  {white_bg}{ESC}[38;2;0;0;0m ordinary {reset}',
        '   ' + ' '.join(f'{pct:^8}' for pct in LEVELS),
        '',
        '2  White text at the same levels (SGR 56). Right: it glows more with each step and stays sharp.',
        '   ' + ' '.join(f'{white_fg}{ESC}[56:{pct}m{"silkie":^8}{reset}' for pct in LEVELS),
        '',
        '3  Colors at 100 percent (upper row) and 250 percent (lower row). Right: the lower row is much',
        '   brighter and has the same hue, it must not wash out towards white or shift color.',
    ]
    colors = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 136, 0))
    for pct in (100, 250):
        lines.append('   ' + ' '.join(f'{ESC}[48;2;{r};{g};{b}m{ESC}[57:{pct}m{block}{reset}' for r, g, b in colors) + f'  {pct} percent')
    lines += [
        '',
        '4  An HDR image (f=64): a gray ramp from black to 8 times SDR white, clipped at the headroom.',
        '   Right: smooth, no bands, the same white as ordinary white under the 1x mark, brighter to its',
        '   right, and flat from the headroom on (the 4x mark unless hdr_max_headroom was changed).',
        '   ' + ramp(8.0, False, ramp_columns),
        '',
        '   ' + ticks(8.0, ramp_columns),
        '',
        '5  The same ramp with tone mapping (T=1). Right: the same up to three quarters of the headroom,',
        '   then it keeps getting brighter all the way to the right edge, with no flat end.',
        '   ' + ramp(8.0, True, ramp_columns),
        '',
        '',
        '6  The reddest red of sRGB, of Display P3 and of Rec. 2020 (color space id of the RGB SGR).',
        '   Right, where untagged colors stay sRGB in a wide window (wayland_colorspace): the second is',
        '   a deeper red than the first. Alike in an sRGB window, and with macos_colorspace displayp3,',
        '   which takes untagged colors to be Display P3.',
        '   ' + ' '.join(f'{ESC}[48:2:{cs}:255:0:0m{block}{reset}' for cs in (0, 1, 2)) + '  sRGB, Display P3, Rec. 2020',
        '',
        '7  Everything else in this window, this text included, must look exactly as it does in a',
        '   window without HDR. Compare with one side by side.',
    ]
    return lines


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--log', help='Also write what the terminal answered to this file')
    p.add_argument('--seconds', type=float, default=0, help='Leave after this many seconds instead of waiting for a key')
    args = p.parse_args()
    fd = sys.stdin.fileno()
    columns = os.get_terminal_size().columns
    log = open(args.log, 'w') if args.log else None

    def note(s: str) -> None:
        if log:
            log.write(f'{time.time():.3f} {s}\n')
            log.flush()

    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    try:
        out(f'{ESC}[2J{ESC}[H')
        headroom, display = ask(fd)
        note(f'headroom {headroom or "no answer"}')
        note(f'display {display or "no answer"}')
        out('silkie HDR and wide gamut test card. It needs about 44 lines.\r\n')
        out('\r\n'.join(card(columns)) + '\r\n\r\n')
        out(('Press q or Enter to leave.' if not args.seconds else f'Leaving in {args.seconds:g} seconds.') + '\r\n')
        out(f'{ESC}7')  # the status line is rewritten here as the headroom is asked for again
        seen = [headroom or '?']
        start = time.monotonic()
        while True:
            status = 'The terminal gives no HDR headroom: it does not implement the HDR protocol.'
            if headroom:
                status = f'Headroom the terminal reports, asked every half second: {" ".join(seen[-12:])}'
            if display:
                status += f'   Display: {display.split(":mode=", 1)[-1][2:] if ":mode=" in display else display}'
            out(f'{ESC}8{ESC}[2K{status[: columns - 1]}')
            if args.seconds and time.monotonic() - start >= args.seconds:
                break
            if select.select([fd], [], [], 0.5)[0]:
                key = os.read(fd, 64)
                if key[:1] in (b'q', b'Q', b'\r', b'\n', b'\x03', b'\x04'):
                    break
                continue
            if len(seen) < 40:
                headroom, d = ask(fd)
                display = d or display
                seen.append(headroom or '?')
                note(f'headroom {headroom or "no answer"}')
        note('left')
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out(f'{ESC}[m\r\n')
        if log:
            log.close()


if __name__ == '__main__':
    main()
