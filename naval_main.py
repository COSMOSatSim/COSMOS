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
from enums import AccPointMode, NavalRules
from utils import colorize
from topology.core import (
    openTLEFromFile, saveTLEOnFile, get_current_time,
    loadConfiguration, periodic_recall_Topology_monitor
)
from routing.routing_engine import routing_simulation_process
from Observer import Observer_Temp
from NavalOrbit.navis_orbit_manager import load_obs_settings
from NavalOrbit.Vessel import Vessel, generate_vessel, ScenarioDistances
from NavalOrbit.naval_topology import (
    build_naval_configurations,
    load_saved_naval_configuration
)


def parse_arguments():
    parser = argparse.ArgumentParser(description="SECMotionModel Naval Simulation Entry Point")
    parser.add_argument(
        "--num-configs",
        type=int,
        default=10,
        help="Number of configuration timesteps to generate (default: 10)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=globals.config.get("Interval_between_Configurations_in_seconds", 2),
        help="Time interval between configurations in seconds (default: 2)"
    )
    parser.add_argument(
        "--distance-scenario",
        type=str,
        default="MEDIUM",
        choices=["NEAR", "MEDIUM", "FAR"],
        help="Initial distance scenario for the vessel relative to observer"
    )
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
        "--sim-duration",
        type=float,
        default=30.0,
        help="Simulation duration in seconds when running simulation (default: 30.0)"
    )
    return parser.parse_args()


def get_scenario_distance(scenario_name: str):
    if scenario_name == "NEAR":
        return ScenarioDistances.NEAR
    elif scenario_name == "FAR":
        return ScenarioDistances.FAR
    else:
        return ScenarioDistances.MEDIUM


def main():
    # 1. SimPy environment and configuration setup
    args = parse_arguments()
    start_real_time = time.time()
    config, resolution_config = globals.config, globals.resolution_config
    env = simpy.Environment()

    print(colorize("\n" + "=" * 70, "cyan"))
    print(colorize("       SECMotionModel - Naval Simulation & Topology Setup", "cyan"))
    print(colorize("=" * 70 + "\n", "cyan"))

    configs_base = None
    configs_optimal = None

    if args.load_only:
        print(colorize("[MODE] Caricamento configurazioni navali esistenti...", "yellow"))
        configs_base = load_saved_naval_configuration(AccPointMode.BASE)
        configs_optimal = load_saved_naval_configuration(AccPointMode.OPTIMAL)

        conf_ref = configs_optimal if configs_optimal else configs_base
        v_name = conf_ref.get("vessel_name", "V-LOADED")
        first_step = conf_ref.get("configurations", [{}])[0]
        pos_dict = first_step.get("vessel_position", {"lat": 0.0, "lon": 0.0})
        vessel = Vessel(v_name, wgs84.latlon(pos_dict["lat"], pos_dict["lon"]), env=env)
    else:
        print(colorize("[INFO] Building new naval configurations...", "yellow"))        
        tle_data = openTLEFromFile(_dir="./NavalOrbit/data")
        t0 = get_current_time()
        
        observer = load_obs_settings()
        distance_range = get_scenario_distance(args.distance_scenario)
        vessel = generate_vessel(
            rule=NavalRules.RADIUS,
            distance_range=distance_range,
            observer_pos=observer
        )
        
        # Build BASE configuration
        configs_base = build_naval_configurations(
            t0=t0,
            tle_data=tle_data,
            mode=AccPointMode.BASE,
            vessel=vessel,
            observer=observer,
            num_configs=args.num_configs,
            interval=args.interval
        )

        # Build OPTIMAL configuration
        configs_optimal = build_naval_configurations(
            t0=t0,
            tle_data=tle_data,
            mode=AccPointMode.OPTIMAL,
            vessel=vessel,
            observer=observer,
            num_configs=args.num_configs,
            interval=args.interval
        )
        
        

    # 5. Summary and Verification
    print(colorize("\n" + "-" * 70, "cyan"))
    print(colorize("                    GENERATION SUMMARY", "cyan"))
    print(colorize("-" * 70, "cyan"))
    
    conf_base_list = configs_base.get("configurations", [])
    conf_opt_list = configs_optimal.get("configurations", [])

    print(f"Total BASE configurations:    {len(conf_base_list)}")
    print(f"Total OPTIMAL configurations: {len(conf_opt_list)}")

    if conf_base_list and conf_opt_list:
        step0_base = conf_base_list[0]
        step0_opt = conf_opt_list[0]
        
        aps_base = [s["satellite"] for s in step0_base.get("configuration", []) if s.get("is_access_point")]
        aps_opt = [s["satellite"] for s in step0_opt.get("configuration", []) if s.get("is_access_point")]
        
        print(f"\nStep 0 ({step0_base.get('time')}):")
        print(f"  - Satellites on corridor line: {len(step0_base.get('configuration', []))}")
        print(f"  - APs (BASE) covering vessel:    {aps_base}")
        print(f"  - APs (OPTIMAL) covering vessel: {aps_opt}")

    elapsed_real = time.time() - start_real_time
    print(colorize(f"\nNaval simulation setup completed in {elapsed_real:.2f} seconds.", "green"))
    print(colorize("Files written to:", "green"))
    print(f"  - data/naval_configurations_AP_base.json")
    print(f"  - data/naval_configurations_AP_optimal.json")
    print(colorize("=" * 70 + "\n", "cyan"))

    # 6. Naval SimPy Simulation Execution
    if args.run_sim:
        print(colorize("\n" + "=" * 70, "cyan"))
        print(colorize("       SECMotionModel - Running Naval SimPy Simulation (Use Case 1)", "cyan"))
        print(colorize("=" * 70 + "\n", "cyan"))

        configs = configs_optimal if configs_optimal else configs_base
        globals.data_configurations = configs

        globals.edge_servers, globals.global_access_point = loadConfiguration(
            env, globals.data_configurations, globals.OGMs_tables
        )
        env.process(periodic_recall_Topology_monitor(env, globals.data_configurations, globals.OGMs_tables))
        env.process(routing_simulation_process(env))

        globals.initial_server_counter = {server.name: 0 for server in globals.edge_servers}
        globals.different_server_counter = {server.name: 0 for server in globals.edge_servers}
        globals.other_server_counter = {server.name: 0 for server in globals.edge_servers}

        # Start continuous task generation with destination = vessel
        env.process(simulation.generate_tasks(
            env,
            globals.initial_server_counter,
            globals.different_server_counter,
            globals.other_server_counter,
            destination=vessel
        ))

        print(colorize(f"[SIM] Running SimPy simulation for {args.sim_duration}s...", "yellow"))
        env.run(until=args.sim_duration)
        print(colorize(f"[SIM] Completed {args.sim_duration}s simulation run!\n", "green"))

        vessel.print_task_summary()


if __name__ == "__main__":
    main()
