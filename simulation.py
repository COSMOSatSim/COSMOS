from typing import Optional, Any, List, Dict
import globals
import experiments
from routing.task import Task
from BaseTerminal import BaseTerminal
import ILP_simulation

hop = 0  # Inizializza la variabile hop a zero

config = globals.config
resolution_config = globals.resolution_config

c_sen_config_global = config.get("C_sen", 1e9)
if isinstance(c_sen_config_global, dict):
    c_min = c_sen_config_global.get("min", 1e9)
    c_max = c_sen_config_global.get("max", 1e9)
    C_sen = globals.rnd.uniform(c_min, c_max)
else:
    C_sen = float(c_sen_config_global)

bw_MBps = float(config.get("available_bandwidth", {}).get("min", 2150.0))
bw_Bps = bw_MBps * (1024 ** 2) if bw_MBps is not None else 0.0
e_coeff = config.get("energy_coefficient", 5e-26)  # coefficiente energetico (esempio numerico)

def network_metrics(image_size_MB, Volume_size_MB=0.0):
    """
    Calcola la larghezza di banda disponibile (in Bps) e la dimensione totale dei dati (in Byte).

    Args:
        image_size_MB (float): Dimensione dell'immagine in MB.
        Volume_size_MB (float, optional): Dimensione aggiuntiva del volume in MB. Default a 0.0.

    Returns:
        tuple: (bw_Bps, data_bytes)
    """

    # Calcola la dimensione totale dei dati in MB e poi in Byte
    total_data_MB = image_size_MB + Volume_size_MB
    data_bytes = total_data_MB * (1024 ** 2)

    return bw_Bps, data_bytes


def TaskAssignment(
    env,
    selected_server,
    destination: BaseTerminal,
    task_id: int,
    image_size: float,
    arrival_time_system: float,
    num_hops: int,
    transfer_time: float,
    task_type: str,
    d_cpu: float,
    D_r: float,
):
    """
    SimPy process that assigns a task to the selected server and simulates CPU/NET queues and downlinks.

    Simulates queuing on the CPU device, execution, queuing on the network device,
    and downlinking or delivering task results towards the specified destination terminal.

    Args:
        env: SimPy simulation environment.
        selected_server: EdgeServer object executing or holding the task.
        destination (BaseTerminal): Destination endpoint terminal (Observer or Vessel).
        task_id (int): Unique identifier for the task.
        image_size (float): Task data/image size in MB.
        arrival_time_system (float): Simulation timestamp when the task arrived.
        num_hops (int): Number of hops traversed before reaching this server.
        transfer_time (float): Transfer time from the source node to this server.
        task_type (str): Type of task ('Generic_Service', 'CPU_Intensive', 'Batch', etc.).
        d_cpu (float): Estimated CPU demand in seconds.
        D_r (float): Relative deadline for task completion.

    Returns:
        Generator: SimPy generator process.

    Raises:
        TypeError: If destination is not an instance of BaseTerminal.
    """
    if not isinstance(destination, BaseTerminal):
        raise TypeError(f"Expected BaseTerminal instance for destination, got {type(destination).__name__}")

    ENABLE_MONITORING = config.get("enable_queue_monitoring", False)

    task_obj = Task(task_id, selected_server.name, destination, env.now, task_type, image_size, source=selected_server)
    bw_Bps, data_bytes = network_metrics(image_size)

    # Inizializza gli attributi solo se il monitoraggio è attivo
    if ENABLE_MONITORING:
        task_obj.d_cpu = d_cpu
        task_obj.d_net = data_bytes / bw_Bps if bw_Bps > 0 else 0.0
        task_obj.deadline = arrival_time_system + D_r
        task_obj.image_size_MB = image_size

    # aspetta il trasferimento iniziale verso il selected_server
    yield env.timeout(transfer_time)
    arrival_time_task_queue = env.now

    # helper per contare utenti + queue. calcola il numero totale di task associati a una risorsa in un preciso istante, sommando sia i task in servizio sia quelli in coda
    def _res_len_with_users(res):
        # numero di task che stanno attualmente utilizzando la risorsa (res.users)
        users_len = len(getattr(res, "users", []))
        # numero di task che sono attualmente in attesa nella coda (res.queue)
        queue_len = len(getattr(res, "queue", []))
        return users_len + queue_len

    # inizializza variabili di coda per reporting
    qlen_on_enqueue_cpu = None
    qlen_on_enqueue_net = None

    eps_cpu, eps_net, time_in_queue = 0.0, 0.0, 0.0  # energia stimata CPU / NET che useremo per riserve e sottrazioni
    start_time = env.now

    d_net = data_bytes / bw_Bps if bw_Bps > 0 else 0.0

    eps_net = selected_server.compute_routing_energy(data_bytes, bw_Bps, config.get("Ptrasm", 1.0))
    net_time = data_bytes / bw_Bps if bw_Bps > 0 else 0.0

    # stime di attesa (metodi del server; se non esistono, fallback a 0). Wn e Wc sono latenze di attesa stimate nelle code (metodi del server)
    try:
        Wn = selected_server.W_net()
    except Exception:
        Wn = getattr(selected_server, "W_net", lambda: 0.0)()

    try:
        Wc = selected_server.W_cpu()
    except Exception:
        Wc = getattr(selected_server, "W_cpu", lambda: 0.0)()

    # ---------------------------
    # Branch: Generic / CPU_Intensive (solo CPU)
    # ---------------------------
    if task_type in ("Generic_Service", "CPU_Intensive"):
        eps_cpu = selected_server.compute_execution_energy(d_cpu, C_sen, e=e_coeff)
        # Check Pre-Coda
        if selected_server.energy - selected_server.energy_reserved < eps_cpu:
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Insufficient Energy for CPU", d_cpu)
            return

        R = Wc + d_cpu + d_net
        if R > D_r:
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Deadline Exceeded", d_cpu)
            return

        selected_server.energy_reserved += eps_cpu
        req_cpu = selected_server.cpu_dev.request()
        qlen_on_enqueue_cpu = _res_len_with_users(selected_server.cpu_dev)
        if ENABLE_MONITORING:
            req_cpu.task_data = task_obj

        # Attendi CPU
        yield req_cpu

        # === FIX: Check Energia CPU POST-Coda ===
        if selected_server.energy < eps_cpu:
            selected_server.energy_reserved -= eps_cpu
            selected_server.cpu_dev.release(req_cpu)
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Insufficient Energy for CPU", d_cpu)
            return
        # ========================================

        time_in_queue = env.now - arrival_time_task_queue
        selected_server.cpu_busy_until = env.now + d_cpu

        yield env.timeout(d_cpu)
        selected_server.cpu_busy_until = env.now

        # Sottrai energia reale
        selected_server.energy -= eps_cpu
        selected_server.cpu_dev.release(req_cpu)

        BANDWIDTH_TO_GU_BPS = config.get("Bandwidth_to_GU_Bps", 100000)
        file_size_bytes = image_size * (1024 ** 2)
        delay_to_transfer = file_size_bytes / BANDWIDTH_TO_GU_BPS

        yield env.timeout(delay_to_transfer)
        selected_server.energy_reserved -= eps_cpu

    # ---------------------------
    # Branch: CPU_and_Data_Intensive (CPU + NET)
    # ---------------------------
    elif task_type in ("CPU_and_Data_Intensive"):
        eps_cpu = selected_server.compute_execution_energy(d_cpu, C_sen, e=e_coeff)

        if selected_server.energy - selected_server.energy_reserved < (eps_cpu + eps_net):
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Insufficient Energy for CPU+NET", d_cpu)
            return

        R = Wc + d_cpu + Wn + d_net
        if R > D_r:
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Deadline Exceeded", d_cpu)
            return

        selected_server.energy_reserved += (eps_cpu + eps_net)

        req_cpu = selected_server.cpu_dev.request()
        qlen_on_enqueue_cpu = _res_len_with_users(selected_server.cpu_dev)
        if ENABLE_MONITORING:
            req_cpu.task_data = task_obj

        yield req_cpu

        # === FIX: Check Energia CPU POST-Coda ===
        if selected_server.energy < eps_cpu:
            selected_server.energy_reserved -= (eps_cpu + eps_net)
            selected_server.cpu_dev.release(req_cpu)
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Insufficient Energy for CPU", d_cpu)
            return
        # ========================================

        Wc = env.now - arrival_time_task_queue
        selected_server.cpu_busy_until = env.now + d_cpu

        yield env.timeout(d_cpu)
        selected_server.cpu_busy_until = env.now
        selected_server.energy -= eps_cpu
        selected_server.cpu_dev.release(req_cpu)

        cpu_service_end = env.now

        req_net = selected_server.net_dev.request()
        qlen_on_enqueue_net = _res_len_with_users(selected_server.net_dev)
        if ENABLE_MONITORING:
            req_net.task_data = task_obj

        yield req_net

        # === FIX: Check Energia NET POST-Coda ===
        if selected_server.energy < eps_net:
            selected_server.energy_reserved -= eps_net
            selected_server.net_dev.release(req_net)
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Insufficient Energy for NET", d_cpu)
            return
        # ========================================

        Wn = env.now - cpu_service_end
        if Wn < 0: Wn = 0.0

        selected_server.net_busy_until = env.now + net_time

        yield env.timeout(net_time)
        selected_server.net_busy_until = env.now
        selected_server.energy -= eps_net
        selected_server.net_dev.release(req_net)

        time_in_queue = Wc + Wn
        selected_server.energy_reserved -= (eps_cpu + eps_net)

    # ---------------------------
    # Branch: Batch (solo NET)
    # ---------------------------
    elif task_type == "Batch":
        if selected_server.energy - selected_server.energy_reserved < eps_net:
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Insufficient Energy for NET", d_cpu)
            return

        R = Wn + d_net
        if R > D_r:
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Deadline Exceeded", d_cpu)
            return

        selected_server.energy_reserved += eps_net

        req_net = selected_server.net_dev.request()
        qlen_on_enqueue_net = _res_len_with_users(selected_server.net_dev)
        if ENABLE_MONITORING:
            req_net.task_data = task_obj

        yield req_net

        # === FIX: Check Energia NET POST-Coda ===
        if selected_server.energy < eps_net:
            selected_server.energy_reserved -= eps_net
            selected_server.net_dev.release(req_net)
            selected_server.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Insufficient Energy for NET", d_cpu)
            return
        # ========================================

        time_in_queue = env.now - arrival_time_task_queue
        selected_server.net_busy_until = env.now + net_time

        yield env.timeout(net_time)
        selected_server.net_busy_until = env.now

        selected_server.energy -= eps_net
        selected_server.energy_reserved -= eps_net
        selected_server.net_dev.release(req_net)

    # Fine
    end_time = env.now
    execution_time = end_time - start_time
    service_time = execution_time + transfer_time + time_in_queue

    selected_server.tasks.append(task_obj)
    globals.gbl_tasks.append(task_obj)

    if selected_server.elev_angle < config["Phi_max"] - config["Phi_buffer"]:
        task_obj.label = 'SEN_OUT_OF_BUFF'
        if ENABLE_MONITORING:
            print(f"{selected_server} {selected_server.elev_angle}° {task_obj.id} set as {task_obj.label}")

    cpu_q = qlen_on_enqueue_cpu if qlen_on_enqueue_cpu is not None else _res_len_with_users(selected_server.cpu_dev)
    net_q = qlen_on_enqueue_net if qlen_on_enqueue_net is not None else _res_len_with_users(selected_server.net_dev)
    qlen = cpu_q + net_q

    selected_server.task_completed(
        task_id, task_type, arrival_time_system, arrival_time_task_queue,
        start_time, end_time, execution_time, service_time, time_in_queue,
        selected_server.name, num_hops, qlen, transfer_time,
        image_size, DeadLine=False, exec_after_set=False,
        eps_cpu=eps_cpu, eps_net=eps_net
    )

    if ENABLE_MONITORING:
        print(f"[{env.now:.3f}] Task {task_id} served on {selected_server.name}")


def cpu_demand(task_type):
    """
    Ritorna d_cpu (secondi) in base al tipo task.
    """
    if task_type == "Generic_Service":
        params = config["CPU_timeout"].get("gen", config["CPU_timeout"]["default"])
    elif task_type in ("CPU_Intensive", "CPU_and_Data_Intensive"):
        params = config["CPU_timeout"].get("cpui", config["CPU_timeout"]["default"])
    else:
        return 0.0

    mean_seconds = params["mean"]
    return experiments.truncated_exponential_unbounded(mean_seconds)


def _calculate_heuristic_metrics(neighbors_at_distance_one, server_selected,
                                 image_size, Volume_size, task_type, d_cpu, deadline, max_energy,
                                 d_net_predicted, data_bytes_global, bw_Bps_global):
    """
    Calcola le metriche euristiche per tutti i server candidati.
    """
    server_metrics = []

    for neighbor in neighbors_at_distance_one:
        latency_to_server = server_selected.get_latency(neighbor)
        bandwidth_to_server = server_selected.get_bandwidth(neighbor)

        total_data_MB = image_size + Volume_size
        total_data_bytes = total_data_MB * (1024 ** 2)

        if bandwidth_to_server is not None and latency_to_server is not None and bandwidth_to_server > 0:
            bandwidth_to_server_Bps = bandwidth_to_server * (1024 ** 2)
            transfer_time = (total_data_bytes / bandwidth_to_server_Bps) + latency_to_server
            d_net_on_link = total_data_bytes / bandwidth_to_server_Bps
        else:
            transfer_time = 0.0
            d_net_on_link = float('inf')

        selection_score = neighbor.get_selection_score(
            task_type,
            d_cpu=d_cpu,
            d_net=d_net_predicted,
            D_r=deadline,
            energy_budget_max=max_energy,
            file_size_bytes=data_bytes_global,
            bandwidth_Bps=bw_Bps_global
        )

        try:
            waiting_cpu = neighbor.W_cpu()
        except:
            waiting_cpu = getattr(neighbor, "waiting_time", 0.0)
        try:
            waiting_net = neighbor.W_net()
        except:
            waiting_net = 0.0

        waiting_time_adjusted = waiting_cpu + waiting_net
        estimated_execution_time = d_cpu
        expected_completion_time = waiting_time_adjusted + estimated_execution_time + d_net_on_link + transfer_time

        server_metrics.append({
            'server': neighbor,
            'selection_score': selection_score,
            'transfer_time': transfer_time,
            'orbitalSunset': neighbor.orbitalSunset,
            'Sunset': neighbor.elev_angle,
            'expected_completion_time': expected_completion_time
        })

    return server_metrics


def _filter_and_select_best_server(server_metrics, deadline, task_id, task_type,
                                   arrival_time_system, image_size, server_selected, config, d_cpu):
    """
    Filtra la lista di metriche (sunset, deadline) e seleziona il server migliore.
    """
    server_metrics_filtered = [m for m in server_metrics if m['orbitalSunset'] not in (None, 0)]

    reason = "No suitable server found after deadline/sunset filters"
    if not server_metrics_filtered:
        print(f"[Task {task_id}] Nessun server valido trovato (filtro orbitalSunset).")
        server_selected.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                             'Invalid orbitalSunset', d_cpu)
        return None, reason

    sorted_servers = sorted(server_metrics_filtered, key=lambda x: x['selection_score'], reverse=True)

    distribution = config.get("request_distribution", {}).get("distribution", "")
    if distribution in ("DTS-base", "DTS-AP optimal"):
        print(f'[{task_id}] Filtro euristico: DTS-TMAX')
        server_metrics_sorted = [m for m in sorted_servers if m['expected_completion_time'] < deadline]
    else:
        print(f'[{task_id}] Filtro euristico: OrbitAware')
        server_metrics_sorted = [
            m for m in sorted_servers
            if m['expected_completion_time'] < deadline and m['expected_completion_time'] < m['orbitalSunset']
        ]

    if not server_metrics_sorted:
        print(f"[Task {task_id}] Nessun server rimasto dopo i filtri (deadline/sunset).")
        server_selected.record_rejected_task(task_id, task_type, arrival_time_system, image_size, reason, d_cpu)
        return None, reason

    return server_metrics_sorted.pop(0), None


def _finalize_and_assign_task(
    env,
    server_selected,
    server,
    destination: BaseTerminal,
    task_id: int,
    image_size: float,
    Volume_size: float,
    arrival_time_system: float,
    transfer_time: float,
    task_type: str,
    d_cpu: float,
    deadline: float,
    required_ram: int,
    required_disk: int,
    initial_server_counter: dict,
    different_server_counter: dict,
    other_server_counter: dict,
):
    """
    Finalize task routing statistics, deduct energy, record generated task data, and invoke TaskAssignment.

    Args:
        env: SimPy simulation environment.
        server_selected: Origin/Access Point EdgeServer that evaluated the task.
        server: Target EdgeServer selected for executing the task.
        destination (BaseTerminal): Destination endpoint terminal (Observer or Vessel).
        task_id (int): Unique identifier for the task.
        image_size (float): Task data size in MB.
        Volume_size (float): Extra data volume in MB.
        arrival_time_system (float): Simulation timestamp when the task arrived.
        transfer_time (float): Time required to transfer data from server_selected to server.
        task_type (str): Type of task ('Generic_Service', 'CPU_Intensive', etc.).
        d_cpu (float): Execution CPU demand in seconds.
        deadline (float): Relative deadline for the task.
        required_ram (int): Required RAM in MB.
        required_disk (int): Required Disk storage in MB.
        initial_server_counter (dict): Counter dict for tasks arriving at initial servers.
        different_server_counter (dict): Counter dict for offloaded tasks.
        other_server_counter (dict): Counter dict for receiving servers.

    Returns:
        Generator: SimPy generator process for task execution.

    Raises:
        TypeError: If destination is not an instance of BaseTerminal.
    """
    if not isinstance(destination, BaseTerminal):
        raise TypeError(f"Expected BaseTerminal instance for destination, got {type(destination).__name__}")

    num_hops_for_task = 0
    initial_server_counter[server_selected.name] += 1
    data_bytes_global = (image_size + Volume_size) * (1024 ** 2)
    bw_Bps_global = bw_Bps

    if server != server_selected:
        different_server_counter[server_selected.name] += 1
        other_server_counter[server.name] += 1
        num_hops_for_task += 1

        bw_MBps_link = server_selected.get_bandwidth(server)
        if bw_MBps_link is not None and bw_MBps_link > 0:
            bw_Bps_for_energy = bw_MBps_link * (1024 ** 2)
            data_bytes_for_energy = data_bytes_global
        else:
            bw_Bps_for_energy = bw_Bps_global if bw_Bps_global > 0 else 0
            data_bytes_for_energy = data_bytes_global

        if bw_Bps_for_energy > 0:
            Ptrasm = config.get("Ptrasm", 1.0)
            eps_net = server_selected.compute_routing_energy(data_bytes_for_energy, bw_Bps_for_energy, Ptrasm)
        else:
            eps_net = 0.0

        if server_selected.energy < eps_net:
            server_selected.record_rejected_task(task_id, task_type, arrival_time_system, image_size,
                                                 "Routing Energy Exhausted", d_cpu)
            return

        # SOTTRAI ENERGIA
        server_selected.energy -= eps_net
        print(f"[{env.now:.2f}] [Task {task_id}] Routed {server_selected.name} -> {server.name} | "f"E_NET={eps_net:.6f} J | Remaining={server_selected.energy:.2f} J")

        # ---- Qui decidiamo la semantica: contare hop come "performed transfer" ----
        globals.gbl_task_hops[str(task_id)] = globals.gbl_task_hops.get(str(task_id), 0) + 1
        num_hops_local = globals.gbl_task_hops[str(task_id)]

        # Aggiornamento dei contatori di fallback/diversi (rimangono invariati)
        different_server_counter[server_selected.name] += 1
        other_server_counter[server.name] += 1

    task_data = {
        "task_id": task_id,
        "arrival_time": arrival_time_system,
        "type": task_type,
        "ram": required_ram,
        "disk": required_disk,
        "image_size": image_size,
        "exec_time": d_cpu,
        "transfer_time": transfer_time,
        "num_hops": num_hops_for_task,
        "execution_server": server.name
    }
    globals.gbl_generated_tasks_data.append(task_data)

    yield from TaskAssignment(
        env, server, destination, task_id, image_size,
        arrival_time_system, num_hops_for_task, transfer_time,
        task_type, d_cpu, deadline
    )


def SearchNode_Heuristic_v1(
    env,
    server_selected,
    destination: BaseTerminal,
    task_id: int,
    required_ram: int,
    required_disk: int,
    image_size: float,
    Volume_size: float,
    arrival_time_system: float,
    initial_server_counter: dict,
    different_server_counter: dict,
    other_server_counter: dict,
    task_type: str,
    max_energy: float,
    d_cpu: float,
    deadline: float,
):
    """
    Select the best server using the Heuristic v1 policy and assign the task.

    Args:
        env: SimPy simulation environment.
        server_selected: Origin/Access Point EdgeServer where the task entered.
        destination (BaseTerminal): Destination endpoint terminal (Observer or Vessel).
        task_id (int): Unique identifier for the task.
        required_ram (int): Required RAM in MB.
        required_disk (int): Required Disk in MB.
        image_size (float): Image/data size in MB.
        Volume_size (float): Additional volume size in MB.
        arrival_time_system (float): Simulation timestamp when task arrived.
        initial_server_counter (dict): Counter dict for initial candidate servers.
        different_server_counter (dict): Counter dict for offloaded servers.
        other_server_counter (dict): Counter dict for executing servers.
        task_type (str): Type of task.
        max_energy (float): Maximum initial/available energy among candidates.
        d_cpu (float): Execution CPU demand in seconds.
        deadline (float): Relative deadline in seconds.

    Returns:
        Generator: SimPy generator process.

    Raises:
        TypeError: If destination is not an instance of BaseTerminal.
    """
    if not isinstance(destination, BaseTerminal):
        raise TypeError(f"Expected BaseTerminal instance for destination, got {type(destination).__name__}")

    # 1. Ottieni i vicini
    neighbors_at_distance_one = server_selected.get_neighbors()
    neighbors_at_distance_one.append(server_selected)

    # 2. Metriche globali
    bw_Bps_global, data_bytes_global = network_metrics(image_size, Volume_size_MB=Volume_size)
    d_net_predicted = data_bytes_global / bw_Bps_global if bw_Bps_global > 0 else float('inf')

    # 3. Metriche per ogni server
    server_metrics = _calculate_heuristic_metrics(
        neighbors_at_distance_one, server_selected,
        image_size, Volume_size, task_type, d_cpu, deadline, max_energy,
        d_net_predicted, data_bytes_global, bw_Bps_global
    )

    # 4. Selezione
    chosen_metric, reason = _filter_and_select_best_server(
        server_metrics, deadline, task_id, task_type,
        arrival_time_system, image_size, server_selected, config, d_cpu,
    )

    if chosen_metric is None:
        return

    # 5. Assegnazione
    server = chosen_metric['server']
    transfer_time = chosen_metric.get('transfer_time', 0.0)

    yield from _finalize_and_assign_task(
        env, server_selected, server, destination, task_id,
        image_size, Volume_size, arrival_time_system,
        transfer_time, task_type, d_cpu, deadline,
        required_ram, required_disk,
        initial_server_counter, different_server_counter, other_server_counter
    )


# ---------------------------------------------------------------------------
# FUNZIONI CORE (task e generate_tasks)
# ---------------------------------------------------------------------------

def task(
    env,
    task_id: int,
    server,
    destination: BaseTerminal,
    initial_server_counter: dict,
    different_server_counter: dict,
    other_server_counter: dict,
    task_data: dict,
    max_energy: float,
):
    """
    SimPy process handling the lifecycle of an individual generated task.

    Resolves task parameters, selects search node policy (ILP or ERT/Heuristic),
    and routes/executes the task towards the destination terminal.

    Args:
        env: SimPy simulation environment.
        task_id (int): Unique identifier for the task.
        server: Selected initial EdgeServer / Access Point.
        destination (BaseTerminal): Destination endpoint terminal (Observer or Vessel).
        initial_server_counter (dict): Counter dict for initial servers.
        different_server_counter (dict): Counter dict for offloaded tasks.
        other_server_counter (dict): Counter dict for receiving servers.
        task_data (dict): Dictionary with task parameters (d_cpu, deadline, type, size, etc.).
        max_energy (float): Reference maximum energy for score normalization.

    Returns:
        Generator: SimPy generator process.

    Raises:
        TypeError: If destination is not an instance of BaseTerminal.
    """
    if not isinstance(destination, BaseTerminal):
        raise TypeError(f"Expected BaseTerminal instance for destination, got {type(destination).__name__}")

    Volume_size = 0.0
    arrival_time_system = env.now
    d_cpu = task_data.get('d_cpu')
    deadline = task_data.get('deadline')
    required_ram = task_data['required_ram']
    required_disk = task_data['required_disk']
    task_type = task_data['type']
    image_size = task_data['image_size']

    print(f"---> Task {task_id} (Type: {task_type}) arriva in {arrival_time_system:.2f}")

    policy = config.get("SearchNode", "ERT")

    search_node_args = (
        env, server, destination,
        task_id,
        required_ram,
        required_disk,
        image_size,
        Volume_size,
        arrival_time_system, initial_server_counter, different_server_counter, other_server_counter,
        task_type, max_energy, d_cpu, deadline
    )

    if policy == "ILP":
        print(f"--- [{env.now:.2f}] Task {task_id} using SearchNode Policy: v2_ilp_hybrid ---")
        yield from ILP_simulation.SearchNode_ILP_Hybrid_v2(*search_node_args)
    else:
        if policy != "ERT":
            print(
                f"--- [{env.now:.2f}] Task {task_id} WARNING: Unknown policy '{policy}'. Defaulting to v1_heuristic ---")
        print(f"--- [{env.now:.2f}] Task {task_id} using SearchNode Policy: v1_heuristic ---")
        yield from SearchNode_Heuristic_v1(*search_node_args)


def generate_tasks(
    env: Any,
    initial_server_counter: dict,
    different_server_counter: dict,
    other_server_counter: dict,
    destination: BaseTerminal,
    source: Optional[BaseTerminal] = None,
):
    """
    SimPy continuous process that periodically generates tasks and offloads them to Access Points.

    Tasks originate at the source terminal and are offloaded to currently visible Access
    Points covering that terminal. After intermediate satellite routing and execution,
    the results are routed to the destination terminal. When source is omitted or None,
    it defaults to destination (representing single-terminal symmetric generation and consumption).

    Args:
        env (Any): SimPy simulation environment.
        initial_server_counter (dict): Counter dict for initial candidate servers.
        different_server_counter (dict): Counter dict for offloaded servers.
        other_server_counter (dict): Counter dict for executing servers.
        destination (BaseTerminal): Destination endpoint terminal receiving the final results.
        source (Optional[BaseTerminal], optional): Source endpoint terminal generating the tasks.
            If None, defaults to the destination terminal (symmetric generation and consumption).
            Defaults to None.

    Returns:
        Generator: SimPy generator process event.

    Raises:
        TypeError: If destination is not an instance of BaseTerminal, or if source
            is explicitly provided but is not an instance of BaseTerminal.
        ValueError: If distribution type in config is unrecognized.
    """
    if not isinstance(destination, BaseTerminal):
        raise TypeError(f"Expected BaseTerminal instance for destination, got {type(destination).__name__}")

    if source is None:
        source = destination
    elif not isinstance(source, BaseTerminal):
        raise TypeError(f"Expected BaseTerminal instance for source, got {type(source).__name__}")

    global arrival_time
    print('Genero i task')

    task_id = 1
    while True:
        candidate_servers = source.get_access_points()
        if not candidate_servers:
            # Attendi se nessun AP è attualmente visibile sopra la sorgente
            yield env.timeout(1.0)
            continue

        max_energy = max(server.energy for server in candidate_servers)
        distribution_type = config["generate_tasks"]["distribution"]
        distribution_function = getattr(experiments, distribution_type)

        if distribution_function is not None and callable(distribution_function):
            arrival_time = distribution_function('Task')
        else:
            raise ValueError("Unrecognized distribution type")
        yield env.timeout(arrival_time)

        temp_task_data = task_type_and_size_generator()
        d_cpu = temp_task_data['d_cpu']
        raw_delta = config.get("deadline", 0.2)
        try:
            delta_D = float(raw_delta)
            if delta_D >= 1.0: delta_D = delta_D / 100.0
        except Exception:
            delta_D = 0.2
        if delta_D < 0.0:
            delta_D = 0.0
        elif delta_D > 1.0:
            delta_D = 1.0

        bw_Bps, data_bytes = network_metrics(temp_task_data['image_size'])
        d_net_predicted = data_bytes / bw_Bps if bw_Bps > 0 else float('inf')

        D_r = (1.0 + delta_D) * (d_cpu + d_net_predicted)
        temp_task_data['deadline'] = D_r

        best_server = None
        best_score = float('-inf')
        for server in candidate_servers:
            score = server.get_selection_score(
                temp_task_data['type'],
                d_cpu=d_cpu,
                d_net=d_net_predicted,
                D_r=D_r,
                energy_budget_max=max_energy,
                file_size_bytes=data_bytes,
                bandwidth_Bps=bw_Bps
            )
            if score > best_score:
                best_score = score
                best_server = server

        if best_server is None:
            print(f"[Task {task_id}] Nessun server scelto in base all'euristica.")
            task_id += 1
            continue

        env.process(task(
            env, task_id, best_server, destination,
            initial_server_counter, different_server_counter, other_server_counter,
            temp_task_data, max_energy
        ))

        task_id += 1


def task_type_and_size_generator():
    """Genera i parametri del task senza avviarlo."""
    if not resolution_config: raise RuntimeError("Configurazione risoluzione task non caricata correttamente.")

    required_ram = globals.rnd.randint(config["required_ram"]["min"], config["required_ram"]["max"])
    required_disk = globals.rnd.randint(config["required_disk"]["min"], config["required_disk"]["max"])
    betas = resolution_config["beta_probabilities"]
    ranges = resolution_config["size_ranges_MB"]
    cpu_data_params = ranges["CPU_DATA_INTENSIVE"]
    batch_params = ranges["BATCH_TASK"]

    r = globals.rnd.random()
    if r < betas["Generic_Service"]:
        task_type = "Generic_Service"
        image_size = globals.rnd.uniform(*ranges["GENERIC_CPU_RANGE"])
    elif r < betas["Generic_Service"] + betas["CPU_Intensive"]:
        task_type = "CPU_Intensive"
        image_size = globals.rnd.uniform(*ranges["GENERIC_CPU_RANGE"])
    elif r < betas["Generic_Service"] + betas["CPU_Intensive"] + betas["CPU_and_Data_Intensive"]:
        task_type = "CPU_and_Data_Intensive"
        r2 = globals.rnd.random()
        if r2 < cpu_data_params["alpha_M_weight"]:
            image_size = globals.rnd.uniform(*cpu_data_params["M_range"])
        elif r2 < cpu_data_params["alpha_M_weight"] + cpu_data_params["alpha_H_weight"]:
            image_size = globals.rnd.uniform(*cpu_data_params["H_range"])
        else:
            image_size = globals.rnd.uniform(*cpu_data_params["VH_range"])
    else:
        task_type = "Batch"
        r3 = globals.rnd.random()
        if r3 < batch_params["gamma_H_weight"]:
            image_size = globals.rnd.uniform(*batch_params["H_range"])
        else:
            image_size = globals.rnd.uniform(*batch_params["VH_range"])

    d_cpu = cpu_demand(task_type)

    return {
        'type': task_type,
        'image_size': image_size,
        'required_ram': required_ram,
        'required_disk': required_disk,
        'd_cpu': d_cpu
    }


def enqueue_batch_in_net(
    env,
    server_obj,
    destination: BaseTerminal,
    task_id: int,
    image_size_MB: float,
    arrival_time_system: float,
    deadline_relative: float,
):
    """
    SimPy process to enqueue a batch task directly into a server's network queue.

    Args:
        env: SimPy simulation environment.
        server_obj: EdgeServer receiving the batch task.
        destination (BaseTerminal): Destination endpoint terminal (Observer or Vessel).
        task_id (int): Unique identifier for the batch task.
        image_size_MB (float): Size of the batch task data in MB.
        arrival_time_system (float): Simulation timestamp when the batch task arrived.
        deadline_relative (float): Relative deadline for batch transmission.

    Returns:
        Generator: SimPy generator process.

    Raises:
        TypeError: If destination is not an instance of BaseTerminal.
    """
    if not isinstance(destination, BaseTerminal):
        raise TypeError(f"Expected BaseTerminal instance for destination, got {type(destination).__name__}")

    print(f"[ENQUEUE_BATCH] Called id={task_id} on {server_obj.name} at time={env.now:.3f}")

    task_obj = Task(task_id, server_obj.name, destination, arrival_time_system, "Batch", image_size_MB, source=server_obj)
    print(f"[ENQ_DBG START] id={task_id} server={server_obj.name} at={env.now:.3f}")
    print(f"  image_size_MB={image_size_MB:.3f}")
    bw_Bps, data_bytes = network_metrics(image_size_MB)
    print(
        f"  bw_Bps={bw_Bps:.3f}, data_bytes={data_bytes}, computed d_net={data_bytes / bw_Bps if bw_Bps > 0 else 'inf'}")
    task_obj.d_net = data_bytes / bw_Bps if bw_Bps > 0 else float('inf')
    task_obj.deadline = arrival_time_system + deadline_relative
    task_obj.image_size_MB = image_size_MB

    eps_net = server_obj.compute_routing_energy(data_bytes, bw_Bps, config.get("Ptrasm", 1.0))
    print(
        f"  EPS_NET calc={eps_net:.6f} energy_before={server_obj.energy:.6f} reserved_before={server_obj.energy_reserved:.6f}")

    # --- FIX 1: Controllo iniziale energia ---
    if server_obj.energy - server_obj.energy_reserved < eps_net:
        server_obj.record_rejected_task(task_id, "Batch", arrival_time_system, image_size_MB,
                                        "Insufficient Energy for Batch", 0.0)
        return

    server_obj.energy_reserved += eps_net
    req = server_obj.net_dev.request()
    req.task_data = task_obj

    print(f"[{env.now:.3f}] ENQUEUE BATCH id={task_id} on {server_obj.name}")
    yield req

    # --- FIX 2: Check Energia POST-Coda ---
    if server_obj.energy < eps_net:
        server_obj.energy_reserved -= eps_net
        print(
            f"[ENQ_DBG SUB] id={task_id} server={server_obj.name} energy_after={server_obj.energy:.6f} reserved_after={server_obj.energy_reserved:.6f}")

        server_obj.net_dev.release(req)
        server_obj.record_rejected_task(task_id, "Batch", arrival_time_system, image_size_MB,
                                        "Insufficient Energy during Batch Queue", 0.0)
        return

    if bw_Bps > 0:
        net_time = data_bytes / bw_Bps
    else:
        net_time = float('inf')

    server_obj.net_busy_until = env.now + net_time
    yield env.timeout(net_time)

    start_service_time = env.now - net_time
    time_in_queue_batch = start_service_time - arrival_time_system
    server_obj.net_busy_until = env.now
    total_service_time = net_time + time_in_queue_batch

    # --- FIX 3: Sottrazione Energia Reale ---
    server_obj.energy -= eps_net
    server_obj.energy_reserved -= eps_net
    server_obj.net_dev.release(req)

    server_obj.task_completed(
        task_id, "Batch", arrival_time_system, arrival_time_system,
        start_service_time, env.now, net_time, total_service_time, time_in_queue_batch,
        server_obj.name, 0, len(server_obj.net_dev.queue),
        0.0, image_size_MB,
        DeadLine=False, exec_after_set=False,
        eps_cpu=0.0, eps_net=eps_net
    )

    try:
        completed_tuple = (
            task_id, "Batch", arrival_time_system, arrival_time_system,
            env.now - net_time, env.now, net_time, total_service_time, time_in_queue_batch,
            server_obj.name, 0, len(server_obj.net_dev.queue), 0.0, image_size_MB,
            False, 0.0, eps_net, eps_net, server_obj.energy
        )
        globals.gbl_batch_completed.append(completed_tuple)
    except Exception as e:
        print(f"ERROR saving batch completion: {e}")

    print(f"[{env.now:.3f}] BATCH id={task_id} served on {server_obj.name}")