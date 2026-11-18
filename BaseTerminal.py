"""
Base Terminal Entity Module for SECMotionModel.

Defines the abstract base class `BaseTerminal` representing a surface network
endpoint (such as a ground Observer or a maritime Vessel).
"""

from abc import ABC
from typing import Any, List, Optional
from skyfield.toposlib import GeographicPosition

import globals
from utils import format_mb


class BaseTerminal(ABC):
    """
    Abstract base class for terrestrial and maritime endpoints in the satellite network.

    Both Observer and Vessel inherit from this class to share common telemetry,
    positioning, and task management attributes.
    """

    def __init__(
        self,
        name: str,
        position: GeographicPosition,
        env: Optional[Any] = None,
    ) -> None:
        """
        Initialize the base terminal endpoint.

        Args:
            name (str): Unique name or identifier of the terminal (e.g. 'OBS', 'V-XXXXX').
            position (GeographicPosition): Skyfield WGS84 geographic position object.
            env (Optional[Any], optional): SimPy simulation environment. Defaults to None.
        """
        self.name: str = name
        self.position: GeographicPosition = position
        self.env: Optional[Any] = env
        self.is_terminal: bool = True
        self.is_acc_point: bool = False

        self.tasks: List[Any] = []
        self.arrived_tasks: List[Any] = []
        self.packets: List[Any] = []
        self.cpu_dev: Optional[Any] = None
        self.completed_tasks: List[Any] = []

    def getPositionVector(self, t: Any) -> List[float]:
        """
        Return the 3D position vector [x, y, z] in km at time t.

        Args:
            t (Any): Skyfield time object.

        Returns:
            List[float]: 3D Cartesian coordinates [x, y, z] in kilometers.
        """
        return self.position.at(t).position.km.tolist()

    def get_access_points(self) -> List[Any]:
        """
        Return the list of active Access Point satellites currently visible to this terminal.

        Reads the active AP edge servers registered in the global simulation
        state (globals.access_points) for this terminal's name or instance.

        Returns:
            List[Any]: Active EdgeServer instances currently acting as APs for this terminal,
                       or an empty list if none are visible or configured.
        """
        return globals.access_points.get(self.name) or globals.access_points.get(self, [])

    @property
    def access_points(self) -> List[Any]:
        """
        Dynamic property alias for get_access_points().

        Returns:
            List[Any]: Active EdgeServer instances covering this terminal.
        """
        return self.get_access_points()

    def print_task_summary(self) -> None:
        """
        Print a formatted summary table of tasks arrived at this terminal.

        Returns:
            None
        """
        print(f"TASK ARRIVATI CON SUCCESSO AL TERMINALE ({self.name}): {len(self.tasks)}:\n")
        print(" id     | weight        | resolution            | Start Routing (s) | End Routing (s) | duration      | hop |")
        for task in self.tasks:
            init_time = round(task.routingInitTime, 2)
            if task.routingEndTime is None:
                end_time = "N/A"
                duration = "N/A"
            else:
                end_time = round(task.routingEndTime, 2)
                duration = round(task.routingEndTime - task.routingInitTime, 2)

            weight_val = format_mb(task.weight) if isinstance(task.weight, (int, float)) else str(task.weight)
            print(
                f" {task.id:<6} | {weight_val:<13} | {task.task_type:<21} | {init_time:<17} | {end_time:<15} | {duration:<13} | {task.hop:<3} |"
            )
        print()

    def __str__(self) -> str:
        """
        Return a string representation of the terminal.

        Returns:
            str: Class name, terminal name, and position.
        """
        return f"{self.__class__.__name__}(name={self.name}, position={self.position})"


# Convenient alias
Terminal = BaseTerminal
