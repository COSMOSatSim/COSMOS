import os
import json
import sys
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

from NavalOrbit.Vessel import Vessel
from Observer import Observer

def getAllSatOnLine(
    t: Time,
    tle_data,
    pos_A: GeographicPosition,
    pos_B: GeographicPosition,
    corridor_deg: float = config["corridor_angle"],
    Phi_max: int = config["Phi_max"],
    Buffer_zone: int = config["Phi_buffer"],
    ap_mode: AccPointMode = AccPointMode.BASE,
    num_acc_point: int = config["access_point"],
) -> Topology:
    """
    This function return all satellites between a given point A,
    and a given point B, in a specific time t.
    It use the TLE data to find all satellites in the line of sight between A and B,
    including the dome/buffer zone exactly above A and B.
    
    It find the Access Points (AP) on the object A. 
    
    Args:
        t (Time): The time at which to evaluate satellite positions.
        tle_data (tle_data): TLE data for satellite positions.
        Obj_A (GeographicPosition): The first geographic position (e.g., Observer).
        Obj_B (GeographicPosition): The second geographic position (e.g., Vessel).
        corridor_deg (float): The corridor angle in degrees for satellite selection.
        Phi_max (int): Maximum elevation angle for the buffer zone.
        Buffer_zone (int): Buffer zone angle in degrees above A and B.
        ap_mode (AccPointMode): Mode for access point selection (BASE or OPTIMAL).
        num_acc_point (int): Number of access points to select.
    Returns:
        Topology: A list of Satellite objects that are between points A and B.
    """
    
    if not isinstance(pos_A, GeographicPosition) or not isinstance(pos_B, GeographicPosition):
        raise ValueError("Both pos_A or pos_B must be instances of GeographicPosition.")
    
    corridor_rad = np.radians(corridor_deg)  
    BZED = Phi_max - Buffer_zone 
    BZED_rad = np.radians(BZED) # Convertito una volta sola fuori dal ciclo
    
    sat_on_line = [] 
    
    # 1. Calcolo vettori osservatori (Geocentrici)
    vA_km = pos_A.at(t).position.km
    vB_km = pos_B.at(t).position.km

    # Normalizzati (Vettori Zenit)
    vA = vA_km / np.linalg.norm(vA_km)
    vB = vB_km / np.linalg.norm(vB_km)

    # Gestione caso A = B
    if np.linalg.norm(vA - vB) < 1e-7:
        # Fallback se Observer e Vessel coincidono: usa la cupola a punto singolo
        dome, sat_sort_buff = getAllSatOnMe(t, tle_data, ap_mode, Phi_max=Phi_max, Num_Access_point=num_acc_point)
        sat_on_line = dome + sat_sort_buff
        for s in sat_on_line:
            s.elev = find_angle(t, s.satellite, pos_A)
        return sat_on_line

    else:
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

        # 3. FASE ACQUISIZIONE
        ts = load.timescale()
        for i in range(0, len(tle_data), 3):
            name = tle_data[i].strip()
            line1 = tle_data[i + 1].strip()
            line2 = tle_data[i + 2].strip()

            # Creazione satellite e calcolo posizione orbitale (LA PARTE PIÙ PESANTE, FATTA UNA VOLTA SOLA)
            satellite = EarthSatellite(line1, line2, name, ts)
            vP_km = satellite.at(t).position.km  
            vP = vP_km / np.linalg.norm(vP_km)  

            # --- FASE 1: Verifica Corridoio Centrale ---
            # Angolo rispetto al piano centrale
            theta = np.arcsin(abs(np.clip(np.dot(n, vP), -1.0, 1.0)))
            in_corridor_inf = theta < corridor_rad
            # Verifica che sia racchiuso tra A e B
            between_walls = np.dot(vP, nA) >= 0 and np.dot(vP, nB) >= 0

            # --- FASE 2: Verifica Cupole (Metodo Topocentrico Vettoriale) ---
            # Vettore da A al satellite
            top_A = vP_km - vA_km
            dist_A = np.linalg.norm(top_A)
            top_A_norm = top_A / dist_A
            alt_A_rad = np.arcsin(np.clip(np.dot(top_A_norm, vA), -1.0, 1.0))

            # Vettore da B al satellite
            top_B = vP_km - vB_km
            dist_B = np.linalg.norm(top_B)
            top_B_norm = top_B / dist_B
            alt_B_rad = np.arcsin(np.clip(np.dot(top_B_norm, vB), -1.0, 1.0))

            # --- UNIONE LOGICA ---
            # È valido se si trova nel corridoio OPPURE sopra l'orizzonte BZED di A OPPURE di B
            if (in_corridor_inf and between_walls) or (alt_A_rad > BZED_rad) or (alt_B_rad > BZED_rad):
                sat_obj = Satellite(satellite, dist_A, (name, line1, line2), False)
                sat_obj.elev = np.degrees(alt_A_rad)    # elevazione rispetto alla posizione A
                sat_on_line.append(sat_obj)
        
        
        # Order Satellite by distance from A
        sat_on_line.sort(key=lambda sat: sat.distance)
        
        if num_acc_point > len(sat_on_line):
            num_acc_point = len(sat_on_line) // 2 # Non ci sono abbastanza satelliti da usare come AP
            print(colorize(f"WARNING: Not enough satellites to satisfy the request. The number of access points has been set to {num_acc_point}.", "orange"))
        
        counter = 0 # Contatore degli access Point
        # Determino Access Points
        for sat in sat_on_line:
            if counter >= num_acc_point:
                # Ho tutti gli AP, posso uscire
                break
            
            # Check della modalità
            if ap_mode == AccPointMode.BASE:
                can_take = counter < num_acc_point
            elif ap_mode == AccPointMode.OPTIMAL:
                can_take = counter < num_acc_point and filterSatellitesInView(pos_A, sat.satellite, t)  # Filter based on the Object A's Position.
            else:
                can_take = False
            
            if can_take:
                sat.is_acc_point = True
                counter += 1
                
        return sat_on_line


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
        
        line = getAllSatOnLine(t, tle_data, vessel.position, observer.position, ap_mode=mode)
        line_map = build_topology_network(line, t)
        
        for satellite in line:
            neighbors_info = line_map.get(satellite.name, [])
            life = {
                "AOS": None,
                "Max-El": None,
                "LOS": None,
                "life_seconds": None,
                "time_until_set_seconds": None,
            }
            if satellite.elev > config["Phi_max"]:
                life = find_satellite_events(
                    satellite.satellite, t, ground_reference_point=vessel.position
                )  # Find events for the satellite
            
            info_sat = create_satellite_Identity_card(
                satellite, life, neighbors_info, t, satellite.is_acc_point, line_setup=True
            )
            info_sat["elev_angle"] = satellite.elev # Elevation angle respect object A
            line_conf.append(info_sat)
            
        data = {
            "time": t.utc_datetime().isoformat(),
            "step_index": step_index,
            "vessel_position": {
                "lat": vessel.position.latitude.degrees,
                "lon": vessel.position.longitude.degrees,
            },
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


