import sys
import numpy as np
from skyfield.timelib import Time
from skyfield.toposlib import GeographicPosition
from enums import AccPointMode, Topology, tle_data, GenConfigsOutput
from globals import config
from tqdm import tqdm
from topology.core import (
    getSystemFromSat, are_satellites_equal, get_pos_proximity, 
    get_orbit_proximity, build_topology_network, create_satellite_Identity_card,
    getLatency
)
from utils import colorize

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


