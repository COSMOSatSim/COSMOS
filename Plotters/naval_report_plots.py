"""
Generate the figures used in the naval LaTeX report.

Input data
----------
result/naval_full_run_2026-11-10/{IN_NETWORK,TO_OBSERVER}/optimal/*.csv

Output
------
relazione_latex/figures/fig_task_outcomes.pdf
relazione_latex/figures/fig_latency.pdf
relazione_latex/figures/fig_latency_breakdown.pdf

The script only depends on the Python standard library, numpy and matplotlib.
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "result" / "naval_full_run_2026-11-10"
FIG_DIR = ROOT / "relazione_latex" / "figures"

CSV_PATHS = {
    "IN_NETWORK": DATA_DIR / "IN_NETWORK" / "optimal" / "[GREEDY]_AT_0.5_CPU_0.05.csv",
    "TO_OBSERVER": DATA_DIR / "TO_OBSERVER" / "optimal" / "[GREEDY]_AT_0.5_CPU_0.05.csv",
}

COLORS = {
    "IN_NETWORK": "#2E5E8C",
    "TO_OBSERVER": "#D97706",
    "filtered": "#9CA3AF",
    "lost": "#C53030",
    "compute": "#2F855A",
    "communication": "#2E5E8C",
    "forward": "#D97706",
    "queue": "#9CA3AF",
    "return": "#7C3AED",
}

LABELS = {
    "IN_NETWORK": "IN_NETWORK (edge in orbita)",
    "TO_OBSERVER": "TO_OBSERVER (relay a terra)",
}

# Counts derived from the full-run logs (task attempts, not only routed tasks).
TASK_COUNTS = {
    "IN_NETWORK": {
        "generated": 582,
        "completed": 532,
        "in_flight": 3,
        "filtered": 47,
        "lost": 0,
    },
    "TO_OBSERVER": {
        "generated": 583,
        "completed": 567,
        "in_flight": 16,
        "filtered": 0,
        "lost": 0,
    },
}


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 9,
            "axes.labelsize": 9,
            "axes.titlesize": 9,
            "legend.fontsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def numeric(rows: list[dict[str, str]], key: str) -> list[float]:
    values = []
    for row in rows:
        raw = row.get(key, "")
        if raw not in ("", None):
            values.append(float(raw))
    return values


def ecdf(values: list[float]) -> tuple[np.ndarray, np.ndarray]:
    x = np.sort(np.asarray(values, dtype=float))
    y = np.arange(1, len(x) + 1) / len(x)
    return x, y


def plot_task_outcomes() -> None:
    categories = ["Completati", "In volo", "Filtrati", "Persi / TTL"]
    keys = ["completed", "in_flight", "filtered", "lost"]

    fig, ax = plt.subplots(figsize=(6.4, 2.5), constrained_layout=True)
    y = np.arange(len(categories))
    height = 0.34

    for offset, use_case in zip((-height / 2, height / 2), ("IN_NETWORK", "TO_OBSERVER")):
        values = [TASK_COUNTS[use_case][key] for key in keys]
        bars = ax.barh(
            y + offset,
            values,
            height=height,
            color=COLORS[use_case],
            label=LABELS[use_case],
            edgecolor="white",
            linewidth=0.6,
        )
        for bar, value in zip(bars, values):
            ax.annotate(
                f"{value}",
                xy=(bar.get_width(), bar.get_y() + bar.get_height() / 2),
                xytext=(3, 0),
                textcoords="offset points",
                va="center",
                ha="left",
                fontsize=7,
            )

    ax.set_yticks(y, categories)
    ax.invert_yaxis()
    ax.set_xlabel("Numero di task")
    ax.set_xlim(0, max(TASK_COUNTS["TO_OBSERVER"]["completed"], TASK_COUNTS["IN_NETWORK"]["completed"]) * 1.12)
    ax.legend(loc="lower right", frameon=False)
    ax.grid(axis="x", color="0.85", linewidth=0.6)
    ax.set_axisbelow(True)
    fig.savefig(FIG_DIR / "fig_task_outcomes.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_latency(in_durations: list[float], to_rtts: list[float]) -> None:
    fig, (ax_box, ax_cdf) = plt.subplots(
        1, 2, figsize=(7.0, 2.7), gridspec_kw={"width_ratios": [1.0, 1.25]}, constrained_layout=True
    )

    data = [in_durations, to_rtts]
    box = ax_box.boxplot(
        data,
        tick_labels=["IN_NETWORK", "TO_OBSERVER"],
        patch_artist=True,
        widths=0.45,
        medianprops={"color": "black", "linewidth": 1.0},
        whiskerprops={"color": "0.35"},
        capprops={"color": "0.35"},
        flierprops={"marker": "o", "markersize": 2.5, "markerfacecolor": "0.55", "markeredgecolor": "0.55"},
    )
    for patch, color in zip(box["boxes"], (COLORS["IN_NETWORK"], COLORS["TO_OBSERVER"])):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)
        patch.set_edgecolor("0.25")
    ax_box.set_ylabel("Latenza / RTT [s]")
    ax_box.grid(axis="y", color="0.85", linewidth=0.6)
    ax_box.set_axisbelow(True)

    for values, use_case, linestyle in (
        (in_durations, "IN_NETWORK", "-"),
        (to_rtts, "TO_OBSERVER", "-"),
    ):
        x, y = ecdf(values)
        ax_cdf.step(
            x,
            y,
            where="post",
            color=COLORS[use_case],
            linewidth=1.5,
            label=f"{LABELS[use_case]} (media {statistics.mean(values):.2f} s)",
        )

    ax_cdf.set_xlabel("Latenza / RTT [s]")
    ax_cdf.set_ylabel("Probabilità cumulata")
    ax_cdf.set_ylim(0, 1.02)
    ax_cdf.grid(color="0.85", linewidth=0.6)
    ax_cdf.set_axisbelow(True)
    ax_cdf.legend(loc="lower right", frameon=False)

    fig.savefig(FIG_DIR / "fig_latency.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_breakdown(
    in_total: float,
    in_compute: float,
    to_total: float,
    to_forward: float,
    to_queue: float,
    to_compute: float,
    to_return: float,
) -> None:
    fig, ax = plt.subplots(figsize=(6.4, 2.6), constrained_layout=True)

    rows = [
        ("TO_OBSERVER", [
            ("Transito andata", to_forward, COLORS["forward"]),
            ("Coda a terra", to_queue, COLORS["queue"]),
            ("Calcolo a terra", to_compute, COLORS["compute"]),
            ("Transito ritorno", to_return, COLORS["return"]),
        ]),
        ("IN_NETWORK", [
            ("Comunicazione / routing", in_total - in_compute, COLORS["communication"]),
            ("Calcolo edge", in_compute, COLORS["compute"]),
        ]),
    ]

    for y, (use_case, segments) in enumerate(rows):
        left = 0.0
        for name, value, color in segments:
            if value <= 0:
                continue
            ax.barh(y, value, left=left, height=0.42, color=color, edgecolor="white", linewidth=0.8)
            if value >= 0.45:
                ax.text(
                    left + value / 2,
                    y,
                    f"{value:.2f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="white",
                    fontweight="bold",
                )
            else:
                ax.text(
                    left + value / 2,
                    y + 0.27,
                    f"{value:.2f}",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    color=color,
                    fontweight="bold",
                )
            left += value
        ax.text(left + 0.06, y, f"tot. {left:.2f} s", va="center", ha="left", fontsize=8)

    ax.set_yticks([0, 1], ["TO_OBSERVER", "IN_NETWORK"])
    ax.set_xlabel("Latenza media [s]")
    ax.set_xlim(0, max(to_total, in_total) * 1.22)
    ax.set_ylim(-0.55, 1.55)
    ax.grid(axis="x", color="0.85", linewidth=0.6)
    ax.set_axisbelow(True)

    from matplotlib.patches import Patch

    legend_items = [
        Patch(facecolor=COLORS["communication"], label="Comunicazione / routing"),
        Patch(facecolor=COLORS["compute"], label="Calcolo"),
        Patch(facecolor=COLORS["forward"], label="Transito andata"),
        Patch(facecolor=COLORS["queue"], label="Coda a terra"),
        Patch(facecolor=COLORS["return"], label="Transito ritorno"),
    ]
    ax.legend(
        handles=legend_items,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.28),
        frameon=False,
        ncol=3,
    )

    fig.savefig(FIG_DIR / "fig_latency_breakdown.pdf", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    configure_style()
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    in_rows = load_rows(CSV_PATHS["IN_NETWORK"])
    to_rows = load_rows(CSV_PATHS["TO_OBSERVER"])

    in_completed = [row for row in in_rows if row["Label"] == "TASK_ARRIVED"]
    to_completed = [row for row in to_rows if row["Label"] == "ROUND_TRIP_COMPLETED"]

    in_durations = numeric(in_completed, "Duration")
    in_compute = numeric(in_completed, "ComputeTime")
    to_rtts = numeric(to_completed, "RTT")
    to_return = numeric(to_completed, "ReturnDuration")
    to_compute = numeric(to_completed, "ComputeTime")
    to_queue = numeric(to_completed, "GroundQueueDelay")

    in_mean = statistics.mean(in_durations)
    in_compute_mean = statistics.mean(in_compute)
    to_mean = statistics.mean(to_rtts)
    to_forward_mean = statistics.mean(
        [
            rtt - ret - cmp - (queue if queue else 0.0)
            for rtt, ret, cmp, queue in zip(to_rtts, to_return, to_compute, to_queue)
        ]
    )

    plot_task_outcomes()
    plot_latency(in_durations, to_rtts)
    plot_breakdown(
        in_total=in_mean,
        in_compute=in_compute_mean,
        to_total=to_mean,
        to_forward=to_forward_mean,
        to_queue=statistics.mean(to_queue),
        to_compute=statistics.mean(to_compute),
        to_return=statistics.mean(to_return),
    )

    print("Figure generate in:", FIG_DIR)
    print(f"IN_NETWORK: n={len(in_durations)} media={in_mean:.3f}s compute={in_compute_mean:.3f}s")
    print(f"TO_OBSERVER: n={len(to_rtts)} media={to_mean:.3f}s andata={to_forward_mean:.3f}s "
          f"compute={statistics.mean(to_compute):.3f}s ritorno={statistics.mean(to_return):.3f}s")


if __name__ == "__main__":
    main()
