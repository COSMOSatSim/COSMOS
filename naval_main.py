"""
Entry point for naval simulation in SECMotionModel.

This script sets up the simulation environment for the naval use-case:
1. Loads TLE satellite data.
2. Initializes the terrestrial Observer (e.g. Rome).
3. Initializes a stationary Vessel (positioned relative to the Observer).
4. Generates both BASE and OPTIMAL satellite network configurations from the
   perspective of the Vessel (Access Points selected covering the ship).
5. Prepares the foundation for future vessel motion simulation and task routing.
"""

import argparse
import os
import sys
import time
import numpy as np
import simpy
from skyfield.api import wgs84

import globals
import simulation
from enums import AccPointMode, NavalUseCase
from utils import colorize
from topology.core import (
    openTLEFromFile, saveTLEOnFile, get_current_time,
    loadConfiguration, periodic_recall_Topology_monitor,
    get_global_mode
)
from routing.routing_engine import routing_simulation_process
from Observer import Observer_Temp
from NavalOrbit.navis_orbit_manager import load_obs_settings
from NavalOrbit.Vessel import Vessel
from NavalOrbit.naval_topology import (
    build_naval_configurations,
    load_saved_naval_configuration
)
from NavalOrbit.naval_relay_simulation import (
    generate_naval_relay_tasks,
    print_relay_diagnostic_summary
)


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments for the naval simulation.

    Returns:
        argparse.Namespace: Parsed command-line flags.
    """
    parser = argparse.ArgumentParser(description="SECMotionModel Naval Simulation Entry Point")
    parser.add_argument(
        "--load-only",
        action="store_true",
        help="Load existing saved naval configurations instead of building new ones"
    )
    parser.add_argument(
        "--run-sim",
        action="store_true",
        help="Run the SimPy simulation after topology generation/loading"
    )
    parser.add_argument(
        "--gui-export",
        action="store_true",
        help="Write gui_state.csv, gui_links.csv and gui_run.json for the GUI"
    )
    parser.add_argument(
        "--use-case",
        type=NavalUseCase,
        default=NavalUseCase.IN_NETWORK,
        choices=list(NavalUseCase),
        help="Naval use case to simulate: IN_NETWORK (tasks return to vessel) or TO_OBSERVER (tasks routed to observer)",
    )
    return parser.parse_args()


def main() -> None:
    """
    Main entry point for naval topology generation and simulation execution.
    """
    # 1. SimPy environment and configuration setup
    args = parse_arguments()
    start_real_time = time.time()
    config = globals.config
    env = simpy.Environment()
    observer = load_obs_settings()
    observer.env = env
    globals.observer = observer

    sim_duration = float(config.get("simulation_duration", 300.0))
    interval = int(config.get("Interval_between_Configurations_in_seconds", 2))
    num_configs = int(sim_duration / interval) if interval > 0 else 150
    ap_mode = get_global_mode()

    print(colorize("\n" + "=" * 70, "cyan"))
    print(colorize("       SECMotionModel - Naval Simulation & Topology Setup", "cyan"))
    print(colorize(f"       AP Mode: {ap_mode.value.upper()} | Sim Duration: {sim_duration}s ({num_configs} configs @ {interval}s)", "cyan"))
    print(colorize("=" * 70 + "\n", "cyan"))

    if args.load_only:
        print(colorize(f"[MODE] Caricamento configurazione navale esistente <{ap_mode.value}>...", "yellow"))
        configs = load_saved_naval_configuration(ap_mode)

        v_name = configs.get("vessel_name", "V-LOADED")
        first_step = configs.get("configurations", [{}])[0]
        pos_dict = first_step.get("vessel_position", {"lat": 0.0, "lon": 0.0})
        vessel = Vessel(v_name, wgs84.latlon(pos_dict["lat"], pos_dict["lon"]), env=env)
    else:
        print(colorize(f"[INFO] Building new naval configuration <{ap_mode.value}>...", "yellow"))        
        tle_data = openTLEFromFile(_dir="./NavalOrbit/data")
        t0 = get_current_time()
        
        # Coordinate fisse oceano Atlantico (No Poli, piena copertura Walker-Delta 53°)
        vessel = Vessel("V-ATLANTIC", wgs84.latlon(33.373586, -47.955604), env=env)
        
        configs = build_naval_configurations(
            t0=t0,
            tle_data=tle_data,
            mode=ap_mode,
            vessel=vessel,
            observer=observer,
            num_configs=num_configs,
            interval=interval
        )

    # Summary and Verification
    print(colorize("\n" + "-" * 70, "cyan"))
    print(colorize("                    GENERATION SUMMARY", "cyan"))
    print(colorize("-" * 70, "cyan"))
    
    conf_list = configs.get("configurations", [])
    print(f"Total configurations ({ap_mode.value.upper()}): {len(conf_list)}")

    if conf_list:
        step0 = conf_list[0]
        aps_dict = step0.get("access_points", {})
        print(f"\nStep 0 ({step0.get('time')}):")
        print(f"  - Satellites on corridor line: {len(step0.get('configuration', []))}")
        print(f"  - APs per-terminal ({ap_mode.value.upper()}): {aps_dict}")

    elapsed_real = time.time() - start_real_time
    print(colorize(f"\nNaval simulation setup completed in {elapsed_real:.2f} seconds.", "green"))
    print(colorize("File loaded/written:", "green"))
    print(f"  - data/naval_configurations_AP_{ap_mode.value}.json")
    print(colorize("=" * 70 + "\n", "cyan"))

    # Naval SimPy Simulation Execution
    if args.run_sim:
        print(colorize("\n" + "=" * 70, "cyan"))
        print(colorize(f"       SECMotionModel - Running Naval SimPy Simulation ({args.use_case.value})", "cyan"))
        print(colorize("=" * 70 + "\n", "cyan"))

        globals.data_configurations = configs

        globals.edge_servers = loadConfiguration(
            env, globals.data_configurations, globals.OGMs_tables
        )
        env.process(periodic_recall_Topology_monitor(env, globals.data_configurations, globals.OGMs_tables))
        env.process(routing_simulation_process(env))

        globals.initial_server_counter = {server.name: 0 for server in globals.edge_servers}
        globals.different_server_counter = {server.name: 0 for server in globals.edge_servers}
        globals.other_server_counter = {server.name: 0 for server in globals.edge_servers}

        if args.use_case == NavalUseCase.IN_NETWORK:
            dest_terminal = vessel
            source_terminal = None  # source defaults to destination in generate_tasks
            # Start continuous task generation with edge compute
            env.process(simulation.generate_tasks(
                env,
                globals.initial_server_counter,
                globals.different_server_counter,
                globals.other_server_counter,
                destination=dest_terminal,
                source=source_terminal,
            ))
        elif args.use_case == NavalUseCase.TO_OBSERVER:
            # Configura il pool di calcolo multi-core a terra sull'Observer
            ground_cores = int(config.get("ground_cpu_capacity", 10))
            observer.cpu_dev = simpy.Resource(env, capacity=ground_cores)
            dest_terminal = observer
            source_terminal = vessel
            # Start continuous relay task generation (zero satellite CPU)
            env.process(generate_naval_relay_tasks(
                env,
                source=source_terminal,
                destination=dest_terminal,
            ))
        else:
            raise ValueError(f"Unknown use case: {args.use_case}")

        gui_monitor = None
        if args.gui_export:
            from NavalOrbit.gui_monitor import (
                GuiMonitor,
                collect_gui_state,
                write_run_metadata,
            )

            gui_dir = f"result/naval/{args.use_case.value}/{ap_mode.value}"
            os.makedirs(gui_dir, exist_ok=True)
            sample_interval = float(config.get("gui_sample_interval", 0.5))
            gui_monitor = GuiMonitor(gui_dir, sample_interval, sim_duration)
            globals.gui_monitor = gui_monitor
            env.process(collect_gui_state(
                env, gui_monitor, sample_interval, sim_duration - interval
            ))
            write_run_metadata(
                gui_dir, config, args.use_case.value, ap_mode.value,
                configs.get("t0"), sim_duration, interval, sample_interval,
                f"data/naval_configurations_AP_{ap_mode.value}.json",
            )

        print(colorize(f"[SIM] Running SimPy simulation for {sim_duration}s (Use Case: {args.use_case.value}, AP: {ap_mode.value})...", "yellow"))
        try:
            env.run(until=sim_duration)
        finally:
            if gui_monitor is not None:
                gui_monitor.close()
                globals.gui_monitor = None
        print(colorize(f"[SIM] Completed {sim_duration}s simulation run!\n", "green"))

        dest_terminal.print_task_summary()
        if args.use_case == NavalUseCase.TO_OBSERVER:
            source_terminal.print_task_summary()
            print_relay_diagnostic_summary(source=source_terminal, destination=dest_terminal)

        # Generazione e salvataggio CSV dello stato di tutti i task (routing, coda, calcolo, RTT)
        from EdgeServer import build_task_csv_path
        from routing.task import generate_Tasks_Status

        base_dir = f"result/naval/{args.use_case.value}/{ap_mode.value}"
        os.makedirs(base_dir, exist_ok=True)
        atime = config.get("arrival_time_exponential", 0.5)
        cpu_mean = config.get("CPU_timeout", {}).get("gen", {}).get("mean", 0.05)
        csv_routing_task = build_task_csv_path(base_dir, atime, cpu_mean)
        print(colorize(f"\n[CSV] Generazione file stato task in {base_dir}...", "cyan"))
        generate_Tasks_Status(csv_routing_task, base_dir)


if __name__ == "__main__":
    main()
