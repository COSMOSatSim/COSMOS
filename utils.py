"""
Module for utility functions in the satellite network simulation.

This module includes helper functions for sending tasks between satellites,
calculating transmission times, and colorizing terminal output for better
readability.
"""

import globals



def colorize(text: str, color: str) -> str:
    """
    Colora una stringa con i codici ANSI per il terminale.

    Args:
        text (str): La stringa da colorare.
        color (str): Il colore (es: "red", "green", "yellow", "blue", "magenta", "cyan", "white").

    Returns:
        str: La stringa colorata con codici ANSI.
    """
    colors = {
        "black": "\033[30m",
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "white": "\033[97m",
        "reset": "\033[0m",
        "orange": "\033[33m"
    }

    start = colors.get(color.lower(), "")
    end = colors["reset"] if start else ""
    return f"{start}{text}{end}"

import sys
import json



def saveInfoInFile(file: str, value_dictionary: dict, N_config: str) -> None:
    try:
        with open(file, "r") as f:
            data = json.load(f)
    except Exception as e:
        data = {}

    # Scrivo la nuova configurazione
    data[str(N_config)] = value_dictionary

    with open(file, "w") as f:
        json.dump(data, f, indent=4)

def transmission_failure_probability(distance: float, laser_range: float) -> float:
    # Probabilità di fallimento cresce linearmente con la distanza
    return round(min(1.0, distance / laser_range), 2)

def print_dict(d: dict, level: int = 0) -> None:
    indent = '\t' * level

    if isinstance(d, dict):
        for key, value in d.items():
            if isinstance(value, (dict, list)):
                print(f"{indent}{key}:")
                print_dict(value, level + 1)
            else:
                print(f"{indent}{key}:\t{value}")
    elif isinstance(d, list):
        for i, item in enumerate(d):
            if isinstance(item, (dict, list)):
                print(f"{indent}[{i}]:")
                print_dict(item, level + 1)
            else:
                print(f"{indent}[{i}]:\t{item}")
    else:
        print(f"{indent}{d}")

import os
def _win_longpath(p: str) -> str:
    """Rende il path compatibile con i percorsi lunghi di Windows usando il prefisso \\?\\."""
    if os.name != "nt":
        return p
    # normalizza/assolutizza
    p = os.path.abspath(p)
    if p.startswith("\\\\?\\"):
        return p  # già esteso
    if p.startswith("\\\\"):        # UNC -> \\?\UNC\server\share\...
        return "\\\\?\\UNC" + p[1:]
    return "\\\\?\\" + p
