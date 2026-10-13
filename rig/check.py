#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Adam DePrince

"""
Compares what the program in the terminal received, the log of client.py,
with what play.py says it should have received, and prints the differences.

Only reports are compared, frames with op=event. For each expected report
the fields it names must have the values it gives; fields it does not name
are not looked at. The pseudo field dt is the difference between the t of a
report and the t of the report before it.
"""

import argparse
import json
import sys


def frames(path: str) -> dict[str, list[dict[str, str]]]:
    ans: dict[str, list[dict[str, str]]] = {}
    with open(path) as f:
        for line in f:
            parts = line.rstrip('\n').split(' ', 2)
            if len(parts) < 3 or parts[1] != 'osc777':
                continue
            selector, _, body = parts[2].partition(';')
            fields = dict(x.partition('=')[::2] for x in body.split(':'))
            if fields.get('op') == 'event':
                fields['_raw'] = body
                ans.setdefault(selector, []).append(fields)
    return ans


def differences(want: dict[str, str], got: dict[str, str], prev_t: int | None) -> list[str]:
    ans = []
    for k, v in want.items():
        if k == 'dt':
            actual = '?' if prev_t is None or 't' not in got else str(int(got['t']) - prev_t)
        else:
            actual = got.get(k, 'absent')
        if actual != v:
            ans.append(f'{k}: expected {v}, got {actual}')
    return ans


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('client_log')
    p.add_argument('expectations')
    p.add_argument('--lookahead', type=int, default=6, help='How many unexpected reports to skip over when looking for an expected one')
    args = p.parse_args()
    got = frames(args.client_log)
    pos = {k: 0 for k in got}
    prev_t: dict[str, int | None] = {}
    ok = bad = 0
    sequence = ''
    with open(args.expectations) as f:
        for line in f:
            e = json.loads(line)
            if 'sequence' in e:
                sequence = e['sequence']
                print(f'== {sequence}')
                continue
            sel, want = e['selector'], e['fields']
            have = got.get(sel, [])
            i = pos.get(sel, 0)
            match = next((j for j in range(i, min(i + args.lookahead, len(have))) if not differences(want, have[j], prev_t.get(sel))), None)
            if match is None:
                bad += 1
                if i < len(have):
                    print(f'MISMATCH {e["note"]}: ' + '; '.join(differences(want, have[i], prev_t.get(sel))))
                    print(f'         got {have[i]["_raw"]}')
                    match = i
                else:
                    print(f'MISSING  {e["note"]}: no more {sel} reports, wanted {want}')
                    continue
            else:
                ok += 1
                for j in range(i, match):
                    print(f'UNEXPECTED before "{e["note"]}": {have[j]["_raw"]}')
            if 't' in have[match]:
                prev_t[sel] = int(have[match]['t'])
            pos[sel] = match + 1
    for sel, have in got.items():
        for fields in have[pos.get(sel, 0) :]:
            print(f'UNEXPECTED at the end: {sel};{fields["_raw"]}')
    print(f'{ok} reports as expected, {bad} not')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
