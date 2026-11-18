#!/usr/bin/env python3
"""
Convert a SECMotionModel naval simulation log into the GUI task trace JSONL
(schema/tasks-v1.schema.json).

This works on already-produced logs, without re-running the simulation and
without modifying the simulation code. When the instrumented `--trace-jsonl`
mode lands, prefer that: it also records exact hop durations and failures.

Recognised lines (IN_NETWORK and TO_OBSERVER naval runs)
--------------------------------------------------------
---> Task 1 (Type: CPU_and_Data_Intensive) arriva in 0.18
[0.18] [Task 1] Routed STARLINK-37163 -> STARLINK-33957 | ...
[2][GREEDY] STARLINK-2500 -> STARLINK-37163 | Tramission-time: ...
[1][GREEDY] CONSEGNATO! STARLINK-33957 -> V-ATLANTIC | ...
[0.398] Task 1 served on STARLINK-33957
Task Persi / TTL Scaduto: ...

Usage
-----
python tools/parse_naval_log.py \
    --log result/naval_full_run_2026-11-10/naval_full_in_network.log \
    --out result/naval/IN_NETWORK/optimal/tasks.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
SPAWN_RE = re.compile(r"Task (\d+) \(Type: ([^)]+)\) arriva in ([\d.]+)")
ROUTE_RE = re.compile(r"\[([\d.]+)\] \[Task (\d+)\] Routed (\S+) -> (\S+)")
TRANSMIT_RE = re.compile(r"\[(\d+)\]\[(\w+)\] (\S+) -> (\S+) \| Tramission-time: ([\d.eE+-]+)")
DELIVER_RE = re.compile(r"\[(\d+)\]\[?(\w+)\]? CONSEGNATO! (\S+) -> (\S+)")
SERVED_RE = re.compile(r"\[([\d.]+)\] Task (\d+) served on (\S+)")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse a naval log into a GUI task trace")
    parser.add_argument("--log", required=True, help="log file (ANSI colours allowed)")
    parser.add_argument("--out", required=True, help="output tasks.jsonl")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    log_path = Path(args.log)
    if not log_path.exists():
        raise SystemExit(f"log not found: {log_path}")

    events: list[dict] = []
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = ANSI_RE.sub("", line).rstrip("\n")

            match = SPAWN_RE.search(line)
            if match:
                task, task_type, moment = match.groups()
                events.append(
                    {
                        "t": round(float(moment), 6),
                        "event": "spawn",
                        "task": int(task),
                        "node": "terminal",
                        "type": task_type,
                    }
                )
                continue

            match = ROUTE_RE.search(line)
            if match:
                moment, task, source, target = match.groups()
                events.append(
                    {
                        "t": round(float(moment), 6),
                        "event": "hop_start",
                        "task": int(task),
                        "from": source,
                        "to": target,
                        "algo": "GREEDY",
                    }
                )
                continue

            match = DELIVER_RE.search(line)
            if match:
                task, algorithm, source, target = match.groups()
                events.append(
                    {
                        "t": None,
                        "event": "deliver",
                        "task": int(task),
                        "from": source,
                        "to": target,
                        "algo": algorithm,
                    }
                )
                continue

            match = SERVED_RE.search(line)
            if match:
                moment, task, node = match.groups()
                events.append(
                    {
                        "t": round(float(moment), 6),
                        "event": "compute",
                        "task": int(task),
                        "node": node,
                    }
                )
                continue

            match = TRANSMIT_RE.search(line)
            if match:
                task, algorithm, source, target, _ = match.groups()
                events.append(
                    {
                        "t": None,
                        "event": "hop_start",
                        "task": int(task),
                        "from": source,
                        "to": target,
                        "algo": algorithm,
                    }
                )

    # Logs do not carry timestamps on every hop; give unknown times the
    # previous known time so the sequence stays monotonic.
    current = 0.0
    for event in events:
        if event.get("t") is None:
            event["t"] = round(current, 6)
        else:
            current = event["t"]

    events.sort(key=lambda item: (item["t"], item["task"], item["event"]))

    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")

    tasks = len({event["task"] for event in events})
    print(f"wrote {len(events)} events for {tasks} tasks to {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
