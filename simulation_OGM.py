"""
Module for simulating the OGM (Originator Generated Message) environment.

This module sets up a simulation environment to process OGMs exchanged
between satellites and an observer. It includes functions to run the
simulation for a specified duration, allowing for the pre-loading of OGM
tables, and to clean up initial configurations used for table filling.
"""

import sys
import simpy
from enums import AccPointMode
import globals
import json, json5
from  Observer import Observer 
from user_based_topology import getObserverObj
from topology import distribute_ogm
from utils import colorize

import time

config = globals.config

ADDING_TIME = config["adding_time"] # secondi di aggiunta al tempo di simulazione per il riempimento delle tabelle OGM
# Calculate dynamically based on config settings
CONFIG_RIEMPI = int(ADDING_TIME / config["Interval_between_Configurations_in_seconds"])


def process_OGM_enviroment_simulation(data_configuration) -> None:
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
    
    

def remove_warmup_configurations(mode:AccPointMode) -> None:
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
