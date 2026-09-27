#!/bin/bash

# ==============================================================================
# SCRIPT WORKER (Slurm Array): Questo script viene eseguito da ogni singolo nodo 
# del cluster per un task specifico. 
# NB: Manca la direttiva --array perché gliela passa 'submit_array.sh' in automatico!
# ==============================================================================
#SBATCH --job-name=Sims_Array
#SBATCH --partition=department_only

# Log output ed errori (viene creata una riga per ogni task dell'array)
# %A = ID del Job Master, %a = ID del task specifico dentro l'array (es. 1, 2, 3...)
#SBATCH --output=SBATCH_LOGS/OUT_%A_%a.out
#SBATCH --error=SBATCH_LOGS/ERR_%A_%a.err

# ==============================================================================
# 1. PREPARAZIONE E ATTIVAZIONE AMBIENTE
# ==============================================================================

# Definisce il percorso dell'ambiente virtuale rispetto a dove è stato lanciato il job
VENV_DIR="$SLURM_SUBMIT_DIR/.venv"

# 1.1. Crea la cartella dei log (Garantisce che esista quando il task tenta di scriverci)
mkdir -p SBATCH_LOGS

# 1.2. Verifica e Attiva l'ambiente virtuale Python
if [ -d "$VENV_DIR" ]; then
    echo "Trovato ambiente virtuale in $VENV_DIR."
    
    # Attiva l'ambiente virtuale. Questo aggiunge i binari di .venv 
    # (incluso 'uv' e 'python') al PATH del nodo che sta eseguendo il job.
    source "$VENV_DIR/bin/activate"
    echo "Ambiente virtuale attivato con successo."
    
else
    echo "ERRORE CRITICO: Ambiente virtuale non trovato in $VENV_DIR." >&2
    echo "Impossibile continuare. Assicurati che il percorso sia corretto e accessibile dal nodo." >&2
    exit 1
fi

# ==============================================================================
# 2. LOGICA DI ESECUZIONE (SLURM ARRAY + OFFSET)
# ==============================================================================

# Legge la variabile CHUNK_OFFSET passata da 'submit_array.sh'. Se non esiste, usa 0.
OFFSET=${CHUNK_OFFSET:-0}

# SLURM_ARRAY_TASK_ID è un numero da 1 a X assegnato automaticamente da Slurm.
# Sommandolo all'OFFSET scopriamo qual è la VERA riga da leggere nei file di testo.
REAL_TASK_ID=$((SLURM_ARRAY_TASK_ID + OFFSET))

SIMS_LIST_FILE="sims_sets_list.txt"
IMG_RES_LIST_FILE="img_resolutions_list.txt"

# 2.1. Estrae usando 'sed' solo la riga numero $REAL_TASK_ID dai file di testo
SET_FILE=$(sed -n "${REAL_TASK_ID}p" "$SIMS_LIST_FILE")
IMG_FILE=$(sed -n "${REAL_TASK_ID}p" "$IMG_RES_LIST_FILE")

echo "--- Esecuzione Task Slurm: ID array $SLURM_ARRAY_TASK_ID | Riga file testo (con offset): $REAL_TASK_ID ---"
echo "  Configurazione Simulazione: $SET_FILE"
echo "  Configurazione Immagini: $IMG_FILE"

# ==============================================================================
# 3. AVVIO DELLA SIMULAZIONE
# ==============================================================================

# Lancia il simulatore passando i due file json prelevati
# NB: Usa 'uv run' invece di 'python' (presumibilmente perché usi il gestore di pacchetti uv)
uv run main.py "$SET_FILE" "$IMG_FILE"
