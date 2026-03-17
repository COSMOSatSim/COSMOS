from skyfield.api import load, wgs84
import topology
from Observer import Observer_Temp
import sys
from SaveCurrentSATOnFile import openTLEFromFile
from user_based_topology import getAllSatOnLine
import numpy as np
from Vessel import Vessel
import json5


def load_vessels_settings(file_path: str = "vessel_setting.json5") -> Vessel:
    """
    This function loads vessel settings from a JSON5 configuration file and returns a list of Vessel instances.
    Args:
        file_path (str): The path to the configuration file.
    Returns:
        Vessel: An instance of the Vessel class.
    """
    with open(file_path, "r") as file:
        data = json5.load(file)
        vessels = []
        for vessel_data in data.get("vessels", []):
            vessel = Vessel(
                name=vessel_data.get("name"),
                position=wgs84.latlon(vessel_data.get("lat"), vessel_data.get("lon")),
            )
            vessels.append(vessel)
        return vessels


def load_obs_settings(file_path: str = "config.json5") -> Observer_Temp:
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


import matplotlib.pyplot as plt
import numpy as np

def plot_corridor_3d(sat_list, pos_A, pos_B, t):
    """
    Visualizza in 3D la Terra, l'Observer (A), il Vessel (B) e i satelliti nel corridoio.
    """
    # Inizializziamo la figura 3D
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')

    # 1. Disegniamo una sfera per rappresentare la Terra (Raggio ~6371 km)
    u = np.linspace(0, 2 * np.pi, 50)
    v = np.linspace(0, np.pi, 50)
    R_earth = 6371.0
    x_earth = R_earth * np.outer(np.cos(u), np.sin(v))
    y_earth = R_earth * np.outer(np.sin(u), np.sin(v))
    z_earth = R_earth * np.outer(np.ones(np.size(u)), np.cos(v))
    
    # Superficie terrestre semi-trasparente (alpha=0.2) per poter vedere "attraverso"
    ax.plot_surface(x_earth, y_earth, z_earth, color='dodgerblue', alpha=0.2, edgecolor='none')

    # 2. Estraiamo le coordinate assolute di A e B al tempo 't'
    vA = pos_A.at(t).position.km
    vB = pos_B.at(t).position.km

    # Plottiamo Observer e Vessel
    ax.scatter(*vA, color='green', s=100, label='Observer (A)', marker='o', depthshade=False)
    ax.scatter(*vB, color='red', s=100, label='Vessel (B)', marker='X', depthshade=False)

    # Disegniamo una linea tratteggiata per unire A e B (utile come riferimento visivo)
    ax.plot([vA[0], vB[0]], [vA[1], vB[1]], [vA[2], vB[2]], color='gray', linestyle='--', label='Line of Sight')

    # 3. Plottiamo i satelliti restituiti dalla tua funzione
    if sat_list:
        # Raccogliamo tutte le coordinate [X, Y, Z] dei satelliti in una matrice NumPy
        sat_coords = np.array([sat.at(t).position.km for sat in sat_list])
        
        # Plottiamo tutti i satelliti in un colpo solo
        ax.scatter(sat_coords[:, 0], sat_coords[:, 1], sat_coords[:, 2], 
                   color='orange', s=40, label='Satellites in Corridor', marker='^', depthshade=False)

    # 4. Impostazioni grafiche (Etichette e Legenda)
    ax.set_xlabel('X (km)')
    ax.set_ylabel('Y (km)')
    ax.set_zlabel('Z (km)')
    ax.set_title('3D View: Satellites in Corridor')
    ax.legend(loc='upper left')

    # 5. Trucco per mantenere le proporzioni 1:1:1 (Altrimenti la Terra sembra un uovo)
    max_range = np.array([x_earth.max()-x_earth.min(), y_earth.max()-y_earth.min(), z_earth.max()-z_earth.min()]).max() / 2.0
    mid_x = (x_earth.max()+x_earth.min()) * 0.5
    mid_y = (y_earth.max()+y_earth.min()) * 0.5
    mid_z = (z_earth.max()+z_earth.min()) * 0.5
    ax.set_xlim(mid_x - max_range, mid_x + max_range)
    ax.set_ylim(mid_y - max_range, mid_y + max_range)
    ax.set_zlim(mid_z - max_range, mid_z + max_range)

    # Mostriamo il grafico!
    plt.show()

def plot_corridor_3d_no_earth(sat_list, pos_A, pos_B, t):
    """
    Visualizza in 3D l'Observer (A), il Vessel (B) e i satelliti nel corridoio,
    senza disegnare la sfera terrestre. La rotta è curva sulla superficie,
    e da ogni satellite scende una linea verticale per mostrare l'altezza.
    """
    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')

    # 1. Estraiamo le coordinate
    vA = pos_A.at(t).position.km
    vB = pos_B.at(t).position.km
    R_earth = 6371.0 # Raggio medio della Terra in km

    # 2. DISEGNIAMO LA ROTTA CURVA SULLA SUPERFICIE
    # Creiamo 50 punti intermedi tra A e B
    t_vals = np.linspace(0, 1, 50)
    arc_points = []
    for val in t_vals:
        # Interpolazione lineare tra vA e vB
        p = (1 - val) * vA + val * vB
        # "Gonfiamo" la linea per farla aderire alla superficie sferica
        p_surface = (p / np.linalg.norm(p)) * R_earth
        arc_points.append(p_surface)
    
    arc_points = np.array(arc_points)
    
    # Plottiamo la curva del terreno
    ax.plot(arc_points[:, 0], arc_points[:, 1], arc_points[:, 2], 
            color='gray', linestyle='--', linewidth=2, label='Superficie Terrestre (Rotta)')

    # Plottiamo Observer e Vessel
    ax.scatter(*vA, color='green', s=100, label='Observer (A)', marker='o', depthshade=False, zorder=5)
    ax.scatter(*vB, color='red', s=100, label='Vessel (B)', marker='X', depthshade=False, zorder=5)

    # 3. PLOTTIAMO I SATELLITI CON I "PILASTRI" DI ALTITUDINE
    if sat_list:
        sat_coords = np.array([sat.at(t).position.km for sat in sat_list])
        
        # Disegniamo i satelliti in orbita
        ax.scatter(sat_coords[:, 0], sat_coords[:, 1], sat_coords[:, 2], 
                   color='orange', s=50, label='Satelliti in Orbita', marker='^', depthshade=False)

        # Disegniamo una linea da ogni satellite giù verso il suolo per mostrare l'altezza
        for sat_pos in sat_coords:
            # Calcoliamo il punto esatto a terra sotto il satellite
            ground_pt = (sat_pos / np.linalg.norm(sat_pos)) * R_earth
            # Tiriamo la linea verticale (stelo)
            ax.plot([ground_pt[0], sat_pos[0]], 
                    [ground_pt[1], sat_pos[1]], 
                    [ground_pt[2], sat_pos[2]], 
                    color='orange', linestyle=':', alpha=0.6)

    # Impostazioni grafiche
    ax.set_xlabel('X (km)')
    ax.set_ylabel('Y (km)')
    ax.set_zlabel('Z (km)')
    ax.set_title('Vista 3D: Altitudine dei Satelliti sulla Rotta')
    ax.legend(loc='upper left')

    # Trucco per mantenere le proporzioni reali 1:1:1
    all_points = np.vstack((arc_points, [vA, vB]))
    if sat_list:
        all_points = np.vstack((all_points, sat_coords))
    
    max_range = np.array([all_points[:,0].max()-all_points[:,0].min(), 
                          all_points[:,1].max()-all_points[:,1].min(), 
                          all_points[:,2].max()-all_points[:,2].min()]).max() / 2.0
    mid_x = (all_points[:,0].max()+all_points[:,0].min()) * 0.5
    mid_y = (all_points[:,1].max()+all_points[:,1].min()) * 0.5
    mid_z = (all_points[:,2].max()+all_points[:,2].min()) * 0.5
    
    ax.set_xlim(mid_x - max_range, mid_x + max_range)
    ax.set_ylim(mid_y - max_range, mid_y + max_range)
    ax.set_zlim(mid_z - max_range, mid_z + max_range)

    plt.show()
    
def manager():

    Vessel = load_vessels_settings()[0]
    observer = load_obs_settings()
    tle_data = openTLEFromFile()
    ts = load.timescale()
    t0 = ts.now()

    
    sats = getAllSatOnLine(
        t=t0, 
        tle_data=tle_data, 
        pos_A=observer.position, 
        pos_B=Vessel.position,
        corridor_deg=10.0
    )
    print(len(sats))
    
    # 2. Passi i risultati e i punti alla funzione di plotting
    #plot_corridor_3d(sats, observer.position, Vessel.position, t0)
    plot_corridor_3d_no_earth(sats, observer.position, Vessel.position, t0)

if __name__ == "__main__":
    manager()
