#!/usr/bin/env python3
"""Write the single-file SECMotionModel GUI simulation descriptor (.secsim).

The descriptor is deliberately small: it points at the scene manifest and at
the optional sidecar files that the GUI already consumes. Paths are stored
relative to the descriptor when possible, so a descriptor can live next to a
simulation result while the exported scene stays in a cache directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SIMULATION_FORMAT = "secgui-simulation"
SIMULATION_VERSION = 1


def _relative_to_bundle(target: Path, bundle_dir: Path) -> str:
    try:
        return os.path.relpath(Path(target).resolve(), bundle_dir.resolve())
    except ValueError:
        # os.path.relpath raises on Windows when the paths are on different
        # drives. An absolute path is still valid for the GUI.
        return str(Path(target).resolve())


def write_bundle(
    path: str | Path,
    manifest: str | Path,
    *,
    tasks: str | Path | None = None,
    loads: str | Path | None = None,
    traffic: str | Path | None = None,
    name: str | None = None,
    source: dict[str, Any] | None = None,
) -> Path:
    """Write the GUI simulation descriptor and return its path."""
    bundle_path = Path(path)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_dir = bundle_path.parent
    document: dict[str, Any] = {
        "format": SIMULATION_FORMAT,
        "version": SIMULATION_VERSION,
    }
    if name:
        document["name"] = name
    document["manifest"] = _relative_to_bundle(Path(manifest), bundle_dir)
    for key, target in (("tasks", tasks), ("loads", loads), ("traffic", traffic)):
        if target is not None:
            document[key] = _relative_to_bundle(Path(target), bundle_dir)
    if source:
        document["source"] = source
    bundle_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return bundle_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Write a .secsim simulation descriptor")
    parser.add_argument("--manifest", required=True, help="scene manifest path")
    parser.add_argument("--out", required=True, help="descriptor output path")
    parser.add_argument("--tasks", default=None)
    parser.add_argument("--loads", default=None)
    parser.add_argument("--traffic", default=None)
    parser.add_argument("--name", default=None)
    arguments = parser.parse_args()
    result = write_bundle(
        arguments.out,
        arguments.manifest,
        tasks=arguments.tasks,
        loads=arguments.loads,
        traffic=arguments.traffic,
        name=arguments.name,
    )
    print(result)
