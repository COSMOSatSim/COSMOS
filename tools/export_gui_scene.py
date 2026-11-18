#!/usr/bin/env python3
"""
Export SECMotionModel configurations to the SECMotionModel-GUI scene format
v1.

The GUI never re-implements orbital mechanics: this exporter converts the
Skyfield positions computed by the simulator into Earth-fixed ECEF/ITRS
kilometres and writes a directory the GUI can load directly. Terrestrial
configurations use the observer position as the single terminal marker;
extended configurations may provide a per-step ``vessel_position``.

Output layout
-------------
out/
  manifest.json       scene manifest (schema/scene-v1.schema.json)
  frames/000000.json  one frame per configuration (schema/frame-v1.schema.json)
  tasks.jsonl         optional task trace (schema/tasks-v1.schema.json)

Usage
-----
python tools/export_gui_scene.py \
    --config data/configurations_AP_optimal.json \
    --out /tmp/secgui/terrestrial \
    --start 0 --end 150
"""

from __future__ import annotations

import argparse
import csv
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
    parser.add_argument("--config", default=None,
                        help="configurations JSON (terrestrial or extended)")
    parser.add_argument("--out", required=True, help="output scene directory")
    parser.add_argument("--trace", default=None, help="task trace JSONL produced by the simulation")
    parser.add_argument("--run-dir", default=None,
                        help="simulation run directory with gui_run.json, gui_state.csv and gui_links.csv")
    parser.add_argument("--state", default=None, help="gui_state.csv (overrides --run-dir)")
    parser.add_argument("--links", default=None, help="gui_links.csv (overrides --run-dir)")
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


def load_state_csv(path: Path) -> list[tuple[float, dict[str, dict[str, Any]]]]:
    """Load gui_state.csv into time-sorted (time, {satellite: metrics}) samples."""
    if not path.exists():
        return []
    samples: dict[float, dict[str, dict[str, Any]]] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row.get("satellite")
            if not name:
                continue
            try:
                time_s = float(row.get("time", 0.0) or 0.0)
                metrics = {
                    "cpu_queue": int(float(row.get("cpu_queue", 0) or 0)),
                    "cpu_service": int(float(row.get("cpu_service", 0) or 0)),
                    "net_queue": int(float(row.get("net_queue", 0) or 0)),
                    "net_service": int(float(row.get("net_service", 0) or 0)),
                    "completed": int(float(row.get("completed_tasks", 0) or 0)),
                    "energy_j": float(row.get("energy_j", 0.0) or 0.0),
                    "energy_reserved_j": float(row.get("energy_reserved_j", 0.0) or 0.0),
                }
            except (TypeError, ValueError):
                continue
            samples.setdefault(time_s, {})[name] = metrics
    return sorted(samples.items())


def load_links_csv(path: Path) -> list[dict[str, Any]]:
    """Load gui_links.csv into normalized traffic events."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                t0 = float(row.get("t_start", 0.0) or 0.0)
                t1 = float(row.get("t_end", t0) or t0)
                duration = float(row.get("duration_s", max(0.0, t1 - t0)) or 0.0)
            except (TypeError, ValueError):
                continue
            events.append({
                "t0": round(t0, 9),
                "t1": round(t1, 9),
                "from": row.get("source", ""),
                "to": row.get("target", ""),
                "task": int(float(row.get("task", 0) or 0)),
                "size_mb": round(float(row.get("size_mb", 0.0) or 0.0), 6),
                "bandwidth_mbps": round(float(row.get("bandwidth_mbps", 0.0) or 0.0), 6),
                "duration_s": round(duration, 9),
                "kind": row.get("kind", ""),
                "algo": row.get("algorithm", ""),
            })
    events.sort(key=lambda item: (item["t0"], item["task"]))
    return events


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
    vessel_name: str = "OBS",
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
            "name": vessel_name,
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

    run_meta: dict[str, Any] = {}
    run_dir = Path(args.run_dir) if args.run_dir else None
    if run_dir is not None:
        meta_path = run_dir / "gui_run.json"
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as handle:
                run_meta = json.load(handle)
        if args.state is None:
            args.state = str(run_dir / run_meta.get("state", "gui_state.csv"))
        if args.links is None:
            args.links = str(run_dir / run_meta.get("links", "gui_links.csv"))
        if args.config is None:
            args.config = run_meta.get("config")
        if args.trace is None:
            candidate = run_dir / "tasks.jsonl"
            if candidate.exists():
                args.trace = str(candidate)

    if not args.config:
        raise SystemExit("--config is required (or use --run-dir with gui_run.json)")
    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"configuration not found: {config_path}")

    state_samples = load_state_csv(Path(args.state)) if args.state else []
    traffic_events = load_links_csv(Path(args.links)) if args.links else []

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

    vessel_name = data.get("vessel_name")
    first_vessel = (
        configurations[start].get("vessel_position")
        or data.get("vessel_position")
        or {}
    )
    if first_vessel:
        vessel_position = (
            float(first_vessel.get("lat", 0.0)),
            float(first_vessel.get("lon", 0.0)),
        )
        vessel_name = vessel_name or "TERMINAL"
    else:
        # Terrestrial configurations expose a single observer terminal.
        vessel_position = observer_position
        vessel_name = vessel_name or "OBS"

    exported = 0
    load_samples: list[dict[str, Any]] = []
    frame_ids: dict[int, set[str]] = {}
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
            vessel_name,
        )
        with (frames_dir / f"{index:06d}.json").open("w", encoding="utf-8") as handle:
            json.dump(document, handle, separators=(",", ":"))

        frame_ids[index] = {satellite["id"] for satellite in document["satellites"]}

        exported += 1
        if exported % 10 == 0 or exported == end - start:
            print(f"exported frame {index} ({exported}/{end - start})")

    if state_samples:
        for time_s, metrics_by_name in state_samples:
            if time_s < start * interval - 1e-9 or time_s >= end * interval - 1e-9:
                continue
            frame_index = min(int(time_s // interval), end - 1)
            ids = frame_ids.get(frame_index)
            if not ids:
                continue
            entries = [
                {"id": name, **metrics}
                for name, metrics in metrics_by_name.items()
                if name in ids
            ]
            if entries:
                load_samples.append({
                    "t": round(time_s, 6),
                    "frame": frame_index,
                    "satellites": entries,
                })

    loads_name = None
    if load_samples:
        loads_name = "loads.jsonl"
        with (output_dir / loads_name).open("w", encoding="utf-8") as handle:
            for sample in load_samples:
                handle.write(json.dumps(sample, separators=(",", ":")) + "\n")
        print(f"exported {len(load_samples)} load samples")

    traffic_name = None
    if traffic_events:
        traffic_name = "traffic.jsonl"
        with (output_dir / traffic_name).open("w", encoding="utf-8") as handle:
            for event in traffic_events:
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
        print(f"exported {len(traffic_events)} traffic events")

    tasks_name = None
    if args.trace:
        trace_path = Path(args.trace)
        if not trace_path.exists():
            raise SystemExit(f"trace not found: {trace_path}")
        count = convert_trace(trace_path, output_dir / "tasks.jsonl")
        print(f"exported {count} task events")
        tasks_name = "tasks.jsonl"

    has_live_data = bool(loads_name or traffic_name)
    manifest = {
        "version": 2 if has_live_data else 1,
        "generator": "SECMotionModel tools/export_gui_scene.py",
        "source": {
            "config": str(config_path),
            "trace": args.trace,
            "run_dir": str(run_dir) if run_dir is not None else None,
            "state": args.state,
            "links": args.links,
        },
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
    if loads_name:
        manifest["loads"] = loads_name
        manifest["load"] = {
            "metric": "max",
            "cpu_capacity": float(run_meta.get(
                "cpu_capacity", core_config.get("cpu_capacity_queue", 5))),
            "net_capacity": float(run_meta.get(
                "net_capacity", core_config.get("net_capacity_queue", 5))),
        }
    if traffic_name:
        manifest["traffic"] = traffic_name
    if loads_name or traffic_name:
        manifest["default_layers"] = {
            "load": bool(loads_name),
            "traffic": bool(traffic_name),
            "tasks": False,
        }

    with (output_dir / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    print(f"scene written to {output_dir} ({exported} frames, {len(satellite_cache)} satellites)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
