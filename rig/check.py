#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Adam DePrince

"""
Compares what the program in the terminal received, the log of client.py,
with what play.py says it should have received, and prints the differences.

Reports are compared, frames with op=event. For each expected report the
fields it names must have the values it gives, where a value of "absent"
means that the field must not be there; fields it does not name are not
looked at. The pseudo field dt is the difference between the t of a
report and the t of the report before it from the same selector.

The descriptions of devices, frames with op=device, are compared in the same
way under the selector with ":device" added, but only in a sequence that
expects some: a pen is described in every sequence it is played in, and most
of them are not about that.

Within each sequence the expected and the received reports are lined up so
that as many as possible agree, so one report too many or too few shows up
as that and not as a mismatch in everything after it.
"""

import argparse
import json
import sys
from typing import Any

Report = dict[str, str]


def reports(path: str) -> list[tuple[float, str, Report]]:
    ans: list[tuple[float, str, Report]] = []
    last_t: dict[str, int] = {}
    with open(path) as f:
        for line in f:
            parts = line.rstrip('\n').split(' ', 2)
            if len(parts) < 3 or parts[1] != 'osc777':
                continue
            selector, _, body = parts[2].partition(';')
            fields = dict(x.partition('=')[::2] for x in body.split(':'))
            if fields.get('op') == 'device':
                selector += ':device'
            elif fields.get('op') != 'event':
                continue
            fields['_raw'] = body
            if fields.get('t', '').isdigit():
                t = int(fields['t'])
                if selector in last_t:
                    fields['dt'] = str(t - last_t[selector])
                last_t[selector] = t
            ans.append((float(parts[0]), selector, fields))
    return ans


def differences(want: Report, got: Report) -> list[str]:
    return [f'{k}: expected {v}, got {got.get(k, "absent")}' for k, v in want.items() if got.get(k, 'absent') != v]


def align(want: list[Report], got: list[Report]) -> list[tuple[int | None, int | None]]:
    "Pairs of indices into want and got, None where one has no partner, at the least total cost"
    INF = 1e9

    def pair(w: Report, g: Report) -> float:
        d = len(differences(w, g))
        # reports that differ in most of what is expected are not the same report
        return 0 if d == 0 else (1.2 + d / 100 if d <= max(1, len(w) // 2) else INF)

    n, m = len(want), len(got)
    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 or j == 0:
                cost[i][j] = i + j
            else:
                cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1, cost[i - 1][j - 1] + pair(want[i - 1], got[j - 1]))
    ans: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + pair(want[i - 1], got[j - 1]):
            ans.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            ans.append((i - 1, None))
            i -= 1
        else:
            ans.append((None, j - 1))
            j -= 1
    return ans[::-1]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('client_log')
    p.add_argument('expectations')
    args = p.parse_args()
    received = reports(args.client_log)
    with open(args.expectations) as f:
        marks: list[dict[str, Any]] = [json.loads(line) for line in f]
    starts = [m for m in marks if 'sequence' in m]
    ok = bad = 0
    for k, start in enumerate(starts):
        end = starts[k + 1]['at'] if k + 1 < len(starts) else float('inf')
        mine = [m for m in marks if start['at'] <= m['at'] < end]
        print(f'== {start["sequence"]}')
        for m in mine:
            if 'died' in m:
                bad += 1
                print('DIED     the terminal dropped its connection')
        expected = {m['selector'] for m in mine if 'selector' in m}
        seen = {s for t, s, _ in received if start['at'] <= t < end and (s in expected or not s.endswith(':device'))}
        for selector in sorted(expected | seen):
            want = [m for m in mine if m.get('selector') == selector]
            got = [(t, r) for t, s, r in received if s == selector and start['at'] <= t < end]
            # reports that are allowed but cannot be predicted, such as the terminal's own momentum
            optional_until = max((m['at'] for m in mine if m.get('skip') == selector), default=0)
            for i, j in align([m['fields'] for m in want], [r for _, r in got]):
                if i is None:
                    assert j is not None
                    if got[j][0] >= optional_until:
                        bad += 1
                        print(f'UNEXPECTED {selector};{got[j][1]["_raw"]}')
                elif j is None:
                    bad += 1
                    print(f'MISSING  {want[i]["note"]}: wanted {want[i]["fields"]}')
                elif d := differences(want[i]['fields'], got[j][1]):
                    bad += 1
                    print(f'MISMATCH {want[i]["note"]}: {"; ".join(d)}')
                    print(f'         got {got[j][1]["_raw"]}')
                else:
                    ok += 1
    print(f'{ok} reports as expected, {bad} differences')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
