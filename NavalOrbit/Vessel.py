import string
import math
import json5
import globals

from skyfield.toposlib import GeographicPosition
from skyfield.api import wgs84

from Observer import Observer_Temp
from enums import NavalRules

class Vessel:
    def __init__(self, name:str, position: GeographicPosition):
        self.name = name   
        self.position = position


    def __str__(self):
        return f"Vessel(name={self.name}, position={self.position})"
    

def generate_vessel_name() -> str:
    # Use globals.rnd for reproducible random choice
    chars = string.ascii_uppercase + string.digits
    return ''.join(globals.rnd.choice(chars) for _ in range(5))

def load_generation_rules(file_path: str = "NavalOrbit/vessel_setting.json5") -> dict:
    with open(file_path, "r") as file:
        data = json5.load(file)
        return data.get("generation_rules", {})

def calculate_destination(lat1_deg, lon1_deg, bearing_deg, distance_km):
    R = 6371.0 # Earth radius in km
    lat1 = math.radians(lat1_deg)
    lon1 = math.radians(lon1_deg)
    brng = math.radians(bearing_deg)
    d = distance_km
    
    lat2 = math.asin(math.sin(lat1) * math.cos(d / R) +
                     math.cos(lat1) * math.sin(d / R) * math.cos(brng))
    
    lon2 = lon1 + math.atan2(math.sin(brng) * math.sin(d / R) * math.cos(lat1),
                             math.cos(d / R) - math.sin(lat1) * math.sin(lat2))
                             
    return math.degrees(lat2), math.degrees(lon2)

def generate_vessel(
    rule: NavalRules = NavalRules.GLOBAL,
    min_dist:int = None, 
    max_dist:int = None, 
    observer_pos:Observer_Temp= None) -> Vessel:
    """
    Generate a Vessel instance based on the specified rule and observer position.
    rule_name is a Naval_Rules enum value.
    if rule_name.RADIUS -> min_dist, max_dist and observer_pos are required to define the distance range in kilometers
    if rule_name.GLOBAL -> The Vessel's position is generated randomly anywhere on the globe.
    
    Args:
        rule (NavalRules): The name of the generation rule to use.
        min_dist  (int): None | The minimum distance in kilometers for the 'radius' mode.
        max_dist  (int): None | The maximum distance in kilometers for the 'radius' mode.
        observer_pos: The position of the observer (required for 'radius' mode).
    Returns:
        Vessel: An instance of the Vessel class.
    """
    
    if rule == NavalRules.RADIUS and observer_pos is None:
        raise ValueError("observer_pos is required when rule_name is 'radius'")
    if rule == NavalRules.RADIUS and (min_dist is None or max_dist is None):
        raise ValueError("min_dist and max_dist are required when rule_name is 'radius'")
    
    
    name = f"V-{generate_vessel_name()}"
    
    if rule.GLOBAL:
        lat = globals.rnd.uniform(-90.0, 90.0)
        lon = globals.rnd.uniform(-180.0, 180.0)
        return Vessel(name, wgs84.latlon(lat, lon))
        
    elif rule.RADIUS:  
        if min_dist < 0 or max_dist < 0 or min_dist > max_dist:
                raise ValueError("Invalid distance range: min_dist and max_dist must be non-negative and min_dist <= max_dist")      
        # Calculate random distance and bearing
        distance = globals.rnd.uniform(min_dist, max_dist)
        bearing = globals.rnd.uniform(0.0, 360.0)
        
        lat1 = observer_pos.latitude.degrees
        lon1 = observer_pos.longitude.degrees
        
        lat2, lon2 = calculate_destination(lat1, lon1, bearing, distance)
        
        return Vessel(name, wgs84.latlon(lat2, lon2))
        
    else:
        raise ValueError(f"Unknown generation mode '{rule}'. Supported modes are 'global' and 'radius'.")