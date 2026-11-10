#!/usr/bin/env python3
"""
Export SECMotionModel naval configurations to the SECMotionModel-GUI scene
format v1.

The GUI never re-implements orbital mechanics: this exporter converts the
Skyfield positions computed by the simulator into Earth-fixed ECEF/ITRS
kilometres and writes a directory the GUI can load directly.

Output layout
-------------
out/
  manifest.json       scene manifest (schema/scene-v1.schema.json)
  frames/000000.json  one frame per configuration (schema/frame-v1.schema.json)
  tasks.jsonl         optional task trace (schema/tasks-v1.schema.json)

Usage
-----
python tools/export_gui_scene.py \
    --config data/naval_configurations_AP_optimal.json \
    --trace result/naval/IN_NETWORK/optimal/trace.jsonl \
    --out ../SECMotionModel-GUI/examples/generated/naval \
    --start 0 --end 150
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from skyfield.api import EarthSatellite, load, wgs84
from skyfield.framelib import itrs

EARTH_RADIUS_KM = 6371.0
DEFAULT_OBSERVER = {"name": "Roma", "lat": 41.8967, "lon": 12.4822}
TASK_EVENTS = {"spawn", "hop_start", "hop_end", "compute", "deliver", "complete", "fail"}


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export SECMotionModel configurations to a GUI scene directory"
    )
    parser.add_argument("--config", required=True, help="naval configurations JSON")
    parser.add_argument("--out", required=True, help="output scene directory")
    parser.add_argument("--trace", default=None, help="task trace JSONL produced by the simulation")
    parser.add_argument(
        "--core-config",
        default="config/config.json5",
        help="core configuration used for Phi_max / Phi_buffer / observer coordinates",
    )
    parser.add_argument("--start", type=int, default=0, help="first frame index (inclusive)")
    parser.add_argument("--end", type=int, default=None, help="last frame index (exclusive)")
    parser.add_argument("--earth-radius-km", type=float, default=EARTH_RADIUS_KM)
    return parser.parse_args()


def load_json5(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import json5  # type: ignore
    except ImportError:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json5.load(handle)


def to_skyfield_time(timescale, iso_string: str):
    parsed = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return timescale.from_datetime(parsed)


def ecef_km(observer, sky_time) -> list[float]:
    """Convert a Skyfield position to Earth-fixed ECEF/ITRS kilometres."""
    vector = observer.at(sky_time).frame_xyz(itrs).km
    return [round(float(component), 3) for component in vector]


def life_remaining_seconds(life: Any) -> float | None:
    if not isinstance(life, dict):
        return None
    for key in ("time_until_set_seconds", "life_seconds"):
        value = life.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def build_satellite_cache(configurations: list[dict[str, Any]], timescale):
    cache: dict[str, EarthSatellite] = {}
    for step in configurations:
        for satellite in step.get("configuration", []):
            name = satellite.get("satellite")
            if not name or name in cache:
                continue
            tle = satellite.get("TLE-DATA") or []
            if not tle:
                continue
            entry = tle[0]
            cache[name] = EarthSatellite(entry["line1"], entry["line2"], entry["name"], timescale)
    return cache


def access_point_map(step: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for terminal, names in (step.get("access_points") or {}).items():
        for name in names or []:
            result.setdefault(name, []).append(terminal)
    return result


def frame_document(
    index: int,
    step: dict[str, Any],
    timescale,
    satellite_cache: dict[str, EarthSatellite],
    vessel_position: tuple[float, float],
    observer_position: tuple[float, float],
    interval: float,
) -> dict[str, Any]:
    sky_time = to_skyfield_time(timescale, step["time"])
    ap_map = access_point_map(step)

    vessel_lat, vessel_lon = vessel_position
    observer_lat, observer_lon = observer_position

    vessel = wgs84.latlon(vessel_lat, vessel_lon)
    observer = wgs84.latlon(observer_lat, observer_lon)

    satellites: list[dict[str, Any]] = []
    for satellite in step.get("configuration", []):
        name = satellite.get("satellite")
        cached = satellite_cache.get(name)
        if cached is None:
            continue
        terminals = ap_map.get(name, [])
        satellites.append(
            {
                "id": name,
                "ecef_km": ecef_km(cached, sky_time),
                "is_ap": bool(satellite.get("is_access_point")) or bool(terminals),
                "terminal_ref": terminals[0] if terminals else None,
                "terminal_refs": terminals,
                "elev_deg": satellite.get("elev_angle"),
                "range_km": satellite.get("distance_from_user"),
                "life_remaining_s": life_remaining_seconds(satellite.get("life")),
                "neighbors": [
                    {"id": neighbor.get("name"), "latency_ms": round(float(neighbor.get("latency", 0.0)) * 1000.0, 4)}
                    for neighbor in satellite.get("neighbors", [])
                    if neighbor.get("name")
                ],
            }
        )

    known_ids = {satellite["id"] for satellite in satellites}
    seen_edges: set[tuple[str, str]] = set()
    for satellite in satellites:
        filtered = []
        for neighbor in satellite.get("neighbors", []):
            other = neighbor.get("id")
            if not other or other not in known_ids:
                continue
            edge = tuple(sorted((satellite["id"], other)))
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            filtered.append(neighbor)
        satellite["neighbors"] = filtered

    satellites.sort(key=lambda item: item["id"])
    return {
        "version": 1,
        "index": index,
        "t": round(index * interval, 3),
        "time": step["time"],
        "vessel": {
            "name": "vessel",
            "lat": vessel_lat,
            "lon": vessel_lon,
            "ecef_km": ecef_km(vessel, sky_time),
        },
        "observer": {
            "name": "observer",
            "lat": observer_lat,
            "lon": observer_lon,
            "ecef_km": ecef_km(observer, sky_time),
        },
        "satellites": satellites,
    }


def convert_trace(trace_path: Path, destination: Path) -> int:
    events: list[dict[str, Any]] = []
    with trace_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise SystemExit(f"{trace_path}:{line_number}: invalid JSON: {error}") from error
            name = event.get("event") or event.get("type")
            if name not in TASK_EVENTS or "t" not in event or "task" not in event:
                continue
            fixed = dict(event)
            fixed["event"] = name
            events.append(fixed)

    events.sort(key=lambda item: float(item["t"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    return len(events)


def main() -> int:
    args = parse_arguments()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"configuration not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    configurations = data.get("configurations") or []
    if not configurations:
        raise SystemExit(f"no configurations found in {config_path}")

    interval = float(data.get("interval", 2))
    start = max(0, args.start)
    end = len(configurations) if args.end is None else min(len(configurations), args.end)
    if end <= start:
        raise SystemExit(f"empty frame range [{start}, {end})")

    core_config = load_json5(Path(args.core_config))
    phi_max = float(core_config.get("Phi_max", 40.0))
    phi_buffer = float(core_config.get("Phi_buffer", 15.0))
    simulation_location = core_config.get("simulation_location", "Roma")
    location = (core_config.get("locations") or {}).get(simulation_location) or DEFAULT_OBSERVER
    observer_position = (
        float(location.get("lat", DEFAULT_OBSERVER["lat"])),
        float(location.get("lon", DEFAULT_OBSERVER["lon"])),
    )

    output_dir = Path(args.out)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    timescale = load.timescale()
    satellite_cache = build_satellite_cache(configurations, timescale)
    if not satellite_cache:
        raise SystemExit("no TLE data found in the configurations")

    vessel_name = data.get("vessel_name", "VESSEL")
    first_vessel = configurations[start].get("vessel_position") or {}
    vessel_position = (
        float(first_vessel.get("lat", 0.0)),
        float(first_vessel.get("lon", 0.0)),
    )

    exported = 0
    for index in range(start, end):
        step = configurations[index]
        step_vessel = step.get("vessel_position") or {}
        current_vessel = (
            float(step_vessel.get("lat", vessel_position[0])),
            float(step_vessel.get("lon", vessel_position[1])),
        )
        document = frame_document(
            index,
            step,
            timescale,
            satellite_cache,
            current_vessel,
            observer_position,
            interval,
        )
        with (frames_dir / f"{index:06d}.json").open("w", encoding="utf-8") as handle:
            json.dump(document, handle, separators=(",", ":"))
        exported += 1
        if exported % 10 == 0 or exported == end - start:
            print(f"exported frame {index} ({exported}/{end - start})")

    tasks_name = None
    if args.trace:
        trace_path = Path(args.trace)
        if not trace_path.exists():
            raise SystemExit(f"trace not found: {trace_path}")
        count = convert_trace(trace_path, output_dir / "tasks.jsonl")
        print(f"exported {count} task events")
        tasks_name = "tasks.jsonl"

    manifest = {
        "version": 1,
        "generator": "SECMotionModel tools/export_gui_scene.py",
        "source": {"config": str(config_path), "trace": args.trace},
        "t0": configurations[start].get("time"),
        "interval_s": interval,
        "duration_s": round((end - start) * interval, 3),
        "earth_radius_km": args.earth_radius_km,
        "phi_max_deg": phi_max,
        "phi_buffer_deg": phi_buffer,
        "terminal": {
            "name": vessel_name,
            "lat": vessel_position[0],
            "lon": vessel_position[1],
        },
        "observer": {
            "name": simulation_location,
            "lat": observer_position[0],
            "lon": observer_position[1],
        },
        "frames": {"count": exported, "pattern": "frames/%06d.json"},
    }
    if tasks_name:
        manifest["tasks"] = tasks_name

    with (output_dir / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    print(f"scene written to {output_dir} ({exported} frames, {len(satellite_cache)} satellites)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
