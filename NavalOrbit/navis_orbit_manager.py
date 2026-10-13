import sys
import json5
import numpy as np
import globals
from utils import colorize
from enums import NavalRules
from Observer import Observer_Temp

from skyfield.api import load, wgs84

from NavalOrbit.Vessel import generate_vessel
from NavalOrbit.naval_topology import genConfigs_line, getAllSatOnLine
from NavalOrbit.orbital_plotters import plot_orbital_corridor

from NavalOrbit.Vessel import DistanceRange, ScenarioDistances
from topology.core import openTLEFromFile, build_topology_network


def load_obs_settings(file_path: str = "config/config.json5") -> Observer_Temp:
    """
    This function loads observer settings from a JSON5 configuration file and returns an Observer instance.
    Args:
        file_path (str): The path to the configuration file.

    Returns:
        Observer: An instance of the Observer class.
    """
    with open(file_path, "r") as file:
        data = json5.load(file)
        location = data["locations"]["Roma"]
        observer = Observer_Temp(
            loc_name="Roma",
            position=wgs84.latlon(location.get("lat"), location.get("lon")),
        )
        return observer

def exp_1_test():
    """
    Plot the orbital corridor between an observer and a vessel using TLE data.
    """
    
    observer = load_obs_settings()
    vessel = generate_vessel(
        rule=NavalRules.GLOBAL,
        )
    print(colorize(f"[DEBUG] Generated vessel: {vessel}", "cyan"))
    
    tle_data = openTLEFromFile()
    ts = load.timescale()
    t0 = ts.now()

    sats = getAllSatOnLine(
        t=t0, 
        tle_data=tle_data, 
        Observer=observer, 
        Vessel=vessel,
        corridor_deg=10.0
    )
    
    plot_orbital_corridor(sats, observer.position, vessel.position, t0, 10.0)

from datetime import timedelta
from NavalOrbit.temp_greedy_routing import simulate_greedy_hops

def exp_2_test(times_iter: int = 10):
    scenarios = {
        "NEAR": [],
        "MEDIUM": [],
        "FAR": []
    }
    
    observer = load_obs_settings()
    
    ts = load.timescale()
    t0 = ts.now()
    tle_data = openTLEFromFile()    
    base_datetime = t0.utc_datetime()
    
    for i in range(times_iter): 
        new_datetime = base_datetime + timedelta(hours=i)
        ts_now = ts.from_datetime(new_datetime)
        
        print(colorize(f"--- Simulating Hour {i} ---", "blue"))
        
        # Generazione navi
        vessel_scen_near = generate_vessel(
            rule=NavalRules.RADIUS,
            distance_range=ScenarioDistances.NEAR,
            observer_pos=observer
        )
        vessel_scen_medium = generate_vessel(
            rule=NavalRules.RADIUS,
            distance_range=ScenarioDistances.MEDIUM,
            observer_pos=observer
        )
        vessel_scen_far = generate_vessel(
            rule=NavalRules.RADIUS,
            distance_range=ScenarioDistances.FAR,
            observer_pos=observer
        )

        # Calcolo lista satelliti
        sats_near = getAllSatOnLine(t=ts_now, tle_data=tle_data, Observer=observer, Vessel=vessel_scen_near, corridor_deg=10.0)
        sats_medium = getAllSatOnLine(t=ts_now, tle_data=tle_data, Observer=observer, Vessel=vessel_scen_medium, corridor_deg=10.0)
        sats_far = getAllSatOnLine(t=ts_now, tle_data=tle_data, Observer=observer, Vessel=vessel_scen_far, corridor_deg=10.0)

        # Costruzione dei grafi topologici
        graph_near = build_topology_network(sats_near, ts_now)
        graph_medium = build_topology_network(sats_medium, ts_now)
        graph_far = build_topology_network(sats_far, ts_now)

        # Identificazione Access Point per l'osservatore
        ap_near = next((sat.name for sat in sats_near if sat.is_acc_point), sats_near[0].name if sats_near else None)
        ap_medium = next((sat.name for sat in sats_medium if sat.is_acc_point), sats_medium[0].name if sats_medium else None)
        ap_far = next((sat.name for sat in sats_far if sat.is_acc_point), sats_far[0].name if sats_far else None)

        # Simulazione routing greedy
        if ap_near:
            hops_near, path_near = simulate_greedy_hops(sats_near, graph_near, ap_near, vessel_scen_near, ts_now)
            scenarios["NEAR"].append(hops_near)
            if hops_near == -1:
                sat_dict = {sat.name: sat.satellite for sat in sats_near}
                lat_dead_end = wgs84.subpoint_of(sat_dict[path_near[-1]].at(ts_now)).latitude.degrees
                lat_vessel = vessel_scen_near.position.latitude.degrees
                print(colorize(f"[ANALISI FALLIMENTO] Scenario NEAR: Vicolo cieco a Latitudine {lat_dead_end:.2f}° (Nave a {lat_vessel:.2f}°)", "red"))
                plot_orbital_corridor(sats_near, observer.position, vessel_scen_near.position, ts_now, 10.0, show_footprints=True, routing_path=path_near)
                
        if ap_medium:
            hops_medium, path_medium = simulate_greedy_hops(sats_medium, graph_medium, ap_medium, vessel_scen_medium, ts_now)
            scenarios["MEDIUM"].append(hops_medium)
            if hops_medium == -1:
                sat_dict = {sat.name: sat.satellite for sat in sats_medium}
                lat_dead_end = wgs84.subpoint_of(sat_dict[path_medium[-1]].at(ts_now)).latitude.degrees
                lat_vessel = vessel_scen_medium.position.latitude.degrees
                print(colorize(f"[ANALISI FALLIMENTO] Scenario MEDIUM: Vicolo cieco a Latitudine {lat_dead_end:.2f}° (Nave a {lat_vessel:.2f}°)", "red"))
                plot_orbital_corridor(sats_medium, observer.position, vessel_scen_medium.position, ts_now, 10.0, show_footprints=True, routing_path=path_medium)
                
        if ap_far:
            hops_far, path_far = simulate_greedy_hops(sats_far, graph_far, ap_far, vessel_scen_far, ts_now)
            scenarios["FAR"].append(hops_far)
            if hops_far == -1:
                sat_dict = {sat.name: sat.satellite for sat in sats_far}
                lat_dead_end = wgs84.subpoint_of(sat_dict[path_far[-1]].at(ts_now)).latitude.degrees
                lat_vessel = vessel_scen_far.position.latitude.degrees
                print(colorize(f"[ANALISI FALLIMENTO] Scenario FAR: Vicolo cieco a Latitudine {lat_dead_end:.2f}° (Nave a {lat_vessel:.2f}°)", "red"))
                plot_orbital_corridor(sats_far, observer.position, vessel_scen_far.position, ts_now, 10.0, show_footprints=True, routing_path=path_far)

    # Calcolo medie e stampe
    print("\n--- RESULTS ---")
    for scenario_name, hops_list in scenarios.items():
        valid_hops = [h for h in hops_list if h != -1]
        failures = hops_list.count(-1)
        avg_hops = sum(valid_hops) / len(valid_hops) if valid_hops else 0
        print(colorize(f"Scenario {scenario_name}: Avg Hops = {avg_hops:.2f} (Failures = {failures}/{times_iter})", "green"))


if __name__ == "__main__":
    exp_2_test()
