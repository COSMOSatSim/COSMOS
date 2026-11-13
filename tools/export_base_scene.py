#!/usr/bin/env python3
"""Export a TLE-only base scene for the GUI.

The scene contains every satellite in the TLE catalog, propagated to
Earth-fixed ECEF/ITRS positions over a short time window. It has no tasks,
load samples or traffic events: it is the neutral "constellation around the
globe" scene used as the GUI starting point.

Usage:
    python3 tools/export_base_scene.py \
        --tle data/tle_data.txt \
        --out ~/.cache/secgui/base \
        --interval 5 --duration 300
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from skyfield.api import EarthSatellite, load, wgs84
from skyfield.framelib import itrs


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a TLE base scene for the GUI")
    parser.add_argument("--tle", default="data/tle_data.txt", help="TLE catalog")
    parser.add_argument("--out", required=True, help="output scene directory")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between frames")
    parser.add_argument("--duration", type=float, default=300.0, help="scene duration in seconds")
    parser.add_argument("--start", default=None, help="ISO-8601 start time (default: now, UTC)")
    parser.add_argument("--max-satellites", type=int, default=0, help="limit for quick tests")
    parser.add_argument("--observer-name", default="OBS")
    parser.add_argument("--observer-lat", type=float, default=41.9028)
    parser.add_argument("--observer-lon", type=float, default=12.4964)
    parser.add_argument("--terminal-name", default="V-ATLANTIC")
    parser.add_argument("--terminal-lat", type=float, default=33.373586)
    parser.add_argument("--terminal-lon", type=float, default=-47.955604)
    return parser.parse_args()


def load_tle_catalog(path: Path) -> list[tuple[str, str, str]]:
    lines = [line.rstrip("\r\n") for line in path.read_text(encoding="utf-8").splitlines()]
    lines = [line for line in lines if line.strip()]
    catalog: list[tuple[str, str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("1 ") and index + 1 < len(lines):
            # Two-line TLE without a name.
            line1 = line
            line2 = lines[index + 1].strip()
            if line2.startswith("2 "):
                catalog.append((f"SAT-{len(catalog) + 1}", line1, line2))
                index += 2
                continue
        if line.startswith("1 ") or line.startswith("2 "):
            index += 1
            continue
        if index + 2 >= len(lines):
            break
        line1 = lines[index + 1].strip()
        line2 = lines[index + 2].strip()
        if line1.startswith("1 ") and line2.startswith("2 "):
            catalog.append((line.strip() or f"SAT-{len(catalog) + 1}", line1, line2))
            index += 3
        else:
            index += 1
    return catalog


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def ecef_km(position) -> list[float]:
    vector = position.frame_xyz(itrs).km
    return [round(float(component), 3) for component in vector]


def finite_position(vector: list[float]) -> bool:
    return all(math.isfinite(component) for component in vector)


def main() -> int:
    args = parse_arguments()
    tle_path = Path(args.tle)
    if not tle_path.exists():
        raise SystemExit(f"TLE catalog not found: {tle_path}")
    if args.interval <= 0.0 or args.duration < 0.0:
        raise SystemExit("--interval must be positive and --duration non-negative")

    catalog = load_tle_catalog(tle_path)
    if args.max_satellites > 0:
        catalog = catalog[: args.max_satellites]
    if not catalog:
        raise SystemExit(f"no TLE entries found in {tle_path}")

    start = (
        datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        if args.start
        else datetime.now(timezone.utc).replace(microsecond=0)
    )
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    timescale = load.timescale()
    satellites = [
        EarthSatellite(line1, line2, name, timescale)
        for name, line1, line2 in catalog
    ]

    output = Path(args.out)
    frames_dir = output / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_count = int(round(args.duration / args.interval)) + 1

    terminal = wgs84.latlon(args.terminal_lat, args.terminal_lon)
    observer = wgs84.latlon(args.observer_lat, args.observer_lon)

    for frame in range(frame_count):
        moment = start + timedelta(seconds=frame * args.interval)
        sky_time = timescale.from_datetime(moment)
        entries: list[dict[str, Any]] = []
        for satellite in satellites:
            position = ecef_km(satellite.at(sky_time))
            if not finite_position(position):
                continue
            entries.append({
                "id": satellite.name,
                "ecef_km": position,
                "is_ap": False,
                "neighbors": [],
            })
        document = {
            "index": frame,
            "t": round(frame * args.interval, 6),
            "time": iso_utc(moment),
            "vessel": {
                "name": args.terminal_name,
                "lat": args.terminal_lat,
                "lon": args.terminal_lon,
                "ecef_km": ecef_km(terminal.at(sky_time)),
            },
            "observer": {
                "name": args.observer_name,
                "lat": args.observer_lat,
                "lon": args.observer_lon,
                "ecef_km": ecef_km(observer.at(sky_time)),
            },
            "satellites": entries,
        }
        with (frames_dir / f"{frame:06d}.json").open("w", encoding="utf-8") as handle:
            json.dump(document, handle, separators=(",", ":"))
        if frame % 10 == 0 or frame + 1 == frame_count:
            print(f"exported frame {frame} ({frame + 1}/{frame_count}), "
                  f"{len(entries)} satellites")

    manifest = {
        "version": 1,
        "generator": "SECMotionModel tools/export_base_scene.py (TLE base scene)",
        "source": {"tle": str(tle_path), "satellites": len(satellites)},
        "t0": iso_utc(start),
        "interval_s": float(args.interval),
        "duration_s": float(args.duration),
        "earth_radius_km": 6371.0,
        "phi_max_deg": 40.0,
        "phi_buffer_deg": 15.0,
        "terminal": {
            "name": args.terminal_name,
            "lat": args.terminal_lat,
            "lon": args.terminal_lon,
        },
        "observer": {
            "name": args.observer_name,
            "lat": args.observer_lat,
            "lon": args.observer_lon,
        },
        "frames": {"count": frame_count, "pattern": "frames/%06d.json"},
    }
    with (output / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    print(f"base scene written to {output} ({frame_count} frames, {len(satellites)} satellites)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
