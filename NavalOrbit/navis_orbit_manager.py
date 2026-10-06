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

from topology.core import openTLEFromFile


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
    Define: 
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
        pos_A=observer.position, 
        pos_B=vessel.position,
        corridor_deg=10.0
    )
    
    plot_orbital_corridor(sats, observer.position, vessel.position, t0, 10.0)

if __name__ == "__main__":
    exp_1_test()
