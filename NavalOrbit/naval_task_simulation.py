"""
Naval Task Simulation Module.

This module provides specialized task assignment functions for the Naval Orbit
scenario, supporting both IN_NETWORK (satellite edge execution) and TO_OBSERVER
(ground execution at Observer) use cases.
"""

import globals
from enums import NavalUseCase
from routing.task import Task
from simulation import network_metrics
from NavalOrbit.Vessel import Vessel

config = globals.config


def _res_len_with_users(res):
    """
    Helper per contare utenti in servizio + task in coda per una risorsa SimPy.
    """
    users_len = len(getattr(res, "users", []))
    queue_len = len(getattr(res, "queue", []))
    return users_len + queue_len


def _handle_in_network_assignment(
    env, selected_server, task_id, image_size,
    arrival_time_system, num_hops, transfer_time,
    task_type, d_cpu, D_r, vessel: Vessel
):
    """
    Gestisce l'Use Case 1 (IN_NETWORK):
    - Il task viene eseguito localmente sul satellite selezionato (CPU/NET).
    - Scala l'energia del satellite (eps_cpu / eps_net).
    - Al termine del calcolo, crea il task del risultato con destinazione la Nave
      (dest_node = vessel.name) e lo inserisce in selected_server.tasks per il ritorno.
    """
    ENABLE_MONITORING = config.get("enable_queue_monitoring", False)

    # Creazione del task virtuale che al termine viaggerà verso la Nave
    task_vessel = Task(
        task_id=task_id,
        current_node=selected_server.name,
        destination=vessel,
        routingInitTime=env.now,
        task_type=task_type,
        image_size=image_size,
        source=vessel
    )

    bw_Bps, data_bytes = network_metrics(image_size)

    if ENABLE_MONITORING:
        task_vessel.d_cpu = d_cpu
        task_vessel.d_net = data_bytes / bw_Bps if bw_Bps > 0 else 0.0
        task_vessel.deadline = arrival_time_system + D_r
        task_vessel.image_size_MB = image_size

    # Attesa del trasferimento iniziale (uplink) verso il selected_server
    yield env.timeout(transfer_time)
    arrival_time_task_queue = env.now

    qlen_on_enqueue_cpu = None
    qlen_on_enqueue_net = None
    eps_cpu, eps_net, time_in_queue = 0.0, 0.0, 0.0
    start_time = env.now

    d_net = data_bytes / bw_Bps if bw_Bps > 0 else 0.0
    eps_net = selected_server.compute_routing_energy(data_bytes, bw_Bps, config.get("Ptrasm", 1.0))
    net_time = data_bytes / bw_Bps if bw_Bps > 0 else 0.0

    try:
        Wn = selected_server.W_net()
    except Exception:
        Wn = getattr(selected_server, "W_net", lambda: 0.0)()

    try:
        Wc = selected_server.W_cpu()
    except Exception:
        Wc = getattr(selected_server, "W_cpu", lambda: 0.0)()

    C_sen = getattr(selected_server, 'C_sen', None)
    if C_sen is None:
        C_sen = globals.rnd.uniform(selected_server.C_sen_min, selected_server.C_sen_max)
    e_coeff = config.get("energy_coefficient", 5e-26)

    # ---------------------------
    # Branch: Generic / CPU_Intensive (solo CPU)
    # ---------------------------
    if task_type in ("Generic_Service", "CPU_Intensive"):
        eps_cpu = selected_server.compute_execution_energy(d_cpu, C_sen, e=e_coeff)
        if selected_server.energy - selected_server.energy_reserved < eps_cpu:
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Insufficient Energy for CPU", d_cpu
            )
            return

        R = Wc + d_cpu + d_net
        if R > D_r:
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Deadline Exceeded", d_cpu
            )
            return

        selected_server.energy_reserved += eps_cpu
        req_cpu = selected_server.cpu_dev.request()
        qlen_on_enqueue_cpu = _res_len_with_users(selected_server.cpu_dev)
        if ENABLE_MONITORING:
            req_cpu.task_data = task_vessel

        yield req_cpu

        if selected_server.energy < eps_cpu:
            selected_server.energy_reserved -= eps_cpu
            selected_server.cpu_dev.release(req_cpu)
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Insufficient Energy for CPU", d_cpu
            )
            return

        time_in_queue = env.now - arrival_time_task_queue
        selected_server.cpu_busy_until = env.now + d_cpu

        yield env.timeout(d_cpu)
        selected_server.cpu_busy_until = env.now

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
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Insufficient Energy for CPU+NET", d_cpu
            )
            return

        R = Wc + d_cpu + Wn + d_net
        if R > D_r:
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Deadline Exceeded", d_cpu
            )
            return

        selected_server.energy_reserved += (eps_cpu + eps_net)
        req_cpu = selected_server.cpu_dev.request()
        qlen_on_enqueue_cpu = _res_len_with_users(selected_server.cpu_dev)
        if ENABLE_MONITORING:
            req_cpu.task_data = task_vessel

        yield req_cpu

        if selected_server.energy < eps_cpu:
            selected_server.energy_reserved -= (eps_cpu + eps_net)
            selected_server.cpu_dev.release(req_cpu)
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Insufficient Energy for CPU", d_cpu
            )
            return

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
            req_net.task_data = task_vessel

        yield req_net

        if selected_server.energy < eps_net:
            selected_server.energy_reserved -= eps_net
            selected_server.net_dev.release(req_net)
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Insufficient Energy for NET", d_cpu
            )
            return

        Wn = env.now - cpu_service_end
        if Wn < 0:
            Wn = 0.0

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
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Insufficient Energy for NET", d_cpu
            )
            return

        R = Wn + d_net
        if R > D_r:
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Deadline Exceeded", d_cpu
            )
            return

        selected_server.energy_reserved += eps_net
        req_net = selected_server.net_dev.request()
        qlen_on_enqueue_net = _res_len_with_users(selected_server.net_dev)
        if ENABLE_MONITORING:
            req_net.task_data = task_vessel

        yield req_net

        if selected_server.energy < eps_net:
            selected_server.energy_reserved -= eps_net
            selected_server.net_dev.release(req_net)
            selected_server.record_rejected_task(
                task_id, task_type, arrival_time_system, image_size,
                "Insufficient Energy for NET", d_cpu
            )
            return

        time_in_queue = env.now - arrival_time_task_queue
        selected_server.net_busy_until = env.now + net_time

        yield env.timeout(net_time)
        selected_server.net_busy_until = env.now

        selected_server.energy -= eps_net
        selected_server.energy_reserved -= eps_net
        selected_server.net_dev.release(req_net)

    # Completamento calcolo
    end_time = env.now
    execution_time = end_time - start_time
    service_time = execution_time + transfer_time + time_in_queue

    # Inserimento nella coda per la spedizione del risultato verso la Nave
    task_vessel.routingInitTime = env.now
    selected_server.tasks.append(task_vessel)
    globals.gbl_tasks.append(task_vessel)

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
        print(f"[{env.now:.3f}] [IN_NETWORK] Task {task_id} eseguito su {selected_server.name}, risultato indirizzato a {vessel.name}")


def _handle_to_observer_assignment(
    env, selected_server, task_id, image_size,
    arrival_time_system, num_hops, transfer_time,
    task_type, d_cpu, D_r, vessel: Vessel
):
    """
    Gestisce l'Use Case 2 (TO_OBSERVER):
    - Il satellite NON esegue la CPU (zero consumo energetico di calcolo su satellite).
    - Attende il transfer_time dell'uplink.
    - Crea il task di andata verso l'Observer (dest_node = 'OBS') e lo inserisce
      in selected_server.tasks affinché la rete ISL lo trasporti a Roma.
    """
    ENABLE_MONITORING = config.get("enable_queue_monitoring", False)

    # Attesa del trasferimento uplink verso il satellite
    yield env.timeout(transfer_time)

    # Creazione del task indirizzato all'Observer
    task_obs = Task(
        task_id=task_id,
        current_node=selected_server.name,
        destination=globals.observer,
        routingInitTime=env.now,
        task_type=task_type,
        image_size=image_size,
        source=vessel
    )

    bw_Bps, data_bytes = network_metrics(image_size)

    if ENABLE_MONITORING:
        task_obs.d_cpu = d_cpu
        task_obs.d_net = data_bytes / bw_Bps if bw_Bps > 0 else 0.0
        task_obs.deadline = arrival_time_system + D_r
        task_obs.image_size_MB = image_size

    # Inserimento nella coda del satellite per avviare il routing verso l'Observer
    selected_server.tasks.append(task_obs)
    globals.gbl_tasks.append(task_obs)

    if ENABLE_MONITORING:
        print(f"[{env.now:.3f}] [TO_OBSERVER] Task {task_id} iniettato in {selected_server.name} con destinazione OBS da {vessel.name}")








def TaskAssignment_Naval(
    env, selected_server, task_id, image_size,
    arrival_time_system, num_hops, transfer_time,
    task_type, d_cpu, D_r,
    vessel: Vessel,
    use_case: NavalUseCase
):
    """
    Dispatcher per l'assegnazione e l'esecuzione del task navale.
    Delega l'effettiva gestione a funzioni dedicate in base allo Use Case.
    """
    if use_case == NavalUseCase.IN_NETWORK:
        # Similar to the original 
        yield from _handle_in_network_assignment(
            env, selected_server, task_id, image_size,
            arrival_time_system, num_hops, transfer_time,
            task_type, d_cpu, D_r, vessel
        )
    elif use_case == NavalUseCase.TO_OBSERVER:
        # New Assignment
        yield from _handle_to_observer_assignment(
            env, selected_server, task_id, image_size,
            arrival_time_system, num_hops, transfer_time,
            task_type, d_cpu, D_r, vessel
        )
    else:
        raise ValueError(f"Use case non riconosciuto: {use_case}")
