#!/bin/bash

# ==============================================================================
# SCRIPT REGISTA: Manda in esecuzione tutti i task su Slurm aggirando il limite
# di 1000 task per singolo Array Job. Suddivide i job in blocchi (chunk) 
# e li esegue sequenzialmente.
# ==============================================================================

# File di input (generato da configsGenerator.py) che contiene la lista dei JSON da simulare
SIMS_LIST_FILE="sims_sets_list.txt"

# 1. Conta quante righe ci sono nel file (ovvero quanti job totali dobbiamo lanciare)
NUM_JOBS=$(cat "$SIMS_LIST_FILE" | wc -l)
# Rimuove eventuali spazi bianchi dalla variabile numerica
NUM_JOBS=$(echo "$NUM_JOBS" | tr -d ' ')

# Controllo di sicurezza: se il file è vuoto, fermati subito per evitare errori di Slurm
if [ "$NUM_JOBS" -eq 0 ]; then
    echo "Errore: Il file di input $SIMS_LIST_FILE è vuoto."
    exit 1
fi

echo "Trovati $NUM_JOBS task totali. Inizio accodamento sequenziale con Offset."

# I cluster Slurm spesso hanno un limite massimo (es. 1000) per le dimensioni di un Array.
MAX_ARRAY_SIZE=1000
PREV_JOB_ID=""
CURRENT_OFFSET=0

# 2. Ciclo finché non abbiamo sottomesso a Slurm tutti i job necessari
while [ $CURRENT_OFFSET -lt $NUM_JOBS ]; do
    
    # Calcola quanti job rimangono da inviare in totale
    REMAINING=$((NUM_JOBS - CURRENT_OFFSET))
    
    # Se ce ne sono ancora più del limite (1000), manda un blocco pieno da 1000.
    # Altrimenti, manda un blocco con solo i task rimanenti per finire.
    if [ $REMAINING -gt $MAX_ARRAY_SIZE ]; then
        CHUNK_SIZE=$MAX_ARRAY_SIZE
    else
        CHUNK_SIZE=$REMAINING
    fi

    # Il range di Slurm per questo blocco sarà es: "1-1000" oppure "1-450"
    ARRAY_RANGE="1-$CHUNK_SIZE"
    
    echo "Sottomissione blocco con OFFSET: $CURRENT_OFFSET (Range Slurm: $ARRAY_RANGE)"
    
    # Esportiamo la variabile CHUNK_OFFSET affinché lo script 'run_array.sh' sappia
    # da quale riga del file di testo deve iniziare a leggere per questo blocco specifico
    export CHUNK_OFFSET=$CURRENT_OFFSET
    
    if [ -z "$PREV_JOB_ID" ]; then
        # PRIMO BLOCCO: Lo lanciamo normalmente senza aspettare nessuno.
        # --parsable: dice a Slurm di stampare a schermo SOLO l'ID del job in formato numerico
        # %50: significa "Esegui massimo 50 task in parallelo contemporaneamente per non intasare il cluster"
        PREV_JOB_ID=$(sbatch --parsable --array="$ARRAY_RANGE%50" slurm_jobs/run_array.sh)
    else
        # BLOCCHI SUCCESSIVI: Li accodiamo mettendo una dipendenza.
        # --dependency=afterany:$PREV_JOB_ID: dice a Slurm di NON far partire questo array 
        # finché l'array del blocco precedente non è terminato (con successo o errore).
        echo "  -> In attesa che il blocco precedente $PREV_JOB_ID finisca..."
        PREV_JOB_ID=$(sbatch --parsable --dependency=afterany:$PREV_JOB_ID --array="$ARRAY_RANGE%50" slurm_jobs/run_array.sh)
    fi
    
    echo "  -> Job ID assegnato da Slurm per questo blocco: $PREV_JOB_ID"
    
    # Avanza l'offset di N posizioni per calcolare il punto di partenza del prossimo ciclo
    CURRENT_OFFSET=$((CURRENT_OFFSET + CHUNK_SIZE))
done

echo "Tutti i blocchi sono stati accodati in Slurm con successo!"
