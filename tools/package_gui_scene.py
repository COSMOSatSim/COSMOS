#!/usr/bin/env python3
"""Package an existing GUI scene directory into one .secsim file.

This is the generic escape hatch for simulations that do not use the TLE
configuration exporter: write a normal GUI scene (manifest + frames + optional
tasks/loads/traffic, see gui/docs/scene-format.md), then run this script. The
GUI only needs the resulting descriptor and the files it points at.

Usage:
    python3 tools/package_gui_scene.py \
        --scene /path/to/scene \
        --out /path/to/simulation.secsim
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scene_bundle import write_bundle  # noqa: E402


def find_manifest(scene_dir: Path) -> Path:
    for name in ("manifest.json", "scene.json"):
        candidate = scene_dir / name
        if candidate.is_file():
            return candidate
    raise SystemExit(f"no manifest.json or scene.json in {scene_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scene", required=True, help="scene directory")
    parser.add_argument("--out", required=True, help="output .secsim file")
    parser.add_argument("--name", default=None, help="display name")
    arguments = parser.parse_args()

    scene_dir = Path(arguments.scene)
    manifest = find_manifest(scene_dir)
    with manifest.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    if not isinstance(document, dict):
        raise SystemExit(f"scene manifest is not a JSON object: {manifest}")
    version = document.get("version")
    if version not in (1, 2):
        raise SystemExit(f"unsupported scene version {version!r} in {manifest}")

    sidecars = {}
    for key in ("tasks", "loads", "traffic"):
        value = document.get(key)
        if isinstance(value, str) and value:
            path = Path(value)
            sidecars[key] = path if path.is_absolute() else scene_dir / path

    descriptor = write_bundle(
        arguments.out,
        manifest,
        tasks=sidecars.get("tasks"),
        loads=sidecars.get("loads"),
        traffic=sidecars.get("traffic"),
        name=arguments.name or scene_dir.name,
        source={"scene": str(scene_dir.resolve()), "manifest_version": version},
    )
    print(f"simulation file written to {descriptor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
