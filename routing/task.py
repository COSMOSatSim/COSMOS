"""
Definition of the Task class for managing tasks in the satellite network simulation.

This module defines the `Task` class used to represent computational tasks
that are routed through a constellation of LEO satellites. It includes attributes
for tracking the task's source, destination, hop count, routing times, and
algorithms used. Additionally, it provides utility functions for task status
reporting and resolution assignment based on resource requirements.
"""

import sys
import globals
import json5, csv
import os
from pprint import pprint
from typing import Optional

from utils import colorize, _win_longpath
from BaseTerminal import BaseTerminal

config = globals.config
resolution = globals.resolution_config


BATMAN = config["Routing_algorithm"]["BATMAN"]
GREEDY = config["Routing_algorithm"]["GREEDY"]
DSR = config["Routing_algorithm"]["DSR"]


class Task:

    def __init__(
        self,
        task_id: int,
        current_node: str,
        destination: BaseTerminal,
        routingInitTime: float,
        task_type: str,
        image_size: float,
        source: Any = None
    ) -> None:
        """
        Initialize a network Task entity.

        Args:
            task_id (int): Unique task identifier.
            current_node (str): Name of the node currently holding or generating the task.
            destination (BaseTerminal): The destination terminal endpoint (Observer or Vessel).
            routingInitTime (float): Simulation timestamp when routing started.
            task_type (str): Type of task (e.g. 'Generic_Service', 'CPU_Intensive', 'Batch').
            image_size (float): Payload or image size in megabytes (MB).
            source (str, optional): Name of the originating source node. Defaults to current_node.

        Raises:
            TypeError: If destination is not an instance of BaseTerminal.
        """
        if not isinstance(destination, BaseTerminal):
            raise TypeError(f"Task destination must be a BaseTerminal instance, got {type(destination).__name__}")

        self.id = task_id
        self.ttl = 20  # Time to live in HOP
        self.hop = 0  # num_hop
        self.arrived = False  # Arrived Flag
        self.routingInitTime = routingInitTime  # Tempo di partenza
        self.routingEndTime: Optional[float] = None  # Tempo di fine
        self.label = 'ON_SIMULATION'  # Failure Label

        self.task_type = task_type  # Es: "CPU_Intensive"
        self.weight = image_size  # Dimensione Immagine (MB)

        self.source = source
        self.source_node: str = source.name if source is not None else current_node

        self.current_node = current_node  # Server sul quale si trova
        self.destination: BaseTerminal = destination  # Oggetto Terminale di destinazione
        self.dest_node: str = destination.name  # Nome del nodo di destinazione per lookup compatibili

        # self.visited: set[str] = {current_node}# Set Server precedente
        self.visited = set()  # Set Server precedente
        self.visited.add(current_node)  # Aggiungo il primo server (il nome!)

        self.algorithms_used = {}  # Dizionario degli algoritmi utilizzati

        self.hop_History = [current_node]  # Lista di satelliti sui quali sono stato

        # DSR
        self.source_DSR = current_node
        self.routeRequestIst = None  # Timestamp start route Request
        self.RouteReply = False  # Bool allow reply
        self.selected_route = []  # Lista percorso da seguire

        trace = getattr(globals, "task_trace", None)
        if trace is not None:
            trace.emit(
                routingInitTime, "spawn", task_id,
                node=current_node, type=task_type, size_mb=image_size,
            )
    
    def __str__(self):
        """
        String representation of the Task object.
        """
        if self.routingEndTime:
            duration = self.routingEndTime - self.routingInitTime
            return f"|ID:{self.id}\t|Hop:{self.hop}|Init:{self.routingInitTime}|Endt:{self.routingEndTime}|dur:{duration}"

    def add_algorithm(self, algo_name: str):
        """Incrementa il contatore per l'algoritmo usato"""
        if algo_name not in self.algorithms_used:
            self.algorithms_used[algo_name] = 0
        self.algorithms_used[algo_name] += 1

    def get_stat_csv(self) -> tuple:
        if self.routingEndTime:
            duration = self.routingEndTime - self.routingInitTime 
            return self.hop, self.routingInitTime, self.routingEndTime, duration
        else:
            return self.hop, self.routingInitTime, "N/A", "N/A"











def get_algo_percentages(t):
    """
    Calcola le percentuali di utilizzo degli algoritmi per un Task.
    Ritorna un dizionario {algoritmo: percentuale}.
    """
    algo_perc = {}
    total = sum(t.algorithms_used.values())
    if total > 0:
        for algo, count in t.algorithms_used.items():
            algo_perc[algo] = round((count / total) * 100, 2)
    return algo_perc  # se non ci sono algoritmi rimane {}




def makeSummary(folder, TArr, TExp, Tsob, ToS):
    from routing.routing_manager import findAlgorithm
    file = f"SUMMARY[{findAlgorithm()}]_Rout_interval_{str(config.get('Routing_Interval')).replace(',', '.')}.csv"

    # 1) Assicurati che la cartella esista (usando il path assoluto)
    folder_abs = os.path.abspath(folder)
    os.makedirs(folder_abs, exist_ok=True)

    # 2) Costruisci path e applica il prefisso long-path su Windows
    path = os.path.join(folder_abs, file)
    path = _win_longpath(path)

    summary_row = [config["seed"], len(globals.gbl_tasks), TArr, TExp, Tsob, ToS]

    file_exists = os.path.isfile(path)
    with open(path, mode="a", newline="", encoding="utf-8") as summary_file:
        writer = csv.writer(summary_file)
        if not file_exists:
            writer.writerow(["Seed", "TotalTasks", "Arrived", "Expired", "OutOfBuff", "OnSim"])
        writer.writerow(summary_row)

    print(f"Summary info saved to: {path}")



def convert_task_list_in_dict(task_list : list) -> dict:
    result = {}
    for elem in task_list:
        # supporta sia oggetti con attributo .id che dict con chiave 'id'
        if isinstance(elem, dict):
            key = elem.get("id")
        else:
            key = getattr(elem, "id", None)

        if key is None:
            continue

        result[key] = elem
        # stampa lo stato corrente del dizionario dopo ogni inserimento
    return result


def generate_Tasks_Status(csv_filename, folder):
    """
        Questa funzione salva in un file CSV le informazioni sui Task
    """

    total_tasks = []
    print(f"TASK GLOBALI {len(globals.gbl_tasks)} \n", )

    for t in globals.gbl_tasks:
        # Se il task ha un tempo di fine routing, calcola la durata e arrotonda i valori
        if t.routingEndTime is not None:
            durata = round(t.routingEndTime - t.routingInitTime, 2)
            routing_end = round(t.routingEndTime, 2)
        else:
            durata = None
            routing_end = None

        # Crea una lista con le informazioni principali del task
        return_dur = (
            round(t.returnEndTime - t.returnInitTime, 3)
            if getattr(t, "returnEndTime", None) is not None and getattr(t, "returnInitTime", None) is not None
            else None
        )
        rtt_val = round(getattr(t, "rtt", 0.0), 3) if getattr(t, "rtt", None) is not None else None
        g_delay = round(getattr(t, "ground_queue_delay", 0.0), 3) if getattr(t, "ground_queue_delay", None) is not None else None
        c_time = round(getattr(t, "d_cpu", 0.0), 3) if getattr(t, "d_cpu", None) is not None else None
        weight_val = round(getattr(t, "weight", 0.0), 3)

        elem = [
            t.id,  # ID del task
            t.current_node,  # Nodo corrente
            t.hop,  # Numero di hop
            t.label,  # Etichetta di stato
            t.task_type,  # Categoria di task_type
            round(t.routingInitTime, 2),  # Tempo di inizio routing arrotondato
            routing_end,  # Tempo di fine routing arrotondato (se presente)
            durata,  # Durata del routing (se presente)
            get_algo_percentages(t),
            weight_val,
            g_delay,
            c_time,
            return_dur,
            rtt_val
        ]
        # Aggiungi le informazioni del task alla lista totale
        total_tasks.append(elem)

    # FASE DI SORTING
    total_tasks.sort(key=lambda x: x[0])

    TArr, TExp, Tsob, ToS = 0, 0, 0, 0

    # FASE DI STAMPA FORMATTATA
    print(f"TOT TASK IN ROUTING SYS: {len(total_tasks)}\n")
    print(
        "id     | CurrentNode          | Hop | Label           | Resolution    | Start Routing (s) | End Routing (s) | duration      | Algo")
    for elem in total_tasks:
        id_, current_node, hop, label, task_type, routing_start, routing_end, durata, algorithms = elem[:9]
        algorithms_str = ', '.join([f"{k}:{v}%" for k, v in algorithms.items()]) if algorithms else "-"

        row = (
            f"{id_:<6} | {str(current_node):<20} | {hop:<3} | {label:<15} | "
            f"{task_type:<22}| {routing_start:<17} | {str(routing_end):<15} | "
            f"{str(durata):<13} | {algorithms_str}"
        )

        if label in ("TASK_ARRIVED", "ROUND_TRIP_COMPLETED"):
            row = colorize(row, "green")
            TArr += 1
        elif label == "TTL_EXPIRED":
            row = colorize(row, "red")
            TExp += 1
        elif label in ("IN_GROUND_QUEUE", "IN_GROUND_COMPUTE", "COMPLETED_ON_OBSERVER"):
            row = colorize(row, "cyan")
            ToS += 1
        elif label == "RETURN_ON_SIMULATION":
            row = colorize(row, "yellow")
            ToS += 1
        elif label == "SEN_OUT_OF_BUFF":
            row = colorize(row, "orange")
            Tsob += 1
        else:
            ToS += 1

        print(row)

    makeSummary(folder, TArr, TExp, Tsob, ToS)  # Genera il Summary

    print()  # Riga vuota alla fine per separare dall'output successivo

    # FASE DI SCRITTURA CSV
    headers = [
        "TaskID", "CurrentNode", "Hop", "Label", "Resolution",
        "RoutingInitTime", "RoutingEndTime", "Duration", "Algorithms",
        "Weight_MB", "GroundQueueDelay", "ComputeTime", "ReturnDuration", "RTT"
    ]

    # Assicura l'esistenza della cartella del CSV (uso path assoluto)
    csv_dir = os.path.abspath(os.path.dirname(csv_filename) or ".")
    os.makedirs(csv_dir, exist_ok=True)

    csv_path = os.path.join(csv_dir, os.path.basename(csv_filename))
    csv_path = _win_longpath(csv_path)  # <--- prefisso long-path su Windows

    with open(csv_path, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(total_tasks)

    print(f"Task info saved to: {csv_path}")