"""Minimal CSV telemetry for the GUI live playback.

The GUI does not run SimPy: this module records the state already produced by
``EdgeServer.export_state()`` and the real transmission intervals handled by
``EdgeServer.transmit_task()``. It is enabled by ``naval_main.py --gui-export``
and has no effect otherwise.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

STATE_FIELDS = [
    "frame",
    "time",
    "satellite",
    "is_access_point",
    "cpu_queue",
    "cpu_service",
    "net_queue",
    "net_service",
    "completed_tasks",
    "energy_j",
    "energy_reserved_j",
    "neighbors",
]

LINK_FIELDS = [
    "t_start",
    "t_end",
    "source",
    "target",
    "task",
    "size_mb",
    "bandwidth_mbps",
    "duration_s",
    "kind",
    "algorithm",
]


class GuiMonitor:
    """Write per-satellite load snapshots and link transmissions to CSV."""

    def __init__(self, output_dir, interval_s, end_s):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.interval_s = float(interval_s)
        self.end_s = float(end_s)
        self._closed = False

        self._state_file = (self.output_dir / "gui_state.csv").open(
            "w", newline="", encoding="utf-8"
        )
        self._state_writer = csv.writer(self._state_file)
        self._state_writer.writerow(STATE_FIELDS)

        self._link_file = (self.output_dir / "gui_links.csv").open(
            "w", newline="", encoding="utf-8"
        )
        self._link_writer = csv.writer(self._link_file)
        self._link_writer.writerow(LINK_FIELDS)

    def snapshot(self, env, servers):
        if self._closed:
            return
        frame = int(round(env.now / self.interval_s))
        for server in servers:
            if server is None:
                continue
            state = server.export_state(env)
            if not state:
                continue
            self._state_writer.writerow([
                frame,
                f"{env.now:.6f}",
                state.get("satellite", ""),
                state.get("is_access_point", False),
                state.get("queue_cpu_len", 0),
                state.get("cpu_service_len", 0),
                state.get("queue_net_len", 0),
                state.get("net_service_len", 0),
                state.get("completed_tasks_count", 0),
                state.get("energy_budget_J", 0.0),
                state.get("energy_reserved_J", 0.0),
                state.get("neighbors_count", 0),
            ])

    def record_link(self, t_start, t_end, source, target, task_id, size_mb,
                    bandwidth_mbps, duration_s, kind, algorithm):
        if self._closed:
            return
        self._link_writer.writerow([
            f"{t_start:.9f}",
            f"{t_end:.9f}",
            source,
            target,
            task_id,
            f"{size_mb:.6f}",
            f"{bandwidth_mbps:.6f}",
            f"{duration_s:.9f}",
            kind,
            algorithm,
        ])

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._state_file.close()
        self._link_file.close()


def collect_gui_state(env, monitor, interval_s, end_s):
    """SimPy process: snapshot every interval until the last scene frame."""
    import globals

    while env.now <= end_s + 1e-9:
        monitor.snapshot(env, globals.edge_servers)
        yield env.timeout(interval_s)


def write_run_metadata(output_dir, config, use_case, mode, t0, duration_s,
                       interval_s, sample_interval_s, config_path):
    """Write the small run descriptor consumed by the scene exporter."""
    metadata = {
        "version": 1,
        "use_case": use_case,
        "mode": mode,
        "t0": t0,
        "duration_s": duration_s,
        "interval_s": interval_s,
        "sample_interval_s": sample_interval_s,
        "state": "gui_state.csv",
        "links": "gui_links.csv",
        "config": config_path,
        "seed": config.get("seed"),
        "cpu_capacity": config.get("cpu_capacity_queue", 5),
        "net_capacity": config.get("net_capacity_queue", 5),
    }
    path = Path(output_dir) / "gui_run.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2)
