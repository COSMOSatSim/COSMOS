import sys
import json
from datetime import timedelta
import globals
import simpy
from utils import colorize, saveInfoInFile, transmission_failure_probability
from routing.ogm import Ogm
from Observer import Observer
from topology.core import ts, get_orbit_proximity
from topology.core import loadConfiguration
import threading
from enums import AccPointMode
from topology.core import getObserverObj


config = globals.config

def load_saved_OGM() -> dict:
    try:
        with open(globals.DEFAULT_OGMS_TABLES, "r") as f:
            print(colorize(f"[LOAD] Caricamento OGM table...", "yellow"))
            ogm_data = json.load(f)
    except Exception as e:
        sys.exit(colorize(f"[ERROR] Caricamento OGM table fallito: {e}", "red"))
    print(colorize("[LOAD] OGM table caricata con successo.\n", "green"))
    return ogm_data


ADDING_TIME = config["adding_time"]
CONFIG_RIEMPI = int(ADDING_TIME / config["Interval_between_Configurations_in_seconds"])


def create_ogm(obj: type, origin_position_vect: list, is_AP: bool) -> None:
    ogm = Ogm(
        originator=obj.name,
        sender=obj.name,
        origin_position_vect=origin_position_vect,
        is_AP=is_AP,
        ttl=15,
        sequence_number=obj.ogm_sequence
    )
    obj.ogm_sequence += 1
    obj.OGMs.append(ogm)

def manage_ogm_test(ogm_map: list, t: type) -> dict:
    print("\t| Generazione OGM")
    for node in ogm_map:
        create_ogm(node, node.getPositionVector(t), node.is_acc_point)

    print("\t| Processing OGMs")
    total = len(ogm_map)

    from tqdm import tqdm
    for node in tqdm(ogm_map, desc="Processing OGMs", ncols=80):
        for ogm in node.OGMs:
            if ogm.id in node.OGMs_History or ogm.ttl == 0:
                continue
            if ogm.originator == node.name and ogm.sender != node.name:
                continue
            if ogm.originator != node.name and ogm.sender != node.name:
                node.OGMs_History[ogm.id] = {"originator": ogm.originator, "sender": ogm.sender}
            
            if ogm.originator != node.name:
                if ogm.originator not in node.ogm_table:
                    node.ogm_table[ogm.originator] = {}
                if ogm.sender not in node.ogm_table[ogm.originator]:
                    node.ogm_table[ogm.originator][ogm.sender] = 0
                node.ogm_table[ogm.originator][ogm.sender] += 1
                
            if type(node) == Observer:
                for ap in globals.global_access_point:
                    ap.OGMs_NP.append(ogm.clone_for_forwarding(node.name))
            else:
                for neighbor in node.neighbors.keys():
                    if neighbor.name == ogm.sender:
                        continue
                    else:
                        proximity = get_orbit_proximity(node.get_satellite(), neighbor.get_satellite(), t)
                        failure_prob = transmission_failure_probability(proximity, config["Laser_Communication_Range"])
                        value = round(globals.rnd.uniform(0, 1), 2)
                        
                        if value > failure_prob:
                            neighbor.OGMs_NP.append(ogm.clone_for_forwarding(node.name))
        node.OGMs = []
        pass

    

    for obj in ogm_map:
        obj.OGMs = obj.OGMs_NP.copy()
        obj.OGMs_NP = []

    print("\t| Cleaning History")
    for obj in ogm_map:
        if type(obj) != Observer:
            out_dim = len(obj.OGMs_History) - obj.OGMs_History_dim
            if out_dim > 0:
                for i in range(out_dim):
                    key, value_ogm_dict = obj.OGMs_History.popitem(last=False)
                    obj.ogm_table[value_ogm_dict['originator']][value_ogm_dict['sender']] -= 1
                    if obj.ogm_table[value_ogm_dict['originator']][value_ogm_dict['sender']] == 0:
                        del obj.ogm_table[value_ogm_dict['originator']][value_ogm_dict['sender']]
                    if len(obj.ogm_table[value_ogm_dict['originator']]) == 0:
                        del obj.ogm_table[value_ogm_dict['originator']]

    ogm_tables_snapshot = {
        satellite.name: satellite.ogm_table
        for satellite in ogm_map
        if type(satellite) != Observer
    }
    return ogm_tables_snapshot

def distribute_ogm(env: type, data_configuration: dict, config_riempimento: int):
    # Need to import loadConfiguration lazily to avoid circular imports during startup
    
    OGMs_table = None

    while True:
        if globals.config_index >= len(data_configuration["configurations"]):
            print(colorize(f"[OGM-filling] Reached end of configurations. Terminating distribution.", "yellow"))
            break

        if globals.config_index == len(data_configuration["configurations"]) - 1:
            print(f"--- Reached last configuration element (index {globals.config_index})")
        else:
            print(f"--- Loading configuration index {globals.config_index}")

        new_edge_servers, new_global_access_point = loadConfiguration(
            env, data_configuration, OGMs_table
        )

        # ! Sincronizzato intrinsecamente da SimPy
        globals.global_access_point = new_global_access_point
        globals.edge_servers = new_edge_servers

        with globals.lock_access_edge_servers_topology:
            ogm_map = [globals.observer] + globals.edge_servers_topology

        num_redistributions = config["OGMs_redistribution"]
        time_section = config["Interval_between_Configurations_in_seconds"] / num_redistributions
        ogm_table_snapshot = None
        at = timedelta(seconds=time_section)

        for i in range(num_redistributions):
            new_instant = ts.utc(globals.ist_in_conf.utc_datetime() + at)
            at += timedelta(seconds=time_section)

            print(f"\tOGMS REDISTRIBUTION {i+1}/{num_redistributions} on : {new_instant.utc_iso(places=6)}")
            ogm_table_snapshot = manage_ogm_test(ogm_map, new_instant)

        if globals.config_index >= config_riempimento:
            ogm_table_path = f"data/OGMs_table.json"
            new_index = globals.config_index - config_riempimento
            saveInfoInFile(ogm_table_path, ogm_table_snapshot, new_index)

        globals.config_index += 1
        yield env.timeout(config["Interval_between_Configurations_in_seconds"])



def process_OGM_enviroment_simulation(data_configuration: dict) -> None:
    """
    Funzione usata per la costruzione delle tabelle OGM nella fase di PRE-Loading
    """
    globals.rnd.seed(config["seed"])

    env_ogm = simpy.Environment()  
    simulation_duration = config['simulation_duration'] + ADDING_TIME    #Aggiungo secondi extra di simulazione per il caricamento delle tabelle    
    print(colorize(f"[OGM-filling] Total OGM Simulation Duration: {simulation_duration} seconds", "cyan"))

    globals.observer = Observer(env_ogm, getObserverObj())  # Singleton Observer
    env_ogm.process(distribute_ogm(env_ogm, data_configuration, CONFIG_RIEMPI))    # ! Processo di redistribuzione

    env_ogm.run(simulation_duration)
    
def remove_warmup_configurations(mode: AccPointMode) -> None:
    """
    Removes the padding configurations generated for OGM table warmup.
    """
    config_path = f"data/configurations_AP_{mode}.json"
    with open(config_path, "r") as f:
        data = json.load(f)

    config_list = data["configurations"]
        
    print(colorize(f"[OGM-filling] Initial configurations count: {len(config_list)}", "yellow"))
    
    del config_list[:CONFIG_RIEMPI]    # Elimino le conf di riempimento delle table
    
    print(colorize(f"[OGM-filling] Removed {CONFIG_RIEMPI} warmup configurations.", "green"))
    print(colorize(f"[OGM-filling] Final configurations count for real simulation: {len(config_list)}", "green"))
    
    data["configurations"] = config_list
    data["t0"] = config_list[0]["time"]
    data["total_seconds"] = config['simulation_duration']
    
    with open(config_path, "w") as f:
        json.dump(data, f, indent=4)
