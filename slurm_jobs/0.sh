#!/bin/bash
#SBATCH --job-name=example_job
#SBATCH --partition=department_only
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.err

uv run example.py