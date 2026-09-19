from abc import ABC, abstractmethod
import globals
import sys
from math import sqrt
from typing import Any, List, Dict, Tuple, Optional

from Task import findAlgorithm, Task
from utils import colorize
from packet import Mode, Packet


# ---------------------------------------------------------
# STRATEGY INTERFACES & CLASSES
# ---------------------------------------------------------
class RoutingStrategy(ABC):
    @abstractmethod
    def route(self, env: Any, manager: Any, task: Task) -> Any:
        pass


class BatmanStrategy(RoutingStrategy):
    def route(self, env: Any, manager: Any, task: Task) -> Any:
        max_neighbor = None
        if task.dest_node in manager.node.ogm_table:
            max_neighbor, _ = self.find_ogm_intersection(
                manager.node.ogm_table[task.dest_node], manager.node.neighbors, task
            )
        else:
            print(f"[{task.id}] {task.dest_node} Route temporaneamente Sconosciuta")
            
        if max_neighbor:
            yield from manager.node.transmit_task(env, task, max_neighbor, 'BATMAN')

    @staticmethod
    def find_ogm_intersection(ogm_table: Dict[str, int], neighbors: List[Any], task: Task) -> Tuple[Any, Any]:
        """
        Trova il vicino migliore incrociando i dati della tabella OGM con i vicini attuali,
        escludendo i nodi già visitati dal task.

        Args:
            ogm_table (Dict[str, int]): Tabella OGM (nodo_destinazione -> distanza).
            neighbors (List[Any]): Lista dei vicini disponibili.
            task (Task): Il task da ruotare (contiene la history dei nodi visitati).

        Returns:
            Tuple[Any, Any]: Una tupla contenente il miglior
                nodo vicino e il relativo valore OGM. Ritorna (None, None) se nessun vicino è valido.
        """
        intersection = {
            neighbor: ogm_table[neighbor.name]
            for neighbor in neighbors
            if (
                neighbor.name in ogm_table
                and neighbor.name not in task.visited
            )
        }

        max_neighbor, max_value = None, None
        if intersection:
            max_neighbor, max_value = max(
                intersection.items(), key=lambda item: item[1])

        return max_neighbor, max_value


class GreedyStrategy(RoutingStrategy):
    def route(self, env: Any, manager: Any, task: Task) -> Any:
        yield from self.greedy_approach(env, manager, task)

    @staticmethod
    def greedy_approach(env: Any, manager: Any, task: Task) -> Any:
        """
        Esegue l'algoritmo GREEDY calcolando la distanza geometrica dei vicini dalla destinazione.

        Args:
            env (Any): L'ambiente SimPy.
            manager (Any): Il RoutingManager del nodo.
            task (Task): Il task da inoltrare.

        Returns:
            Any: Generatore SimPy per l'attesa della trasmissione.
        """
        dest_pos = globals.observer.getPositionVector(globals.ist_in_conf)
        ranker_neighbors = []

        for server in manager.node.neighbors:
            neighbor_distance = RoutingManager.get_pos_proximity(dest_pos, server.getPositionVector(globals.ist_in_conf))
            t = (server, neighbor_distance, server.is_acc_point)
            ranker_neighbors.append(t)

        ranker_neighbors.sort(key=lambda x: (not x[2], x[1]))

        best_server = None
        for neighbor_tuple in ranker_neighbors:
            if neighbor_tuple[0].name not in task.visited:
                best_server = neighbor_tuple[0]
                break

        if best_server:
            yield from manager.node.transmit_task(env, task, best_server, 'GREEDY')


class BatmanGreedyStrategy(RoutingStrategy):
    def route(self, env: Any, manager: Any, task: Task) -> Any:
        max_neighbor = None
        if task.dest_node in manager.node.ogm_table:
            max_neighbor, _ = BatmanStrategy.find_ogm_intersection(
                manager.node.ogm_table[task.dest_node], manager.node.neighbors, task
            )
            
        if max_neighbor:
            yield from manager.node.transmit_task(env, task, max_neighbor, 'BATMAN')
        else:
            yield from GreedyStrategy.greedy_approach(env, manager, task)


class DsrStrategy(RoutingStrategy):
    """
    Gestisce la logica di routing DSR (Dynamic Source Routing).
    Non utilizza la funzione 'route' task-by-task, ma espone metodi statici
    per elaborare asincronamente i pacchetti di Discovery/Reply e i task veri.
    """
    def route(self, env: Any, manager: Any, task: Task) -> Any:
        pass

    @staticmethod
    def process_dsr(env: Any, node: Any) -> None:
        """
        Coordinates the entire DSR (Dynamic Source Routing) cycle for a given node.
        
        This method executes sequentially in zero simulation time, delegating the work
        to two main sub-phases: packet processing (Route Discovery/Reply) and task 
        routing (Route Requests and actual transmissions).
        
        Args:
            env (Any): The SimPy simulation environment.
            node (Any): The network node executing the DSR logic.
            
        Returns:
            None
        """
        neighbors_list, neighbor_map = DsrStrategy._get_dsr_neighbors(node)

        # Fase 1: Smistamento istantaneo dei pacchetti di controllo
        DsrStrategy._process_dsr_packets(node, neighbors_list, neighbor_map)
        
        # Fase 2: Gestione dei Task veri e propri e dei timeout di Route Request
        DsrStrategy._process_dsr_tasks(env, node, neighbors_list, neighbor_map)

    @staticmethod
    def _get_dsr_neighbors(node: Any) -> Tuple[List[Any], Dict[str, Any]]:
        """
        Retrieves and maps the valid neighbors for a node in the DSR context.
        
        Args:
            node (Any): The node whose neighbors are being evaluated.
            
        Returns:
            Tuple[List[Any], Dict[str, Any]]: A tuple containing:
                - neighbors_list (List[Any]): A list of neighbor node objects.
                - neighbor_map (Dict[str, Any]): A dictionary mapping neighbor names to their objects.
        """
        if node.name != 'OBS':
            neighbors_list = list(node.neighbors.keys())
            if node.is_acc_point:
                neighbors_list += [globals.observer]
        else:
            neighbors_list = globals.global_access_point

        neighbor_map = {n.name: n for n in neighbors_list}
        return neighbors_list, neighbor_map

    @staticmethod
    def _process_dsr_packets(node: Any, neighbors_list: List[Any], neighbor_map: Dict[str, Any]) -> None:
        """
        Processes all pending DSR control packets (Route Discovery and Route Reply).
        
        These packets do not consume simulation time (`env.timeout`) or network bandwidth.
        They are processed instantaneously to discover multi-hop paths.
        
        Args:
            node (Any): The node processing its packet queue.
            neighbors_list (List[Any]): A list of valid neighbor objects.
            neighbor_map (Dict[str, Any]): A dictionary mapping neighbor names to objects.
            
        Returns:
            None
        """
        for pkt in node.packets[:]:
            if pkt.mode == Mode.ROUTE_DISCOVERY:
                if pkt.id not in node.pkt_history:
                    if pkt.dest == node.name:
                        pkt.hop_History.append(node.name)
                        DsrStrategy.startRouteReply(node, neighbor_map, pkt)
                    else:
                        for n in neighbors_list:
                            DsrStrategy.sendPkt(node, n, pkt)
                    node.pkt_history.append(pkt.id) 

            elif pkt.mode == Mode.ROUTE_REPLY:
                if pkt.source == node.name:
                    if pkt.taskID not in node.routes:
                        node.routes[pkt.taskID] = []
                    if pkt.hop_History not in node.routes[pkt.taskID]:
                        node.routes[pkt.taskID].append(pkt.hop_History)
                else:
                    lastNodeStack = pkt.node_stack.pop()
                    nextNode = neighbor_map.get(lastNodeStack) 
                    if nextNode is not None:
                        DsrStrategy.sendPkt(node, nextNode, pkt)
            node.packets.remove(pkt)

    @staticmethod
    def _process_dsr_tasks(env: Any, node: Any, neighbors_list: List[Any], neighbor_map: Dict[str, Any]) -> None:
        """
        Processes all pending tasks, initiating Route Discovery or transmitting data.
        
        If a route is known, the task is sent to the next hop via `transmit_task`, which 
        spawns a new SimPy process (`env.process`) to consume real simulation time.
        If no route is known, a Route Discovery phase is initiated or a timeout is evaluated.
        
        Args:
            env (Any): The SimPy simulation environment.
            node (Any): The node evaluating its tasks.
            neighbors_list (List[Any]): A list of valid neighbor objects.
            neighbor_map (Dict[str, Any]): A dictionary mapping neighbor names to objects.
            
        Returns:
            None
        """
        for task in node.tasks:
            if not task.routeRequestIst:
                DsrStrategy.routeDiscovery(node, task, neighbors_list)
            else:
                if node.name == task.source_DSR:
                    timeout = 1 
                    if env.now - task.routeRequestIst > timeout:
                        if task.id in node.routes:
                            nextHop = None
                            node.routes[task.id].sort(key=len)

                            while len(node.routes[task.id]) > 0:
                                route = node.routes[task.id][0].copy()
                                nextHopName = route.pop(0)
                                nextHop = neighbor_map.get(nextHopName)

                                if nextHop is not None:
                                    task.selected_route = route
                                    break 
                                else:
                                    node.routes[task.id].pop(0)
                            
                            if nextHop is not None:
                                env.process(node.transmit_task(env, task, nextHop, 'DSR'))
                            else:
                                task.routeRequestIst = None
                                task.RouteReply = False
                                task.selected_route = []
                                if task.id in node.pkt_history:
                                    node.pkt_history.remove(task.id)
                        else:
                            timeout += 1

                elif node.name == task.dest_node:
                    node.arrived_tasks.append(task)
                    node.tasks.remove(task) 
                    task.routingEndTime = env.now
                    print(colorize(f"[{task.id}] CONSEGNATO! ", "green"))

                else:
                    nextHopName = task.selected_route.pop(0)
                    nextHop = neighbor_map.get(nextHopName)

                    if nextHop is not None:
                        env.process(node.transmit_task(env, task, nextHop, 'DSR'))
                    else:
                        task.routeRequestIst = None
                        task.RouteReply = False
                        task.selected_route = []
                        task.source_DSR = node.name

    @staticmethod
    def routeDiscovery(source: Any, task: Task, neighbors: List[Any]) -> None:
        """
        Initiates a Route Discovery process by broadcasting ROUTE_DISCOVERY packets.
        
        Args:
            source (Any): The node initiating the discovery.
            task (Task): The task that needs to be routed.
            neighbors (List[Any]): List of neighbor objects to broadcast the packet to.
            
        Returns:
            None
        """
        task.routeRequestIst = source.env.now
        for node in neighbors:
            pkt_ID = source.name + "_" + str(source.packets_seq)
            pkt = Packet(pkt_ID, task.id, task.current_node, task.dest_node, Mode.ROUTE_DISCOVERY)
            node.packets.append(pkt)
            pkt.current_node = node.name
            source.pkt_history.append(pkt_ID)
            source.packets_seq += 1
            globals.gbl_packet.append(pkt)

    @staticmethod
    def startRouteReply(source: Any, neighbor_map: Dict[str, Any], pkt: Packet) -> None:
        """
        Converts a ROUTE_DISCOVERY packet into a ROUTE_REPLY packet and sends it back.
        
        Args:
            source (Any): The node generating the reply.
            neighbor_map (Dict[str, Any]): Mapping of neighbor names to node objects.
            pkt (Packet): The Route Discovery packet that reached its destination.
            
        Returns:
            None
        """
        pkt.mode = Mode.ROUTE_REPLY
        last_node_name = pkt.node_stack.pop()
        nextHop = neighbor_map.get(last_node_name)
        
        if nextHop:
            nextHop.packets.append(pkt)
        else:
            if pkt in source.packets:
                print(f"{pkt.id} Rimosso da {source.name}")
                source.packets.remove(pkt)

    @staticmethod
    def sendPkt(source: Any, dest: Any, pkt: Packet) -> None:
        """
        Forwards a packet (Discovery or Reply) to the next hop.
        
        Args:
            source (Any): The current node holding the packet.
            dest (Any): The destination neighbor node.
            pkt (Packet): The packet to be forwarded.
            
        Returns:
            None
        """
        if dest is None:
            print(colorize("[ERROR] Destinazione None nel sendPkt()", "red"))
            sys.exit("ERRORE: destination = None")

        newPkt = pkt.duplicate()
        newPkt.current_node = dest.name
        newPkt.visited.add(source.name)
        newPkt.node_stack.append(source.name)

        if pkt.mode == Mode.ROUTE_DISCOVERY:
            newPkt.hop_History.append(source.name)

        dest.packets.append(newPkt)


# ---------------------------------------------------------
# ROUTING MANAGER
# ---------------------------------------------------------
class RoutingManager:
    """
    Manages the routing decisions for an EdgeServer node using the Strategy Pattern.
    """
    def __init__(self, node: Any):
        self.node = node
        self.strategy = self._initialize_strategy()

    @staticmethod
    def validate_config(config: Dict[str, Any]) -> None:
        """
        Validates the routing configuration to ensure algorithm constraints are met.
        Exits the program if an invalid configuration is detected.
        
        Args:
            config (Dict[str, Any]): Il dizionario globale di configurazione.
            
        Returns:
            None
        """
        batman = config["Routing_algorithm"].get("BATMAN", False)
        greedy = config["Routing_algorithm"].get("GREEDY", False)
        dsr = config["Routing_algorithm"].get("DSR", False)
        
        # 1. Almeno un algoritmo deve essere attivo
        if not batman and not greedy and not dsr:
            sys.exit(colorize("[ERROR] Configurazione Errata: Devi abilitare almeno un algoritmo di routing (BATMAN, GREEDY o DSR).", "red"))
            
        # 2. DSR è esclusivo e non può essere combinato con BATMAN o GREEDY
        if dsr and (batman or greedy):
            sys.exit(colorize("[ERROR] Configurazione Errata: DSR non puo' essere combinato con BATMAN o GREEDY. Usa solo DSR, oppure disabilita DSR e usa BATMAN/GREEDY.", "red"))
            
        print(colorize("[INFO] Configurazione algoritmi di routing validata con successo.", "green"))

    def _initialize_strategy(self) -> Any:
        """
        Inizializza la strategia di routing in base alla configurazione globale.
        
        Returns:
            Any: Un'istanza di RoutingStrategy (BatmanGreedyStrategy, BatmanStrategy, GreedyStrategy, o DsrStrategy).
        """
        # We read the config to determine which strategy to instantiate
        if globals.config["Routing_algorithm"]["BATMAN"] and globals.config["Routing_algorithm"]["GREEDY"]:
            return BatmanGreedyStrategy()
        elif globals.config["Routing_algorithm"]["BATMAN"]:
            return BatmanStrategy()
        elif globals.config["Routing_algorithm"]["GREEDY"]:
            return GreedyStrategy()
        elif globals.config["Routing_algorithm"]["DSR"]:
            return DsrStrategy()
        return None

    def route_tasks(self, env: Any, tasks: List[Task]) -> Any:
        """
        Elabora tutti i task in coda nel nodo ed esegue la strategia selezionata.
        
        Args:
            env (Any): L'ambiente SimPy.
            tasks (List[Task]): La lista dei task presenti nel nodo da elaborare.
            
        Returns:
            Any: Generatore SimPy.
        """
        if len(self.node.neighbors) == 0 or not self.strategy:
            return

        for task in tasks:
            if not task.arrived:
                # Gestione AP Bidirezionale / Monodirezionale
                if globals.config["AP_routing_bidirectional"]:
                    if self.node.is_acc_point:
                        yield from self.deliver_to_Observer(env, 'BIDIRECTIONAL', task)
                        continue
                else:
                    if self.node.elev_angle >= 40:
                        yield from self.deliver_to_Observer(env, 'MONODIRECTIONAL', task)
                        continue

                # Esecuzione dell'algoritmo tramite la strategia scelta
                yield from self.strategy.route(env, self, task)
                
    def deliver_to_Observer(self, env: Any, mode: str, task: Task) -> Any:
        """
        Consegna il task direttamente all'Observer (poiché il nodo è un Access Point).
        
        Args:
            env (Any): L'ambiente SimPy.
            mode (str): Modalità di trasmissione (es. 'BIDIRECTIONAL').
            task (Task): Il task da consegnare.
            
        Returns:
            Any: Generatore SimPy per l'attesa della trasmissione.
        """
        task.routingEndTime = env.now
        algo = findAlgorithm()
        yield from self.node.transmit_task(env, task, globals.observer, algo)

    @staticmethod
    def get_pos_proximity(pos1: List[float], pos2: List[float]) -> float:
        """
        Calcola la distanza euclidea tra due coordinate 3D.
        
        Args:
            pos1 (List[float]): Coordinate (x, y, z) del primo punto.
            pos2 (List[float]): Coordinate (x, y, z) del secondo punto.
            
        Returns:
            float: Distanza tra i due punti.
        """
        x1, y1, z1 = pos1
        x2, y2, z2 = pos2
        return sqrt((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2)
