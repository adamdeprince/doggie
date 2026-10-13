#!/usr/bin/env python3
# Runs inside the terminal under test. client.py <kitty> <log> <steps...>
# steps: query (ask for the HDR headroom), sgr (print text at SGR 56:400), image (show an f=64 image with values
# of 3.0), wait:<seconds>, mark:<file> (touch a file so the driver knows where the client is)
import base64, os, struct, subprocess, sys, time, zlib
kitty, log = sys.argv[1], sys.argv[2]

def out(s):
    sys.stdout.write(s); sys.stdout.flush()

with open(log, 'a') as f:
    for step in sys.argv[3:]:
        if step == 'query':
            r = subprocess.run([kitty, '+kitten', 'query_terminal', 'hdr_headroom'], capture_output=True, text=True)
            f.write(f'{time.time():.3f} query: {r.stdout.strip()} {r.stderr.strip()}\n')
        elif step == 'sgr':
            out('\x1b[38;2;255;255;255m\x1b[56:400m' + 'BRIGHT ' * 40 + '\x1b[m\r\n')
            f.write(f'{time.time():.3f} printed text at 400 percent\n')
        elif step == 'image':
            w = h = 64
            data = struct.pack('<4e', 3.0, 3.0, 3.0, 1.0) * (w * h)
            payload = base64.standard_b64encode(zlib.compress(data)).decode()
            first = True
            while payload:
                chunk, payload = payload[:4096], payload[4096:]
                ctl = f'a=T,f=64,s={w},v={h},o=z,q=2,' if first else ''
                out(f'\x1b_G{ctl}m={1 if payload else 0};{chunk}\x1b\\')
                first = False
            out('\r\n')
            f.write(f'{time.time():.3f} showed an image with values of 3.0\n')
        elif step.startswith('wait:'):
            time.sleep(float(step[5:]))
        elif step.startswith('mark:'):
            open(step[5:], 'w').close()
        f.flush()
