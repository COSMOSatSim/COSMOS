from abc import ABC, abstractmethod
import globals
import sys
from math import sqrt
from Task import findAlgorithm
from utils import colorize

# ---------------------------------------------------------
# STRATEGY INTERFACES & CLASSES
# ---------------------------------------------------------
class RoutingStrategy(ABC):
    @abstractmethod
    def route(self, env, manager, task):
        pass

class BatmanStrategy(RoutingStrategy):
    def route(self, env, manager, task):
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
    def find_ogm_intersection(ogm_table, neighbors, task):
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
    def route(self, env, manager, task):
        yield from self.greedy_approach(env, manager, task)

    @staticmethod
    def greedy_approach(env, manager, task):
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
    def route(self, env, manager, task):
        max_neighbor = None
        if task.dest_node in manager.node.ogm_table:
            max_neighbor, _ = BatmanStrategy.find_ogm_intersection(
                manager.node.ogm_table[task.dest_node], manager.node.neighbors, task
            )
            
        if max_neighbor:
            yield from manager.node.transmit_task(env, task, max_neighbor, 'BATMAN')
        else:
            yield from GreedyStrategy.greedy_approach(env, manager, task)


# ---------------------------------------------------------
# ROUTING MANAGER
# ---------------------------------------------------------
class RoutingManager:
    """
    Manages the routing decisions for an EdgeServer node using the Strategy Pattern.
    """
    def __init__(self, node):
        self.node = node
        self.strategy = self._initialize_strategy()

    @staticmethod
    def validate_config(config):
        """
        Validates the routing configuration to ensure algorithm constraints are met.
        Exits the program if an invalid configuration is detected.
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

    def _initialize_strategy(self):
        # We read the config to determine which strategy to instantiate
        if globals.config["Routing_algorithm"]["BATMAN"] and globals.config["Routing_algorithm"]["GREEDY"]:
            return BatmanGreedyStrategy()
        elif globals.config["Routing_algorithm"]["BATMAN"]:
            return BatmanStrategy()
        elif globals.config["Routing_algorithm"]["GREEDY"]:
            return GreedyStrategy()
        # DSR Strategy will be added here in the next phase
        return None

    def route_tasks(self, env, tasks):
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
                
    def deliver_to_Observer(self, env, mode, task):
        # print(f"[MODE: {mode}]")
        task.routingEndTime = env.now
        algo = findAlgorithm()
        yield from self.node.transmit_task(env, task, globals.observer, algo)

    @staticmethod
    def get_pos_proximity(pos1, pos2):
        x1, y1, z1 = pos1
        x2, y2, z2 = pos2
        return sqrt((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2)
