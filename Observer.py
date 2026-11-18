"""
Observer management and utility functions for task and position handling.

This module provides:

1. `Observer` class:
   - Represents the simulation observer, tracking tasks, packets, and OGM
     history.
   - Provides methods to retrieve geolocation and projected 3D position
     vectors.
   - Supports printing task summaries in a formatted table.

2. `ObserverMeta` singleton metaclass:
   - Ensures only one Observer instance exists at a time.

3. Utility functions:
   - `format_mb`: formats memory values (MB/GB) for display purposes.
"""

import abc
import globals
from collections import OrderedDict
from skyfield.api import wgs84
from skyfield.toposlib import GeographicPosition
import sys
import json5

from BaseTerminal import BaseTerminal
from utils import format_mb

config = globals.config

class ObserverMeta(abc.ABCMeta):
    """
    Singleton instance of an Observer. Inherits from abc.ABCMeta for BaseTerminal compatibility.
    """
    _instances = {}

    def __call__(cls, *args, **kwargs):

        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]
    

class Observer_Temp(BaseTerminal):
    """
    OGGETTO TEMPORANEO.
    Rappresenta l'osservatore nella simulazione, o meglio, colui che genera i task e riceve i risultati.
    """
    def __init__(self, loc_name: str, position: GeographicPosition):
        super().__init__(name='OBS', position=position, env=None)
        self.location_name =  loc_name

    def __str__(self):
        return f"Observer(name={self.name}, location_name={self.location_name}, position={self.position})"  



class Observer(BaseTerminal, metaclass=ObserverMeta):
    def __init__(self, env, pos):
        super().__init__(name='OBS', position=pos, env=env)
        
        self.OGMs_position = {}
        self.ogm_sequence = 0               # Contatore OGM emessi
        self.OGMs = []                      # OGM to process
        self.OGMs_NP = []                   # OGM recived and Not-Processed
        self.ogm_table = {}                 # OGMs Table {'originator': [ 'neighbor': 'count']
        self.OGMs_History = OrderedDict()   # Lista OGM visionati in passato

        self.packets = []           # Lista di pacchetti da smaltire
        self.packets_seq = 0        # contatore pacchetti spediti
        self.pkt_history = []

    
    def getLocation(self, altitude = config["sphere_altitude_km"] ,location = config["simulation_location"]):
        if location in config["locations"]:
            lat = config["locations"][location]["lat"]
            lon = config["locations"][location]["lon"]
            #print(f"User Location: {location} ({lat},{lon}) With Altitude ")

            return wgs84.latlon(lat, lon, altitude)
        else:
                sys.exit(f"Errore: The User Position '{location}' not found in the config file.") 
    
    def getPositionVector(self, t):
        """
        Return a 3D position vector [x,y,z] in km at time t
        :param t: skyfield time object
        :return: list of [x, y, z] in km
        """
        return self.getLocation(altitude = 0).at(t).position.km.tolist()

