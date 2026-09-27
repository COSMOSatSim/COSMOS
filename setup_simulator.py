import json5
import subprocess
import sys
import os
from utils import colorize

CONFIG_PATH = "config/config.json5"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        sys.exit(colorize(f"[!] ERROR: File {CONFIG_PATH} not found.", "red"))
    with open(CONFIG_PATH, 'r') as f:
        return json5.load(f)

def save_config(data):
    with open(CONFIG_PATH, 'w') as f:
        json5.dump(data, f, indent=4)

def main():
    print(colorize("=" * 60, "cyan"))
    print(colorize(" SECMotionModel - First Run Setup ", "cyan"))
    print(colorize("=" * 60, "cyan"))
    print(colorize("\n[1] Modifying config.json5 to force Topology generation...", "yellow"))
    
    cfg = load_config()
    
    # Save original state for safety
    original_build = cfg.get("Build_Configurations", False)
    original_redist = cfg.get("redistribuite_OGM", False)
    original_load = cfg.get("Load_Configuration", True)

    # Force parameters for setup
    cfg["Build_Configurations"] = True
    cfg["redistribuite_OGM"] = False
    cfg["Load_Configuration"] = False
    save_config(cfg)

    print(colorize("[2] Running main.py to generate satellite matrices...", "yellow"))
    try:
        # Use the same Python executable that launched this script
        subprocess.run([sys.executable, "main.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(colorize(f"\n[!] ERROR DURING main.py EXECUTION (Exit code: {e.returncode})", "red"))
        print(colorize("Restoring configuration file...", "yellow"))
        cfg["Build_Configurations"] = original_build
        cfg["redistribuite_OGM"] = original_redist
        cfg["Load_Configuration"] = original_load
        save_config(cfg)
        sys.exit(1)

    print(colorize("\n[3] Generation completed successfully!", "green"))
    print(colorize("[4] Restoring config.json5 for standard simulations (Load_Configuration = True)...", "yellow"))
    
    cfg = load_config()
    cfg["Build_Configurations"] = False
    cfg["redistribuite_OGM"] = False
    cfg["Load_Configuration"] = True
    save_config(cfg)

    print(colorize("\n[SETUP COMPLETED] The simulator is now ready to run with:", "green"))
    print(colorize("   python main.py", "green"))
    print(colorize("   or on the Slurm cluster using the dedicated scripts.", "green"))
    print(colorize("=" * 60, "cyan"))

if __name__ == "__main__":
    main()
