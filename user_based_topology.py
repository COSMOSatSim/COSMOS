import json
from math import sqrt
import math
import numpy as np
import sys
from datetime import timedelta
from skyfield.api import load, EarthSatellite, wgs84


with open('config.json') as config_file:
    config = json.load(config_file)

ts = load.timescale()                                   # ts : time management with astronomical time
time_now = ts.now()


# reading TLE DATA from File
def loadTLEFromFile(filename):
    try:
        with open(filename, "r") as file:
            tle_data = file.read().splitlines()
        print(f"Dati TLE caricati correttamente da {filename}")
        return tle_data
    except FileNotFoundError:
        print(f"Errore: il file {filename} non è stato trovato.")
        return None
    except IOError as e:
        print(f"Errore nella lettura del file: {e}")
        return None

TLE_DATA = loadTLEFromFile("./data/tle_data.txt")       # Load TLE Data 
# ---------------------------------------------------------------------------- #
#                                    Printer                                   #
# ---------------------------------------------------------------------------- #

def printSatList(*sats):
    for l in sats:
        print("-"*20)
        [print(f"SATELLITE: {s[0].name} Distance: {s[1]}") for s in l]


# ---------------------------------------------------------------------------- #
#                                    Getter                                    #
# ---------------------------------------------------------------------------- #

def get_current_time():
    """
    Get the current time using Skyfield's timescale.

    This function loads the timescale from the Skyfield library and returns the current time.

    Returns:
        skyfield.timelib.Time: The current time according to Skyfield's timescale.
    """
    ts = load.timescale()  # Carica la scala temporale di Skyfield
    return ts.now()   

# Getter Topos 'Observer' object 
def getObserverObj(location = config["simulation_location"]):
    if location in config["locations"]:
        lat = config["locations"][location]["lat"]
        lon = config["locations"][location]["lon"]
        print(f"User Location: {location} ({lat},{lon}) ")

        return wgs84.latlon( lat, lon)
    else:
        sys.exit(f"Errore: The User Position '{location}' not found in the config file.") 

OBSERVER = getObserverObj()

# Getter reference system from a Satellite 
def getSystemFromSat(satellite, Geocentric = False, time = time_now):
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
    if Geocentric : # Satellite Position from the Center of Earth
        return satellite.at(time)                   # return geocentric system  
    else:           # Satellite Position from the Observer Position
        difference = satellite - OBSERVER   # Calculate the difference between the satellite's position and the observer's position to get the topocentric reference system
        return difference.at(time)                  # return topocentric system
    

def get_orbit_proximity(sat1 , sat2, t):
    """
    Calculates the distance between two satellites in kilometers.

    Args:
        satellite1: EarthSatellite object representing the first satellite.
        satellite2: EarthSatellite object representing the second satellite.
        timestamp: Skyfield Time object representing the moment of calculation.

    Returns: The distance between the two satellites in kilometers.
    """
    # Get geocentric positions in km
    pos_sat1 = getSystemFromSat(sat1, True, t).position.km
    pos_sat2 = getSystemFromSat(sat2, True, t).position.km

    # Extraction of coordinate components
    x1, y1, z1 = pos_sat1
    x2, y2, z2 = pos_sat2

    return sqrt((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2)     # Calculate the Euclidean distance

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
    return (
        sat1.name == sat2.name and
        sat1.model.satnum == sat2.model.satnum
    )

def getLatency(distance:float):
    LIGHT_SPEED = 299792458  #m/s
    # convert distance to meters
    distance_m = distance * 1000

    return distance_m / LIGHT_SPEED  # Calculate latency in seconds

def getOrbitalPeriod(h):
    """
    Calculate the orbital period of an object in low Earth orbit.

    Parameters:
    h (float): Altitude of the orbit above Earth's surface in meters.

    Returns:
    float: Orbital period in seconds.

    Notes:
    - The function assumes a circular orbit.
    - The Earth's radius and gravitational parameters are hardcoded.
    """

    R_Earth = 6_371_000  # Average radius of the Earth in meters
    G = 6.67430e-11      # Gravitational constant in m^3 kg^-1 s^-2
    M = 5.972e24         # Mass of the Earth in kg
    mu = G * M           # Gravitational parameter

    # Calculate the orbital period
    T_0 = 2 * math.pi * math.sqrt(((R_Earth + h)**3) / mu)
    return T_0

def getDeltaAngle(Phi_s, Phi_max, Delta_s):
    """
    Calculate the entry angle based on given parameters.

    This function computes the entry angle using the provided angles Phi_s, Phi_max, and Delta_s.
    The calculation is based on the formula:
    entry_angle = asin((sin(Phi_s) / sin(Phi_max)) * sin(Delta_s))

    Parameters:
    Phi_s (float): The starting angle in degrees.
    Phi_max (float): The maximum angle in degrees.
    Delta_s (float): The delta angle in degrees.

    Returns:
    float: The calculated entry angle in radians.
    """
    return math.asin((math.sin( math.radians(Phi_s)) / math.sin(math.radians(Phi_max))) * math.sin(math.radians(Delta_s))) 

def satellite_altitude(position):
    """
    Calculate the altitude of a satellite above the Earth's surface.

    Args:
        position (list or array): The position of the satellite in kilometers.

    Returns:
        float: The altitude of the satellite above the Earth's surface in meters.
    """

    R_Earth = 6_371_000  # Average radius of the Earth in meters
    
    # Convert the position to meters
    position_meters = np.array(position) * 1000

    distance_from_earth_center = np.linalg.norm(position_meters)    # Calculate the distance from the center of the Earth
    altitude_above_ground = distance_from_earth_center - R_Earth    # Calculate the altitude above the Earth's surface
    
    return altitude_above_ground



def get_T_p(satellite, Phi_s, time = time_now):
    
    Phi_max = config["Phi_max"]         #! Phi_Max (gradi)
    Delta_s = satellite.model.inclo     #! Delta_s (gradi)

    delta = getDeltaAngle(Phi_s, Phi_max, Delta_s)  # Entry angle in Dome

    geo_Sys = getSystemFromSat(satellite, Geocentric = True, time = time)       # Geocentric System
    position = geo_Sys.position.km

    sat_h = satellite_altitude(position)
    T_o = getOrbitalPeriod(sat_h)                                              # Orbital Period

    T_p = (T_o * math.atan( math.cos(delta) * math.tan(math.radians(Phi_max)))) / math.pi  # Time of Passage in seconds
    return T_p, math.degrees(delta)

# ---------------------------------------------------------------------------- #
#                                    Filter                                    #
# ---------------------------------------------------------------------------- #

def filterSatellitesInView(satellite):
    """
    Input: Satellites
    Output: Boolean value | True : sat is coming in our direction
                          | False : sat is not coming in our direction
    """
    sys = getSystemFromSat(satellite) 
    
    velocity = sys.velocity    

    r = sys.position.km                             # r è la posizione relativa del SAT rispetto all'observer
    r_unit = r / np.linalg.norm(r)                  # Vettore unitario 
    v_rel = np.dot(velocity.km_per_s, r_unit)       # Calcoliamo la velocità calcolando il prodotto scalare tra r e r_unit
    
    return True if v_rel < 0 else False

# ---------------------------------------------------------------------------- #
def getAllSatOnMe(Phi_max=config["Phi_max"], time=time_now, Num_Access_point=config["access_point"]):
    """
    Retrieves all satellites within the observer's dome and buffer zone based on the given parameters.
    Args:
        Phi_max (float): Maximum angle for the dome in degrees. Defaults to config["Phi_max"].
        time (datetime): The current time for satellite position calculations. Defaults to time_now.
        Num_Access_point (int): Number of access points required. Defaults to config["access_point"].
    Returns:
        tuple: A tuple containing:
            - acc_points (list): List of tuples with satellites and their distances that are access points.
            - dome (list): List of tuples with satellites and their distances within the dome but not access points.
            - sat_sort_buff (list): List of tuples with satellites and their distances within the buffer zone.
    """
    
    buffer_Phi = Phi_max - config["Phi_buffer"]             # Angle of a Buffer Zone
    satellites_dome, satellites_buffer = [], []             
    tle_data = TLE_DATA

    # Get all satellites within the observer's dome and buffer zone
    for i in range(0, len(tle_data), 3):
        name = tle_data[i].strip()
        line1 = tle_data[i + 1].strip()
        line2 = tle_data[i + 2].strip()

        satellite = EarthSatellite(line1, line2, name, ts)  # Converting TLE data into SGP4 Satellite Object
        sys = getSystemFromSat(satellite, time=time)        # Reference system 
        
        alt, az, distance = sys.altaz()                     # alt: Altitude in degrees relative to the observer
                                                            # az: Satellite Azimuth Angle relative to the observer
                                                            # distance: Distance between Satellite and Observer
        if alt.degrees > buffer_Phi:
            if alt.degrees > Phi_max:
                satellites_dome.append((satellite, distance.km))
            else:
                # Check if the satellite is coming in our direction
                if filterSatellitesInView(satellite):
                    satellites_buffer.append((satellite, distance.km))

    # Sort satellites based on their position relative to the observer
    sat_sort_dome, sat_sort_buff = sorted(satellites_dome, key=lambda x: x[1]), sorted(satellites_buffer, key=lambda x: x[1])
    
    counter, acc_points, dome = 0, [], []
    if Num_Access_point > len(sat_sort_dome):
        Num_Access_point = len(sat_sort_dome) // 2   # Not enough satellites to satisfy the access point request
    
    # Determine Access Points
    for s in sat_sort_dome:
        if counter < Num_Access_point and filterSatellitesInView(s[0]):
            acc_points.append((s[0], s[1]))
            counter += 1
        else:
            dome.append((s[0], s[1]))
    
    return acc_points, dome, sat_sort_buff

# TODO : Implementa la funazione per capire chi è il miglior satellite che sta per entrare nella cupola
def findOptimalSatellite():
    tle_data = TLE_DATA
    buffer_Phi = config["Phi_max"] - config["Phi_buffer"]       # Angle of a Buffer Zone
    Phi_max = config["Phi_max"]
    satellites = []
    
    # $ Trova tutti i satelliti sopra di me
    for i in range(0, len(tle_data), 3):
        name = tle_data[i].strip()
        line1 = tle_data[i + 1].strip()
        line2 = tle_data[i + 2].strip()

        satellite = EarthSatellite(line1, line2, name, ts)      # Converting tle Data in SGP4 Satellite Object
        sys = getSystemFromSat(satellite)                       
        alt, az, distance = sys.altaz()  

        if alt.degrees < Phi_max and alt.degrees > buffer_Phi and filterSatellitesInView(satellite):      
            # $ Calcola la lunghezza dell'arco di percorrenza nella cupola per ogni satellite
            t_0, angle = get_T_p(satellite, alt.degrees)

            print(f"Satellite: {name} Distance: {distance.km} Phi_s :{alt.degrees} Entry_Angle: {angle} Time in Dome: {t_0 / 60} min")
            #satellites.append((name, distance.km, angle, t_0))
            #print(f"Satellite: {name} Distance: {distance.km} Entry_Angle: {angle} Time in Dome: {t_0 / 60} min")
            # $ Calcola il tempo che ci impiega ogni satellite a raggiungere LOS dato l'arco di percorrenza
            # $ Esegui un ordinamento di questi satelliti per trovare quello che ci mette di più
    
    #sorted_sat = sorted(satellites, key=lambda x: x[1])
    #[print(f"Satellite: {name} Distance: {distance} Entry_Angle: {angle} Time in Dome: {t_0 / 60} min") for name, distance, angle, t_0 in sorted_sat]
# TODO Controlla che il tempo fornito sopra sia lo stesso generato attraverso il find_events (DOPO PRANZO)

#findOptimalSatellite()
# ---------------------------------------------------------------------------- #


def update_time(t_base, t_delta):
    """
    Update Skyfield Time object by adding minutes.

    Args:
        t_base (skyfield.timelib.Time): Base time from ts.now()
        t_delta (int/float): Minutes to add

    Returns:
        skyfield.timelib.Time: Updated time
    """
    current_datetime = t_base.utc_datetime()
    new_datetime = current_datetime + timedelta(minutes=t_delta)
    return ts.from_datetime(new_datetime)




def makeConfigurations(i = time_now, interval = 2, config = 5):
    # ! genera config nel tempo i -> i+interval 
    temp_time = i 
    for z in range(0, config):
        print(f"Configurazione {z} al tempo {temp_time.utc_datetime()}")
        #acc_points, dome, sat_sort_buff = getAllSatOnMe(time = temp_time)
        # Crea topologia


        #Ti raccomando aggiorna i vicini
        #printSatList(acc_points, dome, sat_sort_buff)
        print("-"*20)
        
        temp_time = ts.utc(temp_time.utc_datetime() + timedelta(minutes=interval))

    # ! Salva config dc 

#makeConfigurations()
# ---------------------------------------------------------------------------- #
def check_satellite_visibility(satellite, location, start, end):
    # Intervallo di tempo con step di 1 minuto
    times = ts.utc_range(start.utc_datetime(), end.utc_datetime(), timedelta(minutes=1))
    
    # Trova elevazioni per ogni punto temporale
    elevations = []
    for t in times:
        difference = satellite - location
        topocentric = difference.at(t)
        alt, _, _ = topocentric.altaz()
        elevations.append((t, alt.degrees))
    
    # Filtra le elevazioni tra 20° e 40° e verifica se superano i 40°
    between_20_40 = any(20 <= alt <= 40 for _, alt in elevations)
    exceeds_40 = any(alt > 40 for _, alt in elevations)
    
    return between_20_40 and exceeds_40

def checkConsistency():
    tle_data = TLE_DATA
    satellites = []
    t0 = time_now
    t1 = ts.utc(t0.utc_datetime() + timedelta(minutes=5))


    #Genero la lista di Satelliti
    for i in range(0, len(tle_data), 3):
        name = tle_data[i].strip()
        line1 = tle_data[i + 1].strip()
        line2 = tle_data[i + 2].strip()

        satellite = EarthSatellite(line1, line2, name, ts)
        syst = getSystemFromSat(satellite)
        alt, az, distance = syst.altaz()

        #Prendo i satelliti che sono sopra l'orizzonte
        if alt.degrees > 0:
            satellites.append(satellite)
    
    #Controllo ora tutti i satelliti sull'orizzonte e vedo quelli che stanno venendo nella mia direzione
    print("Satellite in a 1 minute check: \n")
    satellites_events = []
    for sat in satellites:
        t, events = sat.find_events(OBSERVER, t0, t1, altitude_degrees=40)
        for ti, event in zip(t, events):
            syst = getSystemFromSat(sat, time=ti)
            alt, az, distance = syst.altaz()
            if event == 1:
                #print(f"SAT: {sat.name} - Max Elevation: {alt.degrees} - Distance: {distance.km}")
                #print(f"SAT:{sat.name} - Max Elevation: {alt.degrees} at {ti.utc_iso()}")
                satellites_events.append((sat, alt, distance.km, ti.utc_iso()))
    
    sorted(satellites_events, key=lambda x: x[2])
    [print(f"SAT: {sat.name} - Max Elevation: {alt.degrees} - Distance: {distance} al tempo {t} / {t0.utc_datetime()}") for sat, alt, distance, t in satellites_events]
    print("-"*20)
    print("Satellite now: \n")
    
    
    # Troviamo i satelliti che sono sopra di noi ora
    sat_now = []
    for s in satellites:
        syst = getSystemFromSat(s, time = t0)
        alt, az, distance = syst.altaz()
        if alt.degrees > 40:
            #print(f"SAT: {s.name} - Actual Elevation: {alt.degrees} - Distance: {distance.km}")
            sat_now.append((s, alt, distance.km))
    sorted(sat_now, key=lambda x: x[2])
    [print(f"SAT: {sat.name} - Max Elevation: {alt.degrees} - Distance: {distance}") for sat, alt, distance in sat_now]

#checkConsistency()



    