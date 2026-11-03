import os
import json
import sys
from typing import Tuple, Dict, List, Optional, Any
import numpy as np

from skyfield.timelib import Time
from skyfield.toposlib import GeographicPosition
from skyfield.api import EarthSatellite, load

from enums import AccPointMode, Topology, tle_data, GenConfigsOutput
from globals import config
from tqdm import tqdm
from topology.core import (
    find_satellite_events, getSystemFromSat, are_satellites_equal, get_pos_proximity, 
    get_orbit_proximity, build_topology_network, create_satellite_Identity_card,
    getLatency, advance_time, getAllSatOnMe, find_angle
)
from topology.Satellite import Satellite
from topology.core import filterSatellitesInView
from utils import colorize

from BaseTerminal import BaseTerminal
from NavalOrbit.Vessel import Vessel
from Observer import Observer

def getAllSatOnLine(
    t: Time,
    tle_data,
    vessel: BaseTerminal,
    observer: BaseTerminal,
    corridor_deg: float = config["corridor_angle"],
    Phi_max: int = config["Phi_max"],
    Buffer_zone: int = config["Phi_buffer"],
    ap_mode: AccPointMode = AccPointMode.BASE,
    num_acc_point: int = config["access_point"],
) -> Tuple[Topology, Dict[str, List[str]]]:
    """
    Return all satellites between vessel and observer at time t,
    along with the selected Access Points dictionary for each terminal.

    Args:
        t (Time): Skyfield time object.
        tle_data (tle_data): Loaded TLE satellite records.
        vessel (BaseTerminal): First terminal endpoint (Vessel).
        observer (BaseTerminal): Second terminal endpoint (Observer).
        corridor_deg (float, optional): Corridor angle half-width in degrees.
        Phi_max (int, optional): Maximum elevation angle for buffer zone.
        Buffer_zone (int, optional): Buffer zone angle in degrees above A and B.
        ap_mode (AccPointMode, optional): Access Point selection policy (BASE or OPTIMAL).
        num_acc_point (int, optional): Number of access points to select per endpoint.

    Returns:
        Tuple[Topology, Dict[str, List[str]]]:
            - Topology: List of Satellite objects in the corridor / dome.
            - Dict[str, List[str]]: Mapping from terminal name to list of elected AP satellite names.

    Raises:
        TypeError: If vessel or observer are not instances of BaseTerminal.
    """
    if not isinstance(vessel, BaseTerminal) or not isinstance(observer, BaseTerminal):
        raise TypeError("Both vessel and observer must be instances of BaseTerminal.")

    pos_A = vessel.position
    pos_B = observer.position
    name_A = vessel.name
    name_B = observer.name
    
    corridor_rad = np.radians(corridor_deg)  
    BZED = Phi_max - Buffer_zone 
    BZED_rad = np.radians(BZED)
    
    # 1. Calcolo vettori osservatori (Geocentrici)
    vA_km = pos_A.at(t).position.km
    vB_km = pos_B.at(t).position.km

    # Normalizzati (Vettori Zenit)
    vA = vA_km / np.linalg.norm(vA_km)
    vB = vB_km / np.linalg.norm(vB_km)

    # Gestione caso A = B
    if np.linalg.norm(vA - vB) < 1e-7:
        dome, sat_sort_buff = getAllSatOnMe(t, tle_data, ap_mode, Phi_max=Phi_max, Num_Access_point=num_acc_point)
        sat_on_line = dome + sat_sort_buff
        for s in sat_on_line:
            s.elev = find_angle(t, s.satellite, pos_A)
        access_points_dict = {
            name_A: [s.name for s in dome if s.is_acc_point]
        }
        return sat_on_line, access_points_dict

    # 2. Costruzione del piano del corridoio
    cross_prod = np.cross(vA, vB) 
    norm = np.linalg.norm(cross_prod) 

    # Caso limite: A e B opposti
    if norm < 1e-7:
        v_ref = np.array([0, 0, 1]) 
        if np.linalg.norm(np.cross(vA, v_ref)) < 1e-7:
            v_ref = np.array([1, 0, 0])
        cross_prod = np.cross(vA, v_ref)
        norm = np.linalg.norm(cross_prod)

        if norm < 1e-7:
            sys.exit(colorize("[ERROR]: Non è possibile definire un piano per A e B !!! Verifica i dati di input. ", "red"))

    # Vettore normale del piano e "Muri"
    n = cross_prod / norm
    nA = np.cross(n, vA)
    nB = np.cross(vB, n)

    # 3. FASE ACQUISIZIONE (Single pass over TLE data)
    sat_on_line = []
    cand_A: List[Tuple[float, Satellite]] = []
    cand_B: List[Tuple[float, Satellite]] = []

    ts = load.timescale()
    for i in range(0, len(tle_data), 3):
        name = tle_data[i].strip()
        line1 = tle_data[i + 1].strip()
        line2 = tle_data[i + 2].strip()

        # Creazione satellite e calcolo posizione orbitale
        satellite = EarthSatellite(line1, line2, name, ts)
        vP_km = satellite.at(t).position.km  
        vP = vP_km / np.linalg.norm(vP_km)  

        # --- FASE 1: Verifica Corridoio Centrale ---
        theta = np.arcsin(abs(np.clip(np.dot(n, vP), -1.0, 1.0)))
        in_corridor_inf = theta < corridor_rad
        between_walls = np.dot(vP, nA) >= 0 and np.dot(vP, nB) >= 0

        # --- FASE 2: Verifica Cupole (Metodo Topocentrico Vettoriale) ---
        top_A = vP_km - vA_km
        dist_A = float(np.linalg.norm(top_A))
        top_A_norm = top_A / dist_A
        alt_A_rad = float(np.arcsin(np.clip(np.dot(top_A_norm, vA), -1.0, 1.0)))

        top_B = vP_km - vB_km
        dist_B = float(np.linalg.norm(top_B))
        top_B_norm = top_B / dist_B
        alt_B_rad = float(np.arcsin(np.clip(np.dot(top_B_norm, vB), -1.0, 1.0)) )

        in_dome_A = alt_A_rad > BZED_rad
        in_dome_B = alt_B_rad > BZED_rad

        # Unione logica: corridoio o cupola A o cupola B
        if (in_corridor_inf and between_walls) or in_dome_A or in_dome_B:
            sat_obj = Satellite(satellite, dist_A, (name, line1, line2), False)
            sat_obj.elev = float(np.degrees(alt_A_rad))
            sat_on_line.append(sat_obj)

            if in_dome_A:
                cand_A.append((dist_A, sat_obj))
            if in_dome_B:
                cand_B.append((dist_B, sat_obj))

    # Ordina solo le micro-liste di candidati zenitali (~10-15 elementi per cupola)
    cand_A.sort(key=lambda item: item[0])
    cand_B.sort(key=lambda item: item[0])

    # Selezione AP per il Capo A (Nave)
    ap_names_A: List[str] = []
    for _, sat in cand_A:
        if len(ap_names_A) >= num_acc_point:
            break
        can_take = (
            ap_mode == AccPointMode.BASE
            or (ap_mode == AccPointMode.OPTIMAL and filterSatellitesInView(pos_A, sat.satellite, t))
        )
        if can_take:
            sat.is_acc_point = True
            ap_names_A.append(sat.name)

    # Selezione AP per il Capo B (Observer / Ground)
    ap_names_B: List[str] = []
    for _, sat in cand_B:
        if len(ap_names_B) >= num_acc_point:
            break
        can_take = (
            ap_mode == AccPointMode.BASE
            or (ap_mode == AccPointMode.OPTIMAL and filterSatellitesInView(pos_B, sat.satellite, t))
        )
        if can_take:
            sat.is_acc_point = True
            ap_names_B.append(sat.name)

    access_points_dict: Dict[str, List[str]] = {
        name_A: ap_names_A,
        name_B: ap_names_B,
    }

    return sat_on_line, access_points_dict


# ---------------------------------------------------------------------------- #


def genConfigs_line(
    t0: Time,
    interval: int,
    num_configs: int,
    tle_data: tle_data,
    json_path: str,
    mode: AccPointMode,
    vessel: Vessel,
    observer: Observer,
) -> GenConfigsOutput:
    """
    Questa funzione costruisce configurazioni dati due punti A e B.
    Crea 'num_configs' configurazioni ogni 'interval' di tempo a partire dal
    momento 't0'. Usa 'tle_data' per sapere la posizione dei satelliti.
    Salva tutto nel file json in 'json_path'.
    
    Access Point are selected respect the object A.
    
    Args:
        t0 (Time): Initial time for generating configurations.
        interval (int): Time interval (in seconds) between each configuration.
        num_configs (int): Total number of configurations to generate.
        tle_data (tle_data): TLE data for satellite positions.
        json_path (str): Path to save the generated configurations in JSON format.
        mode (AccPointMode): Mode for access point selection.
        vessel (Vessel): istance of an object the world.
        observer (Observer): istance of an object the world.
    Returns:
        GenConfigsOutput: An object containing the generated configurations and related metadata.
    """
    t, configs = t0, [] # Initialize time and configuration list
    totSecs = num_configs * interval # Total duration in seconds
    
    print(colorize(f"[{mode}] Generazione Configurazioni Navali (TARGET : {vessel}):", "yellow"))
    for elapsed_time in tqdm(range(0, totSecs, interval), desc="Progresso", ncols=80):
        step_index = elapsed_time // interval + 1
        
        line_conf = [] # Initialize configuration for the current time step
        
        line, access_points_dict = getAllSatOnLine(
            t,
            tle_data,
            vessel,
            observer,
            ap_mode=mode,
        )
        line_map = build_topology_network(line, t)
        
        phi_max = config["Phi_max"]
        for satellite in line:
            neighbors_info = line_map.get(satellite.name, [])
            
            alt_obs = find_angle(t, satellite.satellite, observer.position)

            if satellite.elev > phi_max:
                # Satellite nella cupola della Nave (A)
                terminal_ref = vessel.name
                elev_val = satellite.elev
                life = find_satellite_events(
                    satellite.satellite, t, ground_reference_point=vessel.position
                )
            elif alt_obs > phi_max:
                # Satellite nella cupola dell'Observer (B)
                terminal_ref = observer.name
                elev_val = alt_obs
                life = find_satellite_events(
                    satellite.satellite, t, ground_reference_point=observer.position
                )
            else:
                # Satellite di transito nel corridoio (sotto la cupola di entrambi)
                terminal_ref = None
                elev_val = satellite.elev
                life = {
                    "AOS": None,
                    "Max-El": None,
                    "LOS": None,
                    "life_seconds": None,
                    "time_until_set_seconds": None,
                }

            info_sat = create_satellite_Identity_card(
                satellite, life, neighbors_info, t, satellite.is_acc_point, line_setup=True
            )
            info_sat["elev_angle"] = elev_val
            info_sat["terminal_ref"] = terminal_ref
            line_conf.append(info_sat)
            
        data = {
            "time": t.utc_datetime().isoformat(),
            "step_index": step_index,
            "vessel_position": {
                "lat": vessel.position.latitude.degrees,
                "lon": vessel.position.longitude.degrees,
            },
            "access_points": access_points_dict,
            "configuration": line_conf,
        }
        configs.append(data)
        t = advance_time(t, interval / 60)
        
    output = {
        "t0": t0.utc_datetime().isoformat(),
        "interval": interval,
        "total_seconds": totSecs,
        "observer_position": observer.location_name,
        "vessel_name": vessel.name,
        "configurations": configs,
    }
    
    try:
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(output, f, indent=4)
        print(colorize(f"[Naval Topology] File salvato con successo in '{json_path}'", "green"))
    except IOError as e:
        print(colorize(f"Errore nel salvataggio del file: {e}", "red"))

    return output


def build_naval_configurations(
    t0: Time,
    tle_data: tle_data,
    mode: AccPointMode,
    observer: Observer,
    vessel: Vessel,
    interval: int = None,
    num_configs: int = None,
) -> GenConfigsOutput:
    """
    Costruisce e salva le configurazioni navali nel tempo per la modalità data (BASE o OPTIMAL).
    """
    config_interval = interval if interval is not None else config.get("Interval_between_Configurations_in_seconds", 120)
    if num_configs is not None:
        tot_config = num_configs
    else:
        tot_duration = config.get("simulation_duration", 300) + config.get("adding_time", 30)
        tot_config = int(tot_duration / config_interval)
    
    config_path = f"data/naval_configurations_AP_{mode}.json"

    configurations = genConfigs_line(
        t0=t0,
        interval=config_interval,
        num_configs=tot_config,
        tle_data=tle_data,
        json_path=config_path,
        mode=mode,
        observer=observer,
        vessel=vessel,
    )
    return configurations


def load_saved_naval_configuration(mode: AccPointMode) -> GenConfigsOutput:
    """
    Carica le configurazioni navali salvate nel file JSON.
    """
    path = f"data/naval_configurations_AP_{mode}.json"
    configuration = None
    print(colorize(f"[LOAD] Caricamento configurazione navale <{mode}>...", "yellow"))

    try:
        with open(path, "r") as f:
            configuration = json.load(f)
    except Exception as e:
        sys.exit(colorize(f"[LOAD] Errore durante il caricamento delle configurazioni navali: {e}", "red"))

    print(colorize(f"[LOAD] Configurazione navale <{mode}> caricata con successo.", "green"))
    return configuration


