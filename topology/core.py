"""
Module to fetch and save current TLE data of active satellites.

This module retrieves the latest TLE (Two-Line Element) data for active
satellites from Celestrak and saves it to a local file for use in
satellite network simulations.
"""

import os
import json5, json
from math import sqrt
import math
import sys
import numpy as np
from datetime import timedelta, datetime
import requests
from skyfield.api import load, EarthSatellite, wgs84
from skyfield.timelib import Time
from skyfield.toposlib import GeographicPosition
from topology.Satellite import Satellite
from enums import AccPointMode, Topology, tle_data, GenConfigsOutput
import globals
from utils import colorize
from tqdm import tqdm
from EdgeServer import EdgeServer


starlink_url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=STARLINK&FORMAT=TLE"
all_active_url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=ACTIVE&FORMAT=TLE"

# Leggi il file di configurazione JSON
config = globals.config

ts = load.timescale()  # ts : time management with astronomical time
time_now = ts.now()

#Funzione che ritorna i satelliti attivi in formato tle 
def get_active_satellites():
    """
    Cosa fa:
    Questo script fa una richiesta al NOMAD per avere tutti i  dati TLE dei satelliti Starlink.
    In seguito li salva in un File: ./Data/tle_data.txt
    """
    url = starlink_url
    print(colorize("[TLE] Requesting Data...","yellow"))
    response = requests.get(url) # ! Request
    if response.status_code == 200:
        tle_data = response.text.strip().splitlines() # ? TLE
        print(colorize("[TLE] Data received.","green"))
        return tle_data
    else:
        print(colorize(f"[TLE] Error: {response.status_code}", "red"))
        return None


def saveTLEOnFile() -> tle_data:
    _dir, filename ="./data", "tle_data.txt"
    file_path = f"{_dir}/{filename}"
    
    # 1. Attempt to download
    tle_data = get_active_satellites()
    
    # Check dir
    if not os.path.exists(_dir):
        try:
            os.makedirs(_dir, exist_ok=True)
        except OSError as e:
            sys.exit(colorize(f"ERRORE: {e}","red"))

    if tle_data:
        try:
            with open(file_path, "w") as file:
                for line in tle_data:
                    file.write(line + "\n")
            print(colorize(f"[TLE] Elaborati Correttamente '{file_path}'","green"))
            return tle_data
        except IOError as e:
            sys.exit(colorize(f"Errore nel salvataggio del file: {e}","red"))
    else:
        # Fallback
        print(colorize("[TLE] TLE not available online. Attempting to use cached data...", "yellow"))
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as file:
                    tle_data_cached = file.read().strip().splitlines()
                    print(colorize(f"[TLE] Fallback successful. Loaded cached TLE data from '{file_path}'", "green"))
                    return tle_data_cached
            except IOError as e:
                sys.exit(colorize(f"Error reading cached TLE data: {e}", "red"))
        else:
            error_msg = (
                "[ERROR] It was not possible to download TLE data from CelesTrak (HTTP Error) "
                "and no cached data is present in 'data/'. Please try again later or manually "
                "provide 'data/tle_data.txt'."
            )
            sys.exit(colorize(error_msg, "red"))


def openTLEFromFile(file_path: str = "./data/tle_data.txt") -> tle_data:
    if not os.path.exists(file_path):
        sys.exit(colorize(f"Errore: Il file '{file_path}' non esiste. Assicurati di aver eseguito 'saveTLEOnFile()' prima.","red"))
    
    try:
        with open(file_path, "r") as file:
            tle_data = file.read().strip().splitlines()
            print(colorize(f"[TLE] Dati TLE caricati da '{file_path}'","green"))
            return tle_data
    except IOError as e:
        sys.exit(colorize(f"Errore nella lettura del file: {e}","red"))


def get_current_time() -> Time:
    """
    Get the current time using Skyfield's timescale.

    This function loads the timescale from the Skyfield library and returns the current time.

    Returns:
        skyfield.timelib.Time: The current time according to Skyfield's timescale.
    """
    ts = load.timescale()  # Carica la scala temporale di Skyfield
    return ts.now()


def advance_time(current_time, minutes_to_add):
    """
    Advance the given Skyfield Time object by a specified number of minutes.

    Args:
        current_time (skyfield.timelib.Time): The current time from ts.now().
        minutes_to_add (int): The number of minutes to add to the current time.

    Returns:
        skyfield.timelib.Time: The new time advanced by the specified number of minutes.
    """
    # Convert the Skyfield Time object to a datetime object
    current_datetime = current_time.utc_datetime()

    # Add the specified number of minutes
    new_datetime = current_datetime + timedelta(minutes=minutes_to_add)

    # Convert the new datetime object back to a Skyfield Time object
    ts = load.timescale()
    new_time = ts.from_datetime(new_datetime)

    return new_time


# Getter Topos 'Observer' object
def getObserverObj(location=config["simulation_location"]):
    if location in config["locations"]:
        lat = config["locations"][location]["lat"]
        lon = config["locations"][location]["lon"]
        return wgs84.latlon(lat, lon)
    else:
        sys.exit(
            f"Errore: The User Position '{location}' not found in the config file."
        )


# Getter reference system from a Satellite
def getSystemFromSat(satellite, time, Geocentric=False):
    """
    Get the reference system from a satellite.

    Args:
        satellite (EarthSatellite): The satellite object.
        Geocentric (bool): If False, return the system relative to the observer's point of view.
                           If True, return the satellite's position relative to the center of the Earth (Geocentric).
        time (Time): The time at which to get the satellite's position.
    Returns:
        Geocentric or Topocentric: The reference system of the satellite at the given time.
    """
    if Geocentric:  # Satellite Position from the Center of Earth
        return satellite.at(time)  # return geocentric system
    else:  # Satellite Position from the Observer Position
        difference = (
            satellite - getObserverObj()
        )  # Calculate the difference between the satellite's position and the observer's position to get the topocentric reference system
        return difference.at(time)  # return topocentric system


def get_pos_proximity(pos1, pos2):
    """
    Calcola la distanza fra due punti in uno spazio tridimensionale
    Args:
        pos1: Vettore posizionale dell'obj1
        pos2: Vettore posizionale dell'obj2
    :return: lunghezza del segmento obj1 -> obj2
    """
    # Extraction of coordinate components
    x1, y1, z1 = pos1
    x2, y2, z2 = pos2

    # Calculate the Euclidean distance
    return sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)


def get_orbit_proximity(sat1, sat2, t):
    """
    Calculates the distance between two satellites in kilometers.

    Args:
        satellite1: EarthSatellite object representing the first satellite.
        satellite2: EarthSatellite object representing the second satellite.
        timestamp: Skyfield Time object representing the moment of calculation.

    Returns: The distance between the two satellites in kilometers.
    """
    # Get geocentric positions in km
    pos_sat1 = getSystemFromSat(sat1, t, True).position.km
    pos_sat2 = getSystemFromSat(sat2, t, True).position.km

    # Extraction of coordinate components
    x1, y1, z1 = pos_sat1
    x2, y2, z2 = pos_sat2

    return sqrt(
        (x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2
    )  # Calculate the Euclidean distance


def are_satellites_equal(sat1, sat2):
    """
    Compare two satellites to check if they are the same based on their name and satellite number.

    Args:
        sat1: EarthSatellite object representing the first satellite.
        sat2: EarthSatellite object representing the second satellite.

    Returns:
        bool: True if the satellites are the same, False otherwise.
    """
    # Confronta per nome e numero satnum
    return sat1.name == sat2.name and sat1.model.satnum == sat2.model.satnum


def getLatency(distance: float):
    LIGHT_SPEED = 299792458  # m/s
    # convert distance to meters
    distance_m = distance * 1000

    return distance_m / LIGHT_SPEED  # Calculate latency in seconds


# ---------------------------------------------------------------------------- #
#                                    Filter                                    #
# ---------------------------------------------------------------------------- #


def filterSatellitesInView(satellite, t):
    """
    Input: Satellites
    Output: Boolean value | True : sat is coming in our direction
                          | False : sat is not coming in our direction
    """
    sys = getSystemFromSat(satellite, t)

    velocity = sys.velocity

    r = sys.position.km  # r è la posizione relativa del SAT rispetto all'observer
    r_unit = r / globals.np.linalg.norm(r)  # Vettore unitario
    v_rel = globals.np.dot(
        velocity.km_per_s, r_unit
    )  # Calcoliamo la velocità calcolando il prodotto scalare tra r e r_unit

    return True if v_rel < 0 else False


def getAllSatOnLine(
    t: Time,
    tle_data,
    pos_A: GeographicPosition,
    pos_B: GeographicPosition,
    corridor_deg: float = config["corridor_angle"],
    Phi_max: int = config["Phi_max"],
    Buffer_zone: int = config["Phi_buffer"],
    ap_mode_a: AccPointMode = AccPointMode.BASE,
    num_acc_point_A: int = config["access_point"]
) -> Topology:
    """
    This function return all satellites between a given point A,
    and a given point B, in a specific time t.
    It use the TLE data to find all satellites in the line of sight between A and B,
    including the dome/buffer zone exactly above A and B.
    """
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
        print(colorize("[DEBUG] A e B sono uguali. Utilizzare la funzione su punto singolo.", "yellow"))
        # Inserisci qui la logica di fallback se serve
        pass

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
            top_A_norm = top_A / np.linalg.norm(top_A)
            alt_A_rad = np.arcsin(np.clip(np.dot(top_A_norm, vA), -1.0, 1.0))

            # Vettore da B al satellite
            top_B = vP_km - vB_km
            top_B_norm = top_B / np.linalg.norm(top_B)
            alt_B_rad = np.arcsin(np.clip(np.dot(top_B_norm, vB), -1.0, 1.0))

            # --- UNIONE LOGICA ---
            # È valido se si trova nel corridoio OPPURE sopra l'orizzonte BZED di A OPPURE di B
            if (in_corridor_inf and between_walls) or (alt_A_rad > BZED_rad) or (alt_B_rad > BZED_rad):
                # ! : controlla 
                # TODO : CONTROLLA CHE QUESTA SEZIONE SIA GIUSTA E FAI IL COMMIT
                sat_on_line.append(Satellite(satellite, np.linalg.norm(vP_km - vA_km), (name, line1, line2), False))
        
        # Sorting Satellite by distance from A
        sat_on_line.sort(key=lambda sat: np.linalg.norm(sat.satellite.at(t).position.km - vA_km))  
        
        
        if num_acc_point_A > len(sat_on_line):
            num_acc_point_A = len(sat_on_line)//2 # Non ci sono abbastanza satelliti da usare come AP
            print(colorize(f"WARNING: Not enough satellites to satisfy the request. The number of access points has been set to {num_acc_point_A}.", "orange"))
        
        
        counter = 0 # Contatore degli access Point
        # Determino Access Points
        for sat in sat_on_line:
            
            if counter >= num_acc_point_A:
                # Ho tutti gli AP di A, posso uscire
                break
            
            # Check della modalità
            if ap_mode_a == AccPointMode.BASE:
                can_take = counter < num_acc_point_A
            elif ap_mode_a == AccPointMode.OPTIMAL:
                can_take = counter < num_acc_point_A and filterSatellitesInView(sat, t)
            
            if can_take:
                sat.is_acc_point = True
                counter += 1
                
        return sat_on_line


# ---------------------------------------------------------------------------- #
def getAllSatOnMe(
    t,
    tle_data,
    ap_mode: AccPointMode,
    Phi_max=config["Phi_max"],
    Num_Access_point=config["access_point"],
):
    """
    This function return all the satellite above a given point

    Args:
        t (Time): time of observation.
        tle_data (tle_data): TLE data of the satellites.
        point_pos (GeographicPosition): position of specific point.
        Phi_max (float): Elevation Angle of a given point to search satellite in that area.
        num_acc_point (int): Number of acc point we are searching in that area

    """
    buffer_Phi = Phi_max - config["Phi_buffer"]  # Angle of a Buffer Zone
    satellites_dome, satellites_buffer = [], []

    # Get all satellites within the observer's dome and buffer zone
    for i in range(0, len(tle_data), 3):
        name = tle_data[i].strip()
        line1 = tle_data[i + 1].strip()
        line2 = tle_data[i + 2].strip()

        satellite = EarthSatellite(
            line1, line2, name, ts
        )  # Converting tle Data in SGP4 Satellite Object
        syst = getSystemFromSat(satellite, t)  # reference system

        alt, az, distance = (
            syst.altaz()
        )  # alt : Altitude in degrees relative to the observer
        # az : Sat Azimuth Angle relative to the observer
        # distance: distance Sat - Observer
        if alt.degrees > buffer_Phi:
            if alt.degrees > Phi_max:
                # Satellite in the Dome
                satellites_dome.append(
                    Satellite(satellite, distance.km, (name, line1, line2), False)
                )
            else:
                # Satellite in the Buffer Zone
                satellites_buffer.append(
                    Satellite(satellite, distance.km, (name, line1, line2), False)
                )

    # Ordino i satelliti in base alla posizione rispetto all'utente
    sat_sort_dome = sorted(satellites_dome, key=lambda s: s.distance)
    sat_sort_buff = sorted(satellites_buffer, key=lambda s: s.distance)

    counter = 0
    if Num_Access_point > len(sat_sort_dome):
        Num_Access_point = (
            len(sat_sort_dome) // 2
        )  # Non ci sono abbastanza satelliti da soddisfare la richiesta di Access_point
        print(
            f"WARNING: Not enough satellites to satisfy the request. The number of access points has been set to {Num_Access_point}."
        )

    # Determino Access Points
    for sat in sat_sort_dome:
        if counter >= Num_Access_point:
            break
        # Decido se eseguire il filtro o meno
        if ap_mode == AccPointMode.BASE:
            can_take = counter < Num_Access_point
        elif ap_mode == AccPointMode.OPTIMAL:
            can_take = counter < Num_Access_point and filterSatellitesInView(
                sat.satellite, t
            )

        if can_take:
            sat.is_acc_point = True
            counter += 1


    return sat_sort_dome, sat_sort_buff


def compute_distances_from_target_satellite(sat, closerSatellite_Sorted, t):
    """
    Compute the distances from the target satellite to other satellites.

    :param sat: The target satellite.
    :param closerSatellite_Sorted: List of satellites sorted by proximity.
    :param t: Current time.

    :return: List of tuples containing satellites and their distances from the target satellite.
    """

    vector_Sat_Topology = []
    for i in range(0, len(closerSatellite_Sorted)):
        if are_satellites_equal(sat.satellite, closerSatellite_Sorted[i].satellite):
            pass
        else:
            proximity = get_orbit_proximity(
                sat.satellite, closerSatellite_Sorted[i].satellite, t
            )
            if proximity < config["Laser_Communication_Range"]:  # Check laser distance
                latency = getLatency(proximity)  # Calculate latency
                vector_Sat_Topology.append(
                    (closerSatellite_Sorted[i].satellite.name, proximity, latency)
                )

    sat_vector_Topology_sorted = sorted(
        vector_Sat_Topology, key=lambda x: x[1]
    )  # Ordino i vicini in base alla distanza dal satellite
    return sat_vector_Topology_sorted


def find_angle(t, satellite):
    """
    Find the elevation angle of a satellite relative to the observer at a given time.

    Args:
        t (skyfield.timelib.Time): The time at which to find the elevation angle.
        satellite (EarthSatellite): The satellite object.

    Returns:
        float: The elevation angle in degrees.
    """
    sys = getSystemFromSat(satellite, t)
    alt, az, distance = sys.altaz()
    return alt.degrees


def create_satellite_Identity_card(
    satellite, life, neighbors_info, t, access_points=False, line_setup=False
):
    """
    Create a dictionary representing a satellite and its neighbors.

    Args:
        satellite (tuple): A tuple containing the satellite object and its distance from the user.
        life (dict): A dictionary with information about the satellite's life.
        neighbors_info (list of tuples): A list of tuples with (neighbor_name, distance, latency).
        t (skyfield.timelib.Time): The current time.
        access_points (bool): Whether the satellite is an access point.

    Returns:
        dict: A dictionary representing the satellite and its neighbors.
    """
    elevation_angle = None
    if not line_setup:
        elevation_angle = find_angle(
            t, satellite.satellite
        )  # Mi trovo l'angolo di elevazione del satellite rispetto l'obverver

    satellite_data = {
        "satellite": satellite.satellite.name,
        "distance_from_user": satellite.distance,
        "is_access_point": access_points,
        "elev_angle": elevation_angle,
        "TLE-DATA": [
            {
                "name": satellite.tle[0],
                "line1": satellite.tle[1],
                "line2": satellite.tle[2],
            }
        ],
        "life": life,
        "neighbors": [
            {"name": neighbor_name, "distance": distance, "latency": latency}
            for neighbor_name, distance, latency in neighbors_info
        ],
    }
    return satellite_data


def find_satellite_events(satellite, t0):
    """
    Finds the events for a satellite between two times.
    Args:
        satellite (EarthSatellite): The satellite for which to find events.
        t0 (datetime): Reference time of start.
        t1 (datetime): The end time for finding events.

    Returns:
        dict : info about life of the satellite
    """
    t_end = ts.utc(
        t0.utc_datetime()
        + timedelta(minutes=config["Interval_future_event_prediction"])
    )  # End time for finding events
    t_start = ts.utc(
        t0.utc_datetime() - timedelta(minutes=config["Interval_past_event_prediction"])
    )  # Start time for finding events

    life = {}

    time, events = satellite.find_events(
        getObserverObj(), t_start, t_end, altitude_degrees=config["Phi_max"]
    )  # Find events for the satellite

    if len(time) == 0:
        life = {
            "AOS": None,
            "Max-El": None,
            "LOS": None,
            "life_seconds": None,
            "time_until_set_seconds": None,
        }
    else:

        if (
            not time[0] < t0 < time[2]
        ):  # If the satellite is not in the dome then its life is not defined
            time_until_set = 0
        else:  # The satellite is in the dome

            time_until_set = timedelta(seconds=(time[2] - t0) * 86400).seconds
        life = {
            "AOS": time[0].utc_strftime(),  # Acquisition of the Satellite (AOS)
            "Max-El": time[1].utc_strftime(),  # Maximum Elevation            (Max-El)
            "LOS": time[2].utc_strftime(),  # Loss of Signal               (LOS)
            "life_seconds": timedelta(
                seconds=(time[2] - time[0]) * 86400
            ).seconds,  # Life of the satellite in Dome
            "time_until_set_seconds": time_until_set,  # Time until the satellite sets
        }

    return life


    progress = current_step / total_steps
    filled = int(bar_width * progress)
    bar = "[" + "#" * filled + "-" * (bar_width - filled) + "]"
    percent = progress * 100
    print(
        f"\r{prefix}: {bar} {current_step}/{total_steps} ({percent:5.1f}%)",
        end="",
        flush=True,
    )


def load_saved_configuration(mode: AccPointMode) -> GenConfigsOutput:
    """
    >> FUNZIONE DI TEST <<
    Funzione che carica le configurazioni salvate nei rispettivi file json.
    Usata nel main per evitare di ricostruire le configurazioni, solo nel caso in cui
    dobbiamo costruire anche le OGM Table.

    Args:
        mode (AccPointMode) : Modalità Configurazioni
    Return:
        configuration (GenConfigsOutput) : Oggetto Configurazione nel formato atteso.
    """
    path = f"data/configurations_AP_{mode}.json"
    configuration = None
    print(colorize(f"[LOAD] Caricamento configurazione <{mode}>...", "yellow"))

    try:
        with open(path, "r") as f:
            configuration = json.load(f)
    except Exception as e:
        sys.exit(
            colorize(
                f"[LOAD] Errore durante il caricamento delle configurazioni: {e}", "red"
            )
        )

    print(colorize(f"[LOAD] Configurazione <{mode}> caricata con successo.", "green"))
    return configuration


def build_configurations(
    t0: Time, tle_data: tle_data, mode: AccPointMode
) -> GenConfigsOutput:

    config_interval = config["Interval_between_Configurations_in_seconds"]
    tot_config = int(
        (config["simulation_duration"] + config["adding_time"]) / config_interval
    )

    config_path = f"data/configurations_AP_{mode}.json"

    configurations = genConfigs_dome(
        t0, config_interval, tot_config, tle_data, config_path, mode
    )

    return configurations


def genConfigs_dome(
    t0:Time,
    interval:int,
    num_configs:int,
    tle_data:tle_data,
    json_path: str,
    mode: AccPointMode
) -> GenConfigsOutput:
    """
    Generates a list of configurations over a specified time period.
    Args:
        t0 (datetime, optional): The initial time for generating configurations. Defaults to the current time.
        interval (int, optional): The time interval (in seconds) between each configuration. Defaults to 2 minutes.
        num_configs (int, optional): The total number of Configurations in the building process.
        tle_data (tle_data): TLE data
    Returns:
        list: A list of configurations generated over the specified time period.
    """
    t, configs = t0, []  # Initialize time and configuration list
    # num_access_point = config["access_point"]  # Number of access points
    totSecs = num_configs * interval  # Total duration in seconds

    print(colorize(f"[{mode}] GENERAZIONE CONFIGURAZIONI:", "yellow"))
    for elapsed_time in tqdm(range(0, totSecs, interval), desc="Progresso", ncols=80):
        step_index = elapsed_time // interval + 1
        

        configuration = []
        
        dome, sat_sort_buff = getAllSatOnMe(t, tle_data, mode)
        topology = dome + sat_sort_buff

        # Gestione della serializzabilità
        for current_server in topology:

            neighbors = compute_distances_from_target_satellite(
                current_server, topology, t
            )  # Compute distances to neighbors

            # ! Aggiungi la sezione vicini per ogni Satellite
            life = find_satellite_events(
                current_server.satellite, t
            )  # Find events for the satellite

            if current_server.is_acc_point:
                info_sat = create_satellite_Identity_card(
                    current_server, life, neighbors, t, True
                )  # Create neighbor info for access points
            else:
                info_sat = create_satellite_Identity_card(
                    current_server, life, neighbors, t, False
                )  # Create neighbor info for other satellites

            configuration.append(info_sat)  # Save this satellite's configuration

        data = {
            "time": t.utc_datetime().isoformat(),  # Current time in ISO format
            "configuration": configuration,  # List of satellite configurations
        }
        configs.append(data)  # Append the configuration to the list
        t = advance_time(t, interval / 60)  # Advance time by the interval

    output = {
        "t0": t0.utc_datetime().isoformat(),  # Initial time in ISO format
        "interval": interval,  # Time interval between configurations
        "total_seconds": totSecs,  # Total duration for configurations
        "observer_position": config["simulation_location"],  # Observer's position
        "configurations": configs,  # List of all configurations
    }

    # Salva il file JSON
    try:
        with open(json_path, "w") as f:
            # noinspection PyTypeChecker
            json.dump(output, f, indent=4)
        print("File saved successfully!")
    except IOError as e:
        print(f"Error saving configuration file: {e}")

    return output


def build_topology_network(satellites, t, max_range=config["Laser_Communication_Range"]):
    """
    Funzione che costruisce la topologia di rete basata sui satelliti forniti e sul tempo t.
    Args:
        satellites (list): Lista di satelliti (EarthSatellite) da considerare per la topologia.
        t (Time): Il tempo specifico per cui calcolare le posizioni e le distanze dei satelliti.
        max_range (float): La distanza massima (in km) per considerare due satelliti come vicini.
    Returns:
        dict: Un dizionario che mappa ogni satellite al suo elenco di vicini.
    """
    if not satellites:
        return {}

    # 1. Estraiamo le posizioni per tutti i satelliti
    positions = np.array([sat.satellite.at(t).position.km for sat in satellites])
    names = [sat.name for sat in satellites]
    num_sats = len(satellites)

    # 2.Matrice delle distanze NxN
    # Sottraiamo ogni vettore da tutti gli altri contemporaneamente
    diff = positions[:, np.newaxis, :] - positions[np.newaxis, :, :]
    dist_matrix = np.linalg.norm(diff, axis=-1)

    topology_map = {}

    # 3. Filtriamo e costruiamo le tuple
    for i in range(num_sats):
        neighbors = []
        for j in range(num_sats):
            if i == j: 
                continue # Salto me stesso
            
            dist = dist_matrix[i, j]
            if dist < max_range:
                latency = getLatency(dist) # Usa la tua funzione esistente
                neighbors.append((names[j], float(dist), float(latency)))
        
        # Ordiniamo i vicini del satellite 'i' per distanza
        neighbors.sort(key=lambda x: x[1])
        topology_map[names[i]] = neighbors

    return topology_map



def genConfigs_line(
    t0:Time,
    interval:int,
    num_configs:int,
    tle_data:tle_data,
    json_path: str,
    mode: AccPointMode,
    pos_A: GeographicPosition,
    pos_B: GeographicPosition
    ) -> GenConfigsOutput:
    """
    Questa funzione costruisce configurazioni dati due punti A e B.
    Crea 'num_configs' configurazioni ogni 'interval' di tempo a partire dal
    momento 't0'. Usa 'tle_data' per sapere la posizione dei satelliti.
    Salva tutto nel file json in 'json_path'.
    
    Args:
        t0 (Time): Initial time for generating configurations.
        interval (int): Time interval (in seconds) between each configuration.
        num_configs (int): Total number of configurations to generate.
        tle_data (tle_data): TLE data for satellite positions.
        json_path (str): Path to save the generated configurations in JSON format.
        mode (AccPointMode): Mode for access point selection.
        pos_A (GeographicPosition): Geographic position of point A.
        pos_B (GeographicPosition): Geographic position of point B.
    Returns:
        GenConfigsOutput: An object containing the generated configurations and related metadata.
    """
    t, configs = t0, [] # Initialize time and configuration list
    totSecs = num_configs * interval # Total duration in seconds
    
    print(colorize(f"[{mode}] Generazione Configurazioni:", "yellow"))
    for elapsed_time in tqdm(range(0, totSecs, interval), desc="Progresso", ncols=80):
        step_index = elapsed_time // interval + 1
         # print progeess bar
        
        line_conf = [] # Initialize configuration for the current time step
        
        line = getAllSatOnLine(t, tle_data, pos_A, pos_B, ap_mode_a=mode) # Get satellites in line between pos_A and pos_B
        line_map = build_topology_network(line, t) # Build the Network for the satellites in line
        
        for satellite in line:
            # Get neighbors for all satellites in line
            neighbors_info = line_map.get(satellite.name, [])
            #TODO : Abbiamo escluso per il momento il calcolo della vita "AOS, Max-El...""
            info_sat = create_satellite_Identity_card(
                satellite, None, neighbors_info, t, satellite.is_acc_point, line_setup=True
            )
            print(info_sat)
            sys.exit(colorize("STOP TEST", "red"))
            
    pass


def build_EdgeServer_from_config(env, configuration, ogm_tables=None):
    neighbors_SAT, tmp_ES, list_acc_point = {}, [], []
    # print_dict(dict_OGMs)
    for sat_info in configuration["configuration"]:
        server_id = f"{sat_info['satellite']}"
        name = sat_info["TLE-DATA"][0]["name"]
        line1 = sat_info["TLE-DATA"][0]["line1"]
        line2 = sat_info["TLE-DATA"][0]["line2"]
        life = sat_info["life"]["time_until_set_seconds"]
        acc_point = sat_info["is_access_point"]
        satellite_angle = sat_info["elev_angle"]

        if acc_point:
            neighbors_SAT[server_id] = sat_info["neighbors"]
            edge_server = EdgeServer(
                env,
                server_id,
                EarthSatellite(line1, line2, name, load.timescale()),
                life,
                acc_point,
                satellite_angle,
            )
            if ogm_tables:
                edge_server.ogm_table = ogm_tables[name]
            tmp_ES.append(edge_server)
            list_acc_point.append(edge_server.name)

        else:
            neighbors_SAT[server_id] = sat_info["neighbors"]
            edge_server = EdgeServer(
                env,
                server_id,
                EarthSatellite(line1, line2, name, load.timescale()),
                life,
                acc_point,
                satellite_angle,
            )
            if ogm_tables:
                edge_server.ogm_table = ogm_tables[name]
            tmp_ES.append(edge_server)

    return tmp_ES, neighbors_SAT, list_acc_point


def periodic_recall_Topology_monitor(env, data_configurations, OGMs_tables):
    while True:

        # SICUREZZA: Interrompiamo se abbiamo finito le configurazioni
        if globals.config_index >= len(data_configurations["configurations"]):
            print(colorize(f"[Topology-Monitor] Reached end of configurations. Terminating monitor.", "yellow"))
            break

        print("-" * 70)
        print(
            f"\t||TIME IN SIMULATION : (seconds:{env.now}) (minutes: {env.now // 60}) ||\n"
        )
        print("MODIFICA CONFIGURAZIONE IN CORSO...\n")

        new_edge_servers, new_global_access_point = loadConfiguration(
            env, data_configurations, OGMs_tables
        )

        # ! Aggiorno le Globali
        # ! Sincronizzato intrinsecamente da SimPy
        globals.global_access_point = new_global_access_point
        globals.edge_servers = new_edge_servers

        globals.config_index += 1
        yield env.timeout(config["Interval_between_Configurations_in_seconds"])




def update_counters_dictionary(
    all_server, initial_server_counter, different_server_counter, other_server_counter
):
    """
    Aggiunge nuovi server ai dizionari dei contatori o li inizializza.

    Args:
        edge_servers (list): Lista attuale di server.
        initial_server_counter (dict): Dizionario per il contatore iniziale dei server.
        different_server_counter (dict): Dizionario per il contatore dei server diversi.
        other_server_counter (dict): Dizionario per il contatore degli altri server.

    Returns:
        None: Aggiorna i dizionari in-place.
    """
    for server_name in all_server:
        if server_name not in initial_server_counter:
            initial_server_counter[server_name] = 0
        if server_name not in different_server_counter:
            different_server_counter[server_name] = 0
        if server_name not in other_server_counter:
            other_server_counter[server_name] = 0


def update_servers(new_servers, acc_point):
    """
    Aggiorna i server esistenti o aggiunge nuovi server se non presenti.

    Args:
        edge_servers (list): Lista di server esistenti (da mantenere).
        new_servers (list): Lista di nuovi server dalla nuova configurazione.

    Returns:
        dict: Dizionario aggiornato dei server.
    """

    # Crea un dizionario per i server esistenti basato sul nome
    old_servers = {server.name: server for server in globals.edge_servers}
    new_servers = {server.name: server for server in new_servers}

    # Dizionari per i risultati
    intersection = {
        name: server for name, server in old_servers.items() if name in new_servers
    }  # Servers nell'intersezione

    # Aggiorno gli attributi dell'intersezione
    for name, server in intersection.items():
        server.elev_angle = new_servers[name].elev_angle
        server.orbitalSunset = new_servers[name].orbitalSunset

    # Aggiorno i riferimenti degli acc_point flags
    for name, server in intersection.items():
        if server.name in acc_point:
            server.is_acc_point = True
        else:
            server.is_acc_point = False

    A = {
        name: server for name, server in old_servers.items() if name not in new_servers
    }  # Server che sono tramontati
    B = {
        name: server for name, server in new_servers.items() if name not in old_servers
    }  # Server che sono appena sorti

    # Stampa i server che sono tramontati
    # for name, server in A.items():
    # print(f"Server tramontato: {name}, angle:{server.elev_angle} ,Orbital Sunset: {server.orbitalSunset} (sec)")

    # Stampa i server che sono appena sorti
    # for name, server in B.items():
    # print(f"Server appena sorto: {name}, angle:{server.elev_angle} ,Orbital Sunset: {server.orbitalSunset}")

    # Stampa i server nell'intersezione
    # for name, server in intersection.items():
    # print(f"Server aggiornato: {name}, angle:{server.elev_angle} ,Orbital Sunset: {server.orbitalSunset}")

    return intersection, A, B


def update_servers_neighbors(servers_dict, neighbors_SAT):
    """
    Updates the neighbors of each server in the servers_dict based on the provided neighbors_SAT information.
    Args:
        servers_dict (dict): A dictionary where keys are server names and values are server objects.
        neighbors_SAT (dict): A dictionary where keys are server names and values are lists of dictionaries
                              containing neighbor information with 'name' and 'latency' keys.
    Returns:
        dict: The updated servers_dict with neighbors information added to each server.
    The function performs the following steps:
    1. Constructs a dictionary (servers_updated_neighbors) to store updated neighbor information for each server.
    2. Iterates through each server in servers_dict and updates its neighbors based on neighbors_SAT.
    3. For each server, it creates dictionaries for hop_neighbors, latency, and bandwidth.
    4. Updates each server's neighbors using the update_neighbors method with the constructed dictionaries.
    """
    servers_updated_neighbors = {}  # Dizionario per i server con i vicini aggiornati

    # Costruzione del dizionario per salvare le informazioni dei server e dei loro vicini
    for k, v in servers_dict.items():
        neighbor, neighbors = {}, []
        for neighbor in neighbors_SAT[k]:
            neighbor = {
                "server": servers_dict[neighbor["name"]],
                "latency": neighbor["latency"],
            }
            neighbors.append(neighbor)

        servers_updated_neighbors[k] = {"obj": v, "neighbors": neighbors}

    # Inserisco i vicini per ogni Edge_server
    for name, server in servers_dict.items():
        hop_neighbors, latency, bandwidth = {}, {}, {}
        info = servers_updated_neighbors[name]

        for neighbor in info["neighbors"]:
            hop_neighbors[neighbor["server"]] = 1
            latency[neighbor["server"]] = neighbor["latency"]
            bandwidth[neighbor["server"]] = globals.rnd.uniform(
                config["available_bandwidth"]["min"],
                config["available_bandwidth"]["max"],
            )

            # Aggiungo i dizionari riguardanti i vicini ai rispettivi server
        server.update_neighbors(hop_neighbors, latency, bandwidth)

    return servers_dict


def loadConfiguration(env, data_configurations, OGMs_tables):
    """
    Carica la configurazione dal file e aggiorna la lista edge_servers senza sostituirla completamente.
    Args:
        env: Ambiente simpy.
        data_configurations: Il dizionario contenente le configurazioni caricate dal file JSON.
        OGMs_tables: Il dizionario contenente le tabelle OGM per ogni configurazione.
        simple: Flag per indicare se caricare la configurazione in modalità semplice.
    Returns:
        None
    """

    global_access_point = []  # futuri acc_points

    if globals.config_index > 0:
        configuration = data_configurations["configurations"][globals.config_index]
        globals.ist_in_conf = string_to_skyfield_time(configuration["time"])

        print(
            "Aggiornato il Tempo Globale: ",
            globals.ist_in_conf.utc_strftime("%Y-%m-%d %H:%M:%S"),
        )

        # ! Costruisci i nuovi server dalla configurazione
        if OGMs_tables:
            OGMs_table_single_config = OGMs_tables[str(globals.config_index)]
            new_servers, new_neighbors, acc_point = build_EdgeServer_from_config(
                env, configuration, OGMs_table_single_config
            )
        else:
            new_servers, new_neighbors, acc_point = build_EdgeServer_from_config(
                env, configuration
            )

        # ! Aggiorna i server esistenti o aggiunge nuovi server se non presenti.
        intersection, old_edge_servers, new_edge_servers = update_servers(
            new_servers, acc_point
        )

        server = {**intersection, **new_edge_servers}

        update_counters_dictionary(
            server,
            globals.initial_server_counter,
            globals.different_server_counter,
            globals.other_server_counter,
        )  # Aggiorno i dizionari dei nuovi aggiunti

        # ! Aggiorno i vicini
        servers_in_dome_updated = update_servers_neighbors(
            {**intersection, **new_edge_servers}, new_neighbors
        )  # Aggiorno i vicini per i server nell'intersection e i nuovi aggiunti

        # Pulisco i dizionari che riguardano i vicini dei server tramontati
        [server.update_neighbors({}, {}, {}) for server in old_edge_servers.values()]

        # ! Ridefinisco le Labels dei Tasks
        for server in old_edge_servers.values():
            if len(server.tasks) > 0:
                print(f"{server.name} SERVER OUT OF BUFF")
                for t in server.tasks:
                    t.label = "SEN_OUT_OF_BUFF"
                    print(f"\t{t.id} : {t.label}")

        with globals.lock_access_edge_servers_topology:
            # Salvo solo i satelliti che appartengono alla topologia
            globals.edge_servers_topology = list(servers_in_dome_updated.values())

        new_edge_servers = list(servers_in_dome_updated.values()) + list(
            old_edge_servers.values()
        )

        # Trovo i nuovi acc_points
        counter_acc_found = 0
        for server in new_edge_servers:
            if counter_acc_found < config["access_point"]:
                if server.is_acc_point:
                    global_access_point.append(server)
                    counter_acc_found += 1
            else:
                break

        return new_edge_servers, global_access_point
    else:
        print(f"SIMULAZIONE INIZIATA conf {globals.config_index}")
        # Caricamento iniziale della configurazione
        configuration = data_configurations["configurations"][globals.config_index]

        # Costruisci i server iniziali
        if OGMs_tables:
            OGMs_table_single_config = OGMs_tables[str(globals.config_index)]
            edge_servers, neighbors_SAT, list_acc_point = build_EdgeServer_from_config(
                env, configuration, OGMs_table_single_config
            )
        else:
            edge_servers, neighbors_SAT, list_acc_point = build_EdgeServer_from_config(
                env, configuration
            )

        server_dict = {server.name: server for server in edge_servers}

        # Aggiungiamo i vicini per ogni elemento
        for server in edge_servers:
            neighbors = neighbors_SAT[server.name]

            for n in neighbors:
                neighbor_server = server_dict.get(n["name"])
                server.add_neighbor(
                    neighbor_server,
                    1,
                    n["latency"],
                    globals.rnd.uniform(
                        config["available_bandwidth"]["min"],
                        config["available_bandwidth"]["max"],
                    ),
                )
        # Trovo i nuovi acc_points
        counter_acc_found = 0
        for server in edge_servers:
            if counter_acc_found < config["access_point"]:
                if server.is_acc_point:
                    global_access_point.append(server)
                    counter_acc_found += 1
            else:
                break

        # print("TOPOLOGIA ATTUALE:")
        # [print(sat.name) for sat in edge_servers]

        # globals.config_index += 1
        globals.ist_in_conf = string_to_skyfield_time(configuration["time"])
        globals.edge_servers_topology = edge_servers
        return edge_servers, global_access_point


def string_to_skyfield_time(time_str):
    # Converte la stringa in oggetto datetime
    dt = datetime.fromisoformat(time_str)
    ts = load.timescale()
    return ts.from_datetime(dt)


def get_global_mode() -> AccPointMode:
    ap_selection = globals.config.get("AP_selection")
    if ap_selection == "base":
        return AccPointMode.BASE
    elif ap_selection == "optimal":
        return AccPointMode.OPTIMAL
    else:
        sys.exit("Modalità di Access Point non valida nel file di configurazione.")
