"""
Base Terminal Entity Module for SECMotionModel.

Defines the abstract base class `BaseTerminal` representing a surface network
endpoint (such as a ground Observer or a maritime Vessel).
"""

from abc import ABC, abstractmethod
from typing import Any, List, Optional
from skyfield.toposlib import GeographicPosition


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

    def getPositionVector(self, t: Any) -> List[float]:
        """
        Return the 3D position vector [x, y, z] in km at time t.

        Args:
            t (Any): Skyfield time object.

        Returns:
            List[float]: 3D Cartesian coordinates [x, y, z] in kilometers.
        """
        return self.position.at(t).position.km.tolist()

    @abstractmethod
    def print_task_summary(self) -> None:
        """
        Print a formatted summary table of tasks arrived at the terminal.

        Returns:
            None
        """
        pass

    def __str__(self) -> str:
        """
        Return a string representation of the terminal.

        Returns:
            str: Class name, terminal name, and position.
        """
        return f"{self.__class__.__name__}(name={self.name}, position={self.position})"


# Convenient alias
Terminal = BaseTerminal
