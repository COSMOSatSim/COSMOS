#!/usr/bin/env bash
#
# Export a SECMotionModel simulation and open it in the GUI.
#
# This is the core-side companion to the standalone GUI launcher. It invokes
# tools/export_gui_scene.py, writes a .secsim descriptor into the GUI cache and
# then calls gui/scripts/run_gui.sh with that file. The GUI binary itself has no
# Python or core dependency.
#
#   tools/run_gui.sh                     TLE base scene
#   tools/run_gui.sh --config FILE       export a topology configuration
#   tools/run_gui.sh --trace FILE        attach a task trace to --config
#   tools/run_gui.sh --run DIR           export a simulation run
#   tools/run_gui.sh --naval             export and open the naval run
#   tools/run_gui.sh --empty             empty GUI workspace
#   tools/run_gui.sh --minimal           minimal GUI example
#
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
	DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
	SOURCE="$(readlink "$SOURCE")"
	[[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
CORE="$(cd -P "$(dirname "$SOURCE")/.." && pwd)"
GUI_LAUNCHER="$CORE/gui/scripts/run_gui.sh"
CACHE="${SECGUI_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/secgui}"

usage() {
	cat <<'EOF'
Usage: tools/run_gui.sh [options] [GUI options...]

Export a simulation with the core exporter, then open the resulting .secsim in
the standalone GUI.

  --config <json>    export a configuration JSON
  --trace <jsonl>    task trace for --config
  --run <dir>        export a run directory with gui_run.json
  --naval            export result/naval/IN_NETWORK/optimal (or TO_OBSERVER)
  --base             TLE base scene (default)
  --empty            empty GUI workspace
  --minimal          minimal example scene
  --gui <path>       GUI launcher (default: gui/scripts/run_gui.sh)
  -h, --help         show this help

Everything else is forwarded to the GUI, for example --time, --camera,
--target, --headless or --screenshot.

Environment:
  SECGUI_CACHE_DIR   export cache (default: ~/.cache/secgui)
  SECGUI_NAVAL_RUN   naval run directory
  SECGUI_BIN         GUI executable
EOF
}

resolve_input() {
	local path="$1"
	if [[ "$path" != /* ]]; then
		if [ -e "$path" ]; then
			path="$(cd "$(dirname "$path")" && pwd)/$(basename "$path")"
		else
			path="$CORE/$path"
		fi
	fi
	printf '%s\n' "$path"
}

stamp() {
	local path
	for path in "$@"; do
		stat -c '%Y-%s' "$path" 2>/dev/null || echo 0
	done | sha256sum | cut -c1-16
}

export_scene() {
	local kind="$1" source="$2" trace="${3:-}" name_override="${4:-}"
	local name cache scene_dir tmp stamp_value
	name="$(basename "$source")"
	name="${name%.json}"
	name="${name%.json5}"
	if [ "$kind" = "run" ]; then
		stamp_value="$(stamp "$source/gui_run.json" \
			"$source/gui_state.csv" "$source/gui_links.csv" \
			"$source/simulation_dataset.json" "$source/tasks.jsonl")"
	else
		stamp_value="$(stamp "$source" "$trace")"
	fi
	if [ -n "$name_override" ]; then
		cache="$CACHE/scenes/$name_override"
	else
		cache="$CACHE/scenes/$name-$stamp_value"
	fi
	if [ ! -f "$cache/simulation.secsim" ] \
		|| [ "$(cat "$cache/.stamp" 2>/dev/null || true)" != "$stamp_value" ]; then
		tmp="$cache.tmp.$$"
		rm -rf "$tmp"
		mkdir -p "$CACHE/scenes"
		echo "run_gui: exporting $source -> $cache" >&2
		if [ "$kind" = "run" ]; then
			(cd "$CORE" && python3 tools/export_gui_scene.py \
				--run-dir "$source" --out "$tmp") 1>&2
		else
			local trace_args=()
			if [ -n "$trace" ]; then
				trace_args=(--trace "$trace")
			fi
			(cd "$CORE" && python3 tools/export_gui_scene.py \
				--config "$source" --core-config config/config.json5 \
				--out "$tmp" "${trace_args[@]}") 1>&2
		fi
		printf '%s\n' "$stamp_value" >"$tmp/.stamp"
		rm -rf "$cache"
		mv "$tmp" "$cache"
	fi
	scene_dir="$cache"
	printf '%s\n' "$scene_dir/simulation.secsim"
}

mode="base"
config_path=""
trace_path=""
run_path=""
gui_path=""
forward=()
while [ $# -gt 0 ]; do
	case "$1" in
		--config)
			[ $# -ge 2 ] || { echo "error: --config requires a path" >&2; exit 2; }
			config_path="$2"; shift 2 ;;
		--trace)
			[ $# -ge 2 ] || { echo "error: --trace requires a path" >&2; exit 2; }
			trace_path="$2"; shift 2 ;;
		--run)
			[ $# -ge 2 ] || { echo "error: --run requires a directory" >&2; exit 2; }
			run_path="$2"; shift 2 ;;
		--naval) mode="naval"; shift ;;
		--base) mode="base"; shift ;;
		--empty) mode="empty"; shift ;;
		--minimal) mode="minimal"; shift ;;
		--gui)
			[ $# -ge 2 ] || { echo "error: --gui requires a path" >&2; exit 2; }
			gui_path="$2"; shift 2 ;;
		-h|--help) usage; exit 0 ;;
		*) forward+=("$1"); shift ;;
	esac
done

if [ -n "$gui_path" ]; then
	GUI_LAUNCHER="$gui_path"
fi
[ -x "$GUI_LAUNCHER" ] || {
	echo "error: GUI launcher not found: $GUI_LAUNCHER" >&2
	exit 1
}

if [ -n "$trace_path" ] && [ -z "$config_path" ]; then
	echo "error: --trace requires --config" >&2
	exit 2
fi
if [ -n "$config_path" ] && [ -n "$run_path" ]; then
	echo "error: --config and --run are mutually exclusive" >&2
	exit 2
fi
if [ "$mode" = "naval" ] && { [ -n "$config_path" ] || [ -n "$run_path" ]; }; then
	echo "error: --naval cannot be combined with --config or --run" >&2
	exit 2
fi

scene_file=""
if [ -n "$config_path" ]; then
	config_path="$(resolve_input "$config_path")"
	[ -f "$config_path" ] || { echo "error: config not found: $config_path" >&2; exit 1; }
	if [ -n "$trace_path" ]; then
		trace_path="$(resolve_input "$trace_path")"
		[ -f "$trace_path" ] || { echo "error: trace not found: $trace_path" >&2; exit 1; }
	fi
	scene_file="$(export_scene config "$config_path" "$trace_path")"
	vessel="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("vessel_name") or "")' "$config_path" 2>/dev/null || true)"
	if [ -n "$vessel" ]; then
		has_camera=false
		has_target=false
		for arg in "${forward[@]}"; do
			[ "$arg" = "--camera" ] && has_camera=true
			[ "$arg" = "--target" ] && has_target=true
		done
		if ! $has_camera; then
			forward+=(--camera vessel)
		fi
		if ! $has_target; then
			forward+=(--target "$vessel")
		fi
	fi
elif [ -n "$run_path" ]; then
	run_path="$(resolve_input "$run_path")"
	[ -f "$run_path/gui_run.json" ] || {
		echo "error: gui_run.json not found in $run_path" >&2
		exit 1
	}
	scene_file="$(export_scene run "$run_path")"
elif [ "$mode" = "naval" ]; then
	run_path="${SECGUI_NAVAL_RUN:-}"
	if [ -z "$run_path" ]; then
		for candidate in "$CORE/result/naval/IN_NETWORK/optimal" \
		                 "$CORE/result/naval/TO_OBSERVER/optimal"; do
			if [ -f "$candidate/gui_run.json" ]; then
				run_path="$candidate"
				break
			fi
		done
	fi
	if [ -n "$run_path" ] && [ -f "$run_path/gui_run.json" ]; then
		scene_file="$(export_scene run "$run_path" "" naval)"
		forward=(--camera vessel --target V-ATLANTIC "${forward[@]}")
	else
		exec "$GUI_LAUNCHER" --naval "${forward[@]}"
	fi
elif [ "$mode" = "empty" ]; then
	exec "$GUI_LAUNCHER" --empty "${forward[@]}"
elif [ "$mode" = "minimal" ]; then
	exec "$GUI_LAUNCHER" --minimal "${forward[@]}"
fi

if [ -z "$scene_file" ]; then
	base="$CACHE/base"
	if [ -f "$base/simulation.secsim" ]; then
		scene_file="$base/simulation.secsim"
	elif [ -f "$base/manifest.json" ]; then
		scene_file="$base/manifest.json"
	else
		tmp="$base.tmp.$$"
		rm -rf "$tmp"
		mkdir -p "$CACHE"
		echo "run_gui: generating TLE base scene" >&2
		(cd "$CORE" && python3 tools/export_base_scene.py \
			--tle data/tle_data.txt --out "$tmp" \
			--interval 5 --duration 300) 1>&2
		rm -rf "$base"
		mv "$tmp" "$base"
		scene_file="$base/simulation.secsim"
	fi
	forward=(--camera orbit --layer isl=off --layer dome=off \
		--layer route=off "${forward[@]}")
fi

exec "$GUI_LAUNCHER" "$scene_file" "${forward[@]}"
