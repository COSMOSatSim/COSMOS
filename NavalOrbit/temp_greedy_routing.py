import numpy as np
from globals import config

def simulate_greedy_hops(sats_list, topology_graph, start_sat_name, target_vessel, t):
    """
    Simulates a greedy routing algorithm over the static graph at time 't'.
    
    Args:
        sats_list: List of Satellite objects (from getAllSatOnLine).
        topology_graph: Dict returned by build_topology_network {sat_name: [(neighbor_name, dist, latency), ...]}.
        start_sat_name: Name of the satellite acting as Access Point for the Observer.
        target_vessel: Vessel object acting as destination.
        t: Skyfield Time object representing the current instant.
        
    Returns:
        int: Number of hops to reach the vessel, or -1 if no path was found (dead end / loop).
    """
    # In monodirectional mode, the satellite must be within the central dome (e.g. 40 degrees)
    min_elevation = config["Phi_max"]
    
    # Dizionario veloce per recuperare gli oggetti Satellite dal nome
    sats_dict = {sat.name: sat for sat in sats_list}
    
    current_node = start_sat_name
    visited = set([current_node])
    path = [current_node]
    hops = 0
    
    # Pre-calcola il vettore posizione della nave in km al tempo t
    vessel_pos_km = target_vessel.position.at(t).position.km
    
    while True:
        # 1. Controlliamo se siamo arrivati a destinazione (se current_node vede la nave)
        current_sat_obj = sats_dict[current_node].satellite
        difference = current_sat_obj - target_vessel.position
        alt, _, _ = difference.at(t).altaz()
        
        if alt.degrees > min_elevation:
            # Siamo sopra la nave! Routing completato.
            return hops, path
            
        # 2. Otteniamo i vicini del nodo corrente
        neighbors = topology_graph.get(current_node, [])
        unvisited_neighbors = [n[0] for n in neighbors if n[0] not in visited and n[0] in sats_dict]
        
        if not unvisited_neighbors:
            # Vicolo cieco o routing in loop!
            return -1, path
            
        # 3. Cerchiamo il vicino più promettente (quello geograficamente più vicino alla nave)
        best_neighbor = None
        min_dist_to_vessel = float('inf')
        
        for neighbor_name in unvisited_neighbors:
            neighbor_sat_obj = sats_dict[neighbor_name].satellite
            neighbor_pos_km = neighbor_sat_obj.at(t).position.km
            dist_to_vessel = np.linalg.norm(neighbor_pos_km - vessel_pos_km)
            
            if dist_to_vessel < min_dist_to_vessel:
                min_dist_to_vessel = dist_to_vessel
                best_neighbor = neighbor_name
                
        # 4. Hop verso il best_neighbor
        current_node = best_neighbor
        visited.add(current_node)
        path.append(current_node)
        hops += 1
