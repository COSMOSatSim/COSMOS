from typing import Any
import globals
from routing.routing_manager import DsrStrategy

config = globals.config

# | Secondi | Millisecondi |
# | ------- | ------------ |
# | 1       | 1000 ms      |
# | 0,5     | 500 ms       |
# | 0,1     | 100 ms       |
# | 0,01    | 10 ms        |
# | 0,001   | 1 ms         |

def routing_simulation_process(env: Any) -> Any:
    """
    Questa funzione dovrà scorrere costantemente tutti i task dentro
    la lista dei globali, e costantemente spingerli verso la destinazione.
    Rappresenta il loop di routing del motore di simulazione SimPy.
    
    Args:
        env (Any): L'ambiente SimPy.
        
    Returns:
        Any: Generatore per le attese SimPy.
    """
    interval = config["Routing_Interval"]
    while True:

        if globals.config["Routing_algorithm"].get("DSR", False):
            for node in globals.edge_servers:               # Forwarding per ogni nodo
                DsrStrategy.process_dsr(env, node)
            DsrStrategy.process_dsr(env, globals.observer)  # Forwarding per l'observer
        else:
            for node in globals.edge_servers:
                yield from node.forward_packet(env)    # Eseguiamo il forwarding

        # TODO DIMINUIRE QUESTO VALORE PER rendere il routing più veloce
        yield env.timeout(interval)
