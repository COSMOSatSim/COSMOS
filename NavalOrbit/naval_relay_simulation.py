"""
Naval Relay Simulation Module.

Implements the forward relay pipeline for Use Case 2 (TO_OBSERVER):
1. Tasks originate at the surface Vessel in the Atlantic Ocean.
2. Overhead Starlink Access Points are selected using Round Robin to balance uplink load.
3. Uplink transmission is simulated via SimPy timeout based on packet weight and bandwidth.
4. Tasks are injected into the satellite constellation as pure relay packets (no satellite CPU compute).
5. Inter-Satellite Links (ISL) route tasks multi-hop across the ocean corridor to Rome.
6. The Rome Access Point delivers the tasks to the ground Observer terminal.
"""

from typing import Any, Generator, List, Dict
import experiments
import globals
from BaseTerminal import BaseTerminal
from routing.task import Task
from simulation import task_type_and_size_generator, network_metrics
from utils import colorize, format_mb

# Module-level tracking of relay generation and return
relay_generated_tasks: List[Task] = []
ap_selection_counter: Dict[str, int] = {}

return_generated_tasks: List[Task] = []
obs_ap_selection_counter: Dict[str, int] = {}
obs_ap_rr_index: int = 0


def generate_naval_relay_tasks(
    env: Any,
    source: BaseTerminal,
    destination: BaseTerminal,
) -> Generator[Any, Any, None]:
    """
    Continuous SimPy process generating naval tasks at the source vessel and offloading
    them as pure relay packets to overhead Starlink Access Points using Round Robin.

    Tasks are transmitted to the selected Access Point via uplink and then routed
    across the transatlantic ISL corridor to the destination terminal (Observer).
    No edge compute or CPU execution is performed on the satellite constellation during
    this phase.

    Args:
        env (Any): SimPy simulation environment.
        source (BaseTerminal): Originating surface terminal (Vessel).
        destination (BaseTerminal): Destination endpoint terminal (Observer).

    Returns:
        Generator[Any, Any, None]: SimPy generator process.

    Raises:
        TypeError: If source or destination are not instances of BaseTerminal.
        ValueError: If the task inter-arrival distribution is unrecognized.
    """
    if not isinstance(source, BaseTerminal):
        raise TypeError(f"Expected BaseTerminal instance for source, got {type(source).__name__}")
    if not isinstance(destination, BaseTerminal):
        raise TypeError(f"Expected BaseTerminal instance for destination, got {type(destination).__name__}")

    config = globals.config
    distribution_type = config.get("generate_tasks", {}).get("distribution", "exponential")
    distribution_function = getattr(experiments, distribution_type, None)
    if distribution_function is None or not callable(distribution_function):
        raise ValueError(f"Unrecognized inter-arrival distribution type: {distribution_type}")

    print(colorize(f"[RELAY] Avviato generatore di traffico relay: {source.name} -> {destination.name}", "cyan"))
    
    task_id = 1
    ap_rr_index = 0

    while True:
        candidate_aps = source.get_access_points()
        if not candidate_aps:
            # Attendi se nessun Access Point e' temporaneamente visibile sopra la nave
            yield env.timeout(1.0)
            continue

        # 1. Attesa inter-arrivo poissoniana tra un task e il successivo
        arrival_time = distribution_function("Task")
        yield env.timeout(arrival_time)

        # 2. Generazione dei parametri del task (payload in MB, tipo, d_cpu richiesta a terra)
        task_data = task_type_and_size_generator()

        # 3. Selezione AP tramite Round Robin per bilanciare il carico uplink
        selected_ap = candidate_aps[ap_rr_index % len(candidate_aps)]
        ap_rr_index += 1

        ap_selection_counter[selected_ap.name] = ap_selection_counter.get(selected_ap.name, 0) + 1

        # 4. Avvio del processo SimPy di uplink e instradamento in rete
        env.process(_relay_uplink_and_route(
            env=env,
            task_id=task_id,
            source=source,
            selected_ap=selected_ap,
            destination=destination,
            task_data=task_data
        ))

        task_id += 1


def _relay_uplink_and_route(
    env: Any,
    task_id: int,
    source: BaseTerminal,
    selected_ap: Any,
    destination: BaseTerminal,
    task_data: dict,
) -> Generator[Any, Any, None]:
    """
    SimPy process simulating the physical radio uplink of a task from the vessel to an
    Access Point and injecting it into the satellite ISL network.

    Args:
        env (Any): SimPy simulation environment.
        task_id (int): Unique progressive task identifier.
        source (BaseTerminal): Originating vessel terminal.
        selected_ap (Any): Selected EdgeServer acting as Access Point above the vessel.
        destination (BaseTerminal): Destination ground terminal (Observer).
        task_data (dict): Dictionary with task parameters (type, image_size, d_cpu, etc.).

    Returns:
        Generator[Any, Any, None]: SimPy generator process event.
    """
    # 1. Simulazione del tempo di trasmissione radio Uplink Nave -> Satellite AP
    bw_Bps, data_bytes = network_metrics(task_data["image_size"])
    t_uplink = data_bytes / bw_Bps if bw_Bps > 0 else 0.0
    yield env.timeout(t_uplink)

    # 2. Creazione dell'oggetto Task
    task_obj = Task(
        task_id=task_id,
        current_node=selected_ap.name,
        destination=destination,
        routingInitTime=env.now,
        task_type=task_data["type"],
        image_size=task_data["image_size"],
        source=source
    )

    # Custodia dei parametri computazionali da eseguire a terra sull'Observer
    task_obj.d_cpu = task_data.get("d_cpu", 0.0)
    task_obj.required_ram = task_data.get("required_ram", 0)
    task_obj.required_disk = task_data.get("required_disk", 0)

    # Calcolo della deadline per monitoraggio
    raw_delta = globals.config.get("deadline", 0.2)
    try:
        delta_D = float(raw_delta)
        if delta_D >= 1.0: delta_D = delta_D / 100.0
    except Exception:
        delta_D = 0.2
    d_net_est = data_bytes / bw_Bps if bw_Bps > 0 else 0.0
    task_obj.deadline = env.now + (1.0 + delta_D) * (task_obj.d_cpu + d_net_est)

    # 3. Iniezione nella coda del satellite: avvia la traversata ISL transatlantica verso Roma
    selected_ap.tasks.append(task_obj)
    globals.gbl_tasks.append(task_obj)
    relay_generated_tasks.append(task_obj)

    print(f"---> [RELAY] Task {task_id} ({task_obj.task_type}, {task_obj.weight:.2f} MB, d_cpu={task_obj.d_cpu:.2f}s) "
          f"uplink completato su {selected_ap.name} verso {destination.name}")


def TaskAssignment_Observer(
    env: Any,
    observer: BaseTerminal,
    task: Task,
) -> Generator[Any, Any, None]:
    """
    SimPy process that schedules and executes a delivered relay task on the ground Observer's
    multi-core computing resource pool.

    Schedules the task in the Observer's CPU queue (cpu_dev resource), waits for an
    available ground core, executes the computation for the duration of task.d_cpu,
    and updates performance and latency metrics.

    Args:
        env (Any): SimPy simulation environment.
        observer (BaseTerminal): Destination ground terminal holding the cpu_dev resource.
        task (Task): Arrived relay task to be computed on the ground.

    Returns:
        Generator[Any, Any, None]: SimPy generator event.

    Raises:
        AttributeError: If observer does not have an initialized cpu_dev resource.
    """
    if getattr(observer, "cpu_dev", None) is None:
        raise AttributeError(f"Terminal {observer.name} does not have a configured cpu_dev resource.")

    # 1. Registra timestamp di arrivo a terra e hop di andata
    task.forward_hop = task.hop
    task.ground_arrival_time = env.now
    task.label = "IN_GROUND_QUEUE"
    task.status = "IN_GROUND_QUEUE"

    # 2. Richiesta di un core dal pool di elaborazione a terra
    req = observer.cpu_dev.request()
    yield req

    # 3. Core acquisito: calcolo del tempo di attesa in coda a terra
    task.ground_compute_start = env.now
    task.ground_queue_delay = task.ground_compute_start - task.ground_arrival_time
    task.label = "IN_GROUND_COMPUTE"
    task.status = "IN_GROUND_COMPUTE"

    # 4. Esecuzione del calcolo (d_cpu)
    yield env.timeout(task.d_cpu)

    # 5. Rilascio del core CPU
    observer.cpu_dev.release(req)

    # 6. Registrazione metriche di completamento
    task.ground_compute_end = env.now
    task.ground_total_time = task.ground_compute_end - task.ground_arrival_time
    task.label = "COMPLETED_ON_OBSERVER"
    task.status = "COMPLETED_ON_OBSERVER"

    observer.completed_tasks.append(task)

    print(
        colorize(
            f"[*COMPLETED*] [GROUND OBS] Task {task.id} ({task.task_type}) completato su {observer.name} "
            f"(coda: {task.ground_queue_delay:.3f}s, cpu: {task.d_cpu:.2f}s, tot terra: {task.ground_total_time:.3f}s)",
            "green",
        )
    )

    # 7. Avvio del viaggio di ritorno del risultato verso la sorgente (Nave)
    env.process(_relay_return_uplink_and_route(
        env=env,
        task=task,
        observer=observer,
        vessel=task.source,
    ))


def _relay_return_uplink_and_route(
    env: Any,
    task: Task,
    observer: BaseTerminal,
    vessel: BaseTerminal,
) -> Generator[Any, Any, None]:
    """
    SimPy process simulating the physical radio uplink of the completed task result
    from the ground Observer (Rome) to an overhead Starlink Access Point, and injecting
    it into the ISL constellation towards the surface Vessel.

    Uses the task's original payload size (task.weight) assigned by task_type_and_size_generator()
    in accordance with its task type and configuration.

    Args:
        env (Any): SimPy simulation environment.
        task (Task): The completed task object returning to the vessel.
        observer (BaseTerminal): Originating ground terminal (Observer at Rome).
        vessel (BaseTerminal): Destination surface terminal (Vessel in Atlantic).

    Returns:
        Generator[Any, Any, None]: SimPy generator process event.
    """
    global obs_ap_rr_index

    # 1. Trova gli Access Point Starlink visibili sopra Roma
    candidate_aps = observer.get_access_points()
    while not candidate_aps:
        yield env.timeout(1.0)
        candidate_aps = observer.get_access_points()

    # 2. Selezione dell'AP con Round Robin per bilanciare il carico uplink da Roma
    selected_ap = candidate_aps[obs_ap_rr_index % len(candidate_aps)]
    obs_ap_rr_index += 1
    obs_ap_selection_counter[selected_ap.name] = obs_ap_selection_counter.get(selected_ap.name, 0) + 1

    # 3. Simulazione del tempo di trasmissione radio Uplink Terra -> Satellite AP usando il peso originale del task
    bw_Bps, data_bytes = network_metrics(task.weight)
    t_uplink = data_bytes / bw_Bps if bw_Bps > 0 else 0.0
    yield env.timeout(t_uplink)

    # 4. Configurazione dello stato del task per la tratta di ritorno
    task.is_return = True
    task.returnInitTime = env.now

    # Inversione di rotta: la nuova destinazione è la nave
    task.destination = vessel
    task.dest_node = vessel.name
    task.source = observer
    task.source_node = observer.name

    # Reset dei campi di routing per la traversata ISL di ritorno
    task.current_node = selected_ap.name
    task.visited = {selected_ap.name}
    task.ttl = 20
    task.hop = 0
    task.arrived = False
    task.label = 'RETURN_ON_SIMULATION'

    # Iniezione nella coda del satellite AP di Roma
    selected_ap.tasks.append(task)
    return_generated_tasks.append(task)

    print(f"---> [RETURN RELAY] Task {task.id} ({task.task_type}, {task.weight:.2f} MB) "
          f"uplink completato su {selected_ap.name} verso {vessel.name}")


def print_relay_diagnostic_summary(source: BaseTerminal, destination: BaseTerminal) -> None:
    """
    Print a comprehensive diagnostic report of the forward relay execution.
    Verifies delivery rate, lost packets (TTL/dead_tasks), in-flight packets,
    Round Robin AP distribution, network latency, and ground computing metrics.

    Args:
        source (BaseTerminal): Originating vessel terminal.
        destination (BaseTerminal): Destination ground terminal (Observer).

    Returns:
        None
    """
    total_generated = len(relay_generated_tasks)
    total_delivered = len(destination.tasks)
    
    # Raccogli task morti (TTL scaduto) da tutti i server
    total_dead = sum(len(server.dead_tasks) for server in globals.edge_servers)
    dead_task_ids = [t.id for server in globals.edge_servers for t in server.dead_tasks]
    
    # Task ancora in volo nelle code dei satelliti
    in_flight_tasks = [t.id for server in globals.edge_servers for t in server.tasks]
    total_in_flight = len(in_flight_tasks)

    print("\n" + "=" * 70)
    print(colorize("          RELAY FORWARD PIPELINE DIAGNOSTIC REPORT", "cyan"))
    print("=" * 70)
    print(f"Sorgente (Nave):              {source.name}")
    print(f"Destinazione (Observer):      {destination.name}")
    print(f"Totale Task Generati:         {total_generated}")
    print(f"Totale Task Consegnati:       {total_delivered} ({total_delivered/total_generated*100:.2f}% delivery rate)" if total_generated > 0 else "0")
    print(f"Task Persi / TTL Scaduto:     {total_dead} (IDs: {dead_task_ids[:10]}...)")
    print(f"Task in volo a fine sim:      {total_in_flight} (IDs: {in_flight_tasks[:10]}...)")

    print("\n" + "-" * 70)
    print(" Distribuzione Round Robin degli AP di partenza:")
    for ap_name, count in sorted(ap_selection_counter.items(), key=lambda x: -x[1]):
        print(f"   - {ap_name:<25}: {count} task ({count/total_generated*100:.1f}%)" if total_generated > 0 else "")

    if destination.tasks:
        durations = [t.routingEndTime - t.routingInitTime for t in destination.tasks if t.routingEndTime is not None]
        hops = [t.hop for t in destination.tasks]
        
        print("\n" + "-" * 70)
        print(" Metriche di Traversata Transatlantica (One-Way):")
        if durations:
            print(f"   - Latenza Media Andata:   {sum(durations)/len(durations):.3f} s (min: {min(durations):.3f}s, max: {max(durations):.3f}s)")
        if hops:
            from collections import Counter
            hop_dist = Counter(hops)
            print(f"   - Hop Medi Andata:        {sum(hops)/len(hops):.2f} hop")
            print(f"   - Dettaglio Hop:          " + ", ".join(f"{h} hops: {cnt}" for h, cnt in sorted(hop_dist.items())))

    # Metriche di calcolo ed esecuzione a terra sull'Observer
    completed_ground = getattr(destination, "completed_tasks", [])
    total_completed = len(completed_ground)
    in_ground_queue = total_delivered - total_completed
    cpu_res = getattr(destination, "cpu_dev", None)
    cpu_capacity = cpu_res.capacity if cpu_res is not None else "N/A"

    print("\n" + "-" * 70)
    print(" Metriche di Elaborazione a Terra (Ground Computing Observer):")
    print(f"   - Core CPU Pool a Terra:        {cpu_capacity}")
    print(f"   - Task Arrivati a Terra:        {total_delivered}")
    print(f"   - Task Completati su OBS CPU:   {total_completed} ({total_completed/total_delivered*100:.2f}% completamento)" if total_delivered > 0 else "")
    print(f"   - Task in Coda/Esecuzione OBS:  {in_ground_queue}")

    if completed_ground:
        queue_delays = [getattr(t, "ground_queue_delay", 0.0) for t in completed_ground]
        cpu_times = [getattr(t, "d_cpu", 0.0) for t in completed_ground]
        ground_totals = [getattr(t, "ground_total_time", 0.0) for t in completed_ground]
        e2e_latencies = [getattr(t, "ground_compute_end", 0.0) - t.routingInitTime for t in completed_ground if getattr(t, "ground_compute_end", None) is not None]

        print(f"   - Attesa Media Coda a Terra:    {sum(queue_delays)/len(queue_delays):.3f} s (max: {max(queue_delays):.3f}s)")
        print(f"   - Tempo Medio Calcolo CPU:      {sum(cpu_times)/len(cpu_times):.3f} s")
        print(f"   - Tempo Medio Totale a Terra:   {sum(ground_totals)/len(ground_totals):.3f} s")
        if e2e_latencies:
            print(f"   - Latenza Media End-to-End (Andata + Calcolo): {sum(e2e_latencies)/len(e2e_latencies):.3f} s")

    # Metriche di Ritorno e Round-Trip Time (RTT alla Nave)
    rtt_tasks = [t for t in source.tasks if getattr(t, "is_return", False)]
    total_rtt_completed = len(rtt_tasks)
    in_flight_return = len(return_generated_tasks) - total_rtt_completed

    print("\n" + "-" * 70)
    print(" Metriche di Ritorno e Round-Trip Time (RTT alla Nave):")
    print(f"   - Risultati Spediti da Roma:   {len(return_generated_tasks)}")
    print(f"   - Risultati Consegnati su Nave:{total_rtt_completed} ({total_rtt_completed/len(return_generated_tasks)*100:.2f}% return rate)" if return_generated_tasks else "0")
    print(f"   - Risultati in Volo al ritorno:{in_flight_return}")

    if rtt_tasks:
        rtts = [t.rtt for t in rtt_tasks if getattr(t, "rtt", None) is not None]
        ret_durations = [t.returnEndTime - t.returnInitTime for t in rtt_tasks if getattr(t, "returnEndTime", None) is not None]
        ret_hops = [getattr(t, "return_hop", 0) for t in rtt_tasks]

        if rtts:
            print(f"   - RTT Medio Completo:          {sum(rtts)/len(rtts):.3f} s (min: {min(rtts):.3f}s, max: {max(rtts):.3f}s)")
        if ret_durations:
            print(f"   - Latenza Media Solo Ritorno:  {sum(ret_durations)/len(ret_durations):.3f} s (min: {min(ret_durations):.3f}s, max: {max(ret_durations):.3f}s)")
        if ret_hops:
            print(f"   - Hop Medi Solo Ritorno:       {sum(ret_hops)/len(ret_hops):.2f} hop")

    print("=" * 70 + "\n")
