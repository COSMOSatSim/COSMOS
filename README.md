# SECMotionModel: Satellite Edge Computing Motion Simulation Model

SECMotionModel is a discrete-event simulation (DES) platform built on Python and [SimPy](https://simpy.readthedocs.io/), designed to model and analyze **Satellite Edge Computing (SEC)** in Low Earth Orbit (LEO) constellations. This project was developed to evaluate how satellite movement impacts coverage, latency, energy consumption, and task offloading efficiency.

## 🚀 Overview

As LEO satellite constellations (like Starlink) grow, the possibility of using satellites as "Edge Computing" nodes becomes viable. This project simulates the interaction between stationary ground users (Observers) and a dynamic constellation of satellites that provide both connectivity and computational resources.

---

## 🛠 Project Structure

The project follows a clean, modular architecture:

- **`main.py`**: The primary entry point for a single simulation run. It initializes the SimPy environment and starts the simulation processes.
- **`launcher.py`**: Orchestrates batch simulation runs using multiprocessing locally.
- **`setup_simulator.py`**: Automated wrapper script for generating orbital mechanics data during the first execution.
- **`config/`**: Directory containing JSON5 configuration files for simulation logic and task generation.
- **`topology/`**: Package managing the dynamic network topology (`core.py`) and orbital mechanics using the Skyfield library (`Satellite.py`).
- **`routing/`**: Package containing the routing engine (`routing_manager.py`), tasks (`task.py`), and graph management (`ogm_manager.py`).
- **`slurm_jobs/`**: Package containing Slurm Array bash scripts and Python config generators for massive parallel execution on cluster nodes.
- **`EdgeServer.py`**: Contains the logic for satellites acting as computational nodes, including resource management (CPU, Network, RAM, Disk).
- **`Observer.py`**: Represents the ground entities (users) that generate and offload tasks to the satellite network.
- **`globals.py`**: Centralized state management.

---

## 📥 Requirements

Ensure you have Python 3.8+ installed. You can install the required dependencies using:

```bash
pip install simpy skyfield json5 numpy pandas tqdm matplotlib
```
*(Tip: We recommend using an isolated virtual environment or `uv`).*

---

## 🏃 First-Time Setup

Computing LEO orbital mechanics for every millisecond of a simulation is computationally expensive. Therefore, the simulator uses a **Data Materialization** approach: it pre-calculates the satellite topology and saves it to JSON files.

**Before running the simulation for the first time, you must build these matrices.**
We have provided an automated script for this:

```bash
python setup_simulator.py
```
*What it does: This script will temporarily set `Build_Configurations: True` in your `config.json5`, run the `main.py` generation routine, and automatically set it back to `Load_Configuration: True` when finished. You only need to run this once!*

---

## 🎮 Running the Simulation

Once the setup is complete, you have three ways to run the simulator:

### 1. Single Run (Local)
To execute a single simulation using the parameters defined in `config/config.json5`:
```bash
python main.py
```

### 2. Batch Run (Local Multiprocessing)
To run multiple simulations in parallel locally (sweeping across parameters):
```bash
python launcher.py
```

### 3. Array Run (Slurm Cluster)
If you are running on an HPC cluster managed by Slurm, use the highly optimized native Slurm Arrays:
1. Generate the configuration sets:
   ```bash
   python slurm_jobs/configsGenerator.py
   ```
2. Submit the chunked array job to the cluster (Work only in the cluster):
   ```bash
   sbatch slurm_jobs/submit_array.sh
   ```

---

## 📊 Results and Analysis

Simulation results are automatically saved in the `result/` directory as CSV files. These files contain detailed logs of:
- Task execution times, queue times, and total latencies.
- Energy consumption tracking of Edge Servers.
- Success/failure rates of task offloading based on deadlines.

You can use the scripts provided in the `Plotters/` directory to parse and visualize the results.
