"""
Naval Configuration Sequence Plotter and Animator.

This standalone script visualizes the temporal evolution of satellite network
configurations generated for the naval use-case (e.g. from
'data/naval_configurations_AP_base.json' or 'data/naval_configurations_AP_optimal.json').

Key Features:
- Highlights satellites with an active 'life' attribute in glowing GREEN.
- Differentiates corridor transit satellites and Access Points.
- Displays the Earth wireframe, Observer (e.g. Rome), Vessel (Ship),
  the great circle surface route, the 40° elevation dome footprint,
  and inter-satellite ISL links.
- Produces animated GIFs, MP4 videos, or interactive matplotlib windows.
- Can rotate the camera around the Earth for cinematic 3D orbital animation.

Usage:
    python Plotters/naval_config_plotter.py --help
    python Plotters/naval_config_plotter.py --config-file data/naval_configurations_AP_base.json --output data/naval_base.gif
"""

import argparse
import json
import os
import sys
from datetime import datetime
import numpy as np

import matplotlib
# Use non-interactive backend by default if no DISPLAY
if "DISPLAY" not in os.environ:
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter, FFMpegWriter
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from skyfield.api import EarthSatellite, load, wgs84


EARTH_RADIUS_KM = 6371.0


def load_phi_settings(config_path="config/config.json5") -> tuple[float, float]:
    """Carica Phi_max e Phi_buffer dal file di configurazione con fallback sicuri."""
    phi_max = 40.0
    phi_buffer = 15.0
    if os.path.exists(config_path):
        try:
            import json5
            with open(config_path, "r") as f:
                cfg = json5.load(f)
            phi_max = float(cfg.get("Phi_max", 40.0))
            phi_buffer = float(cfg.get("Phi_buffer", 15.0))
        except Exception:
            pass
    return phi_max, phi_buffer


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Visualizzatore e Animatore delle Configurazioni Navali SECMotionModel"
    )
    parser.add_argument(
        "--config-file",
        type=str,
        default="data/naval_configurations_AP_base.json",
        help="Percorso del file JSON con le configurazioni (default: data/naval_configurations_AP_base.json)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="NavalOrbit/animations/naval_configurations_animation.gif",
        help="Percorso del file di output (GIF o MP4, default: NavalOrbit/animations/naval_configurations_animation.gif)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=2,
        help="Frame per secondo dell'animazione (default: 2)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=120,
        help="Risoluzione DPI dell'animazione (default: 120)",
    )
    parser.add_argument(
        "--view-mode",
        type=str,
        default="vessel_perp",
        choices=["vessel_perp", "topdown", "zenith", "polar", "custom"],
        help="Modalità prospettica: 'vessel_perp' (zoom perpendicolare sopra la nave, default), 'topdown' (dall'alto centrato sul corridoio), 'zenith' (radiale perpendicolare corridoio), 'polar' (dall'alto polare), 'custom' (manuale)",
    )
    parser.add_argument(
        "--center-on",
        type=str,
        default="vessel",
        choices=["vessel", "corridor", "all", "globe"],
        help="Punto di centratura del box 3D: 'vessel' (Nave, default), 'corridor' (linea Observer-Nave), 'all' (tutti i satelliti), 'globe' (globo intero)",
    )
    parser.add_argument(
        "--span",
        type=float,
        default=1250.0,
        help="Semi-ampiezza della visuale in km per lo zoom sulla nave (default: 1250 km, include cupola e buffer zone)",
    )
    parser.add_argument(
        "--elev",
        type=float,
        default=None,
        help="Angolo di elevazione della telecamera 3D in gradi (se non specificato, calcolato automaticamente per la vista dall'alto)",
    )
    parser.add_argument(
        "--azim",
        type=float,
        default=None,
        help="Angolo azimutale iniziale della telecamera 3D in gradi (se non specificato, allineato automaticamente al bersaglio)",
    )
    parser.add_argument(
        "--elev-offset",
        type=float,
        default=25.0,
        help="Inclinazione aggiuntiva dall'alto in modalità topdown in gradi (default: 25.0)",
    )
    parser.add_argument(
        "--no-labels",
        action="store_true",
        help="Disabilita le etichette con nome ed elevazione sui satelliti verdi",
    )
    parser.add_argument(
        "--rotate",
        type=float,
        default=0.0,
        help="Rotazione della telecamera per frame in gradi (default: 0.0 per vista stabile dall'alto; >0 per rotazione cinematografica)",
    )
    parser.add_argument(
        "--no-isls",
        action="store_true",
        help="Disabilita il disegno dei collegamenti ISL tra satelliti vicini",
    )
    parser.add_argument(
        "--full-globe",
        action="store_true",
        help="Mostra l'intero globo terrestre anziché zoomare sul corridoio navale",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Numero massimo di frame/configurazioni da animare (opzionale)",
    )
    parser.add_argument(
        "--frame",
        type=int,
        default=None,
        help="Se specificato, esporta solo un singolo frame come PNG statico",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Apre una finestra interattiva a schermo (richiede ambiente grafico)",
    )
    return parser.parse_args()


def load_configurations(file_path: str) -> dict:
    if not os.path.exists(file_path):
        sys.exit(f"[ERRORE] Il file configurazioni '{file_path}' non esiste.")
    with open(file_path, "r") as f:
        data = json.load(f)
    return data


def get_observer_coordinates(obs_name: str) -> tuple[float, float]:
    """Restituisce le coordinate di default per l'Observer noto (es. Roma)."""
    if "roma" in obs_name.lower():
        return 41.9028, 12.4964
    return 41.9028, 12.4964


def draw_earth_wireframe(ax, R=EARTH_RADIUS_KM):
    """Disegna la griglia sferica della Terra con paralleli e meridiani principali."""
    u = np.linspace(0, 2 * np.pi, 36)
    v = np.linspace(0, np.pi, 18)
    x = R * np.outer(np.cos(u), np.sin(v))
    y = R * np.outer(np.sin(u), np.sin(v))
    z = R * np.outer(np.ones(np.size(u)), np.cos(v))
    ax.plot_wireframe(x, y, z, color="#1E293B", alpha=0.35, linewidth=0.6)

    # Evidenzia Equatore e Primo Meridiano
    theta = np.linspace(0, 2 * np.pi, 100)
    ax.plot(R * np.cos(theta), R * np.sin(theta), np.zeros_like(theta),
            color="#334155", linewidth=1.0, linestyle=":", alpha=0.6)


def draw_ground_circle(ax, center_vec, angular_radius_deg, R, color, label, linestyle="-", lw=1.8, alpha=0.85):
    """Disegna un cerchio geodetico sulla sfera terrestre (es. cupola 40° di elevazione)."""
    if angular_radius_deg <= 0:
        return
    rad = np.radians(angular_radius_deg)
    center_norm = center_vec / np.linalg.norm(center_vec)

    ref_vec = np.array([1.0, 0.0, 0.0]) if abs(center_norm[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    local_x = np.cross(center_norm, ref_vec)
    local_x /= np.linalg.norm(local_x)
    local_y = np.cross(center_norm, local_x)

    angles = np.linspace(0, 2 * np.pi, 90)
    pts = []
    for a in angles:
        pt = (np.sin(rad) * np.cos(a) * local_x +
              np.sin(rad) * np.sin(a) * local_y +
              np.cos(rad) * center_norm) * R
        pts.append(pt)
    pts = np.array(pts)
    ax.plot(pts[:, 0], pts[:, 1], pts[:, 2], color=color,
            linestyle=linestyle, linewidth=lw, label=label, alpha=alpha)


def draw_local_range_rings(ax, center_vec, R=EARTH_RADIUS_KM):
    """Disegna cerchi di distanza concentrici (300, 600, 900 km) attorno al centro per riferimento locale."""
    center_norm = center_vec / np.linalg.norm(center_vec)
    ref_vec = np.array([1.0, 0.0, 0.0]) if abs(center_norm[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    local_x = np.cross(center_norm, ref_vec)
    local_x /= np.linalg.norm(local_x)
    local_y = np.cross(center_norm, local_x)

    angles = np.linspace(0, 2 * np.pi, 60)
    for km_dist in [300.0, 600.0, 900.0]:
        ang_rad = km_dist / R
        pts = [
            (np.sin(ang_rad) * np.cos(a) * local_x +
             np.sin(ang_rad) * np.sin(a) * local_y +
             np.cos(ang_rad) * center_norm) * R
            for a in angles
        ]
        pts = np.array(pts)
        ax.plot(pts[:, 0], pts[:, 1], pts[:, 2], color="#334155",
                linestyle=":", linewidth=0.8, alpha=0.5)


def draw_great_circle_route(ax, vA, vB, R=EARTH_RADIUS_KM, color="#FBBF24", label="Rotta Nave-Observer"):
    """Disegna l'arco di cerchio massimo sulla superficie terrestre tra Observer e Nave."""
    t_vals = np.linspace(0, 1, 60)
    arc_points = []
    for val in t_vals:
        p = (1 - val) * vA + val * vB
        norm = np.linalg.norm(p)
        if norm > 0:
            arc_points.append((p / norm) * R)
    if arc_points:
        pts = np.array(arc_points)
        ax.plot(pts[:, 0], pts[:, 1], pts[:, 2], color=color,
                linestyle="--", linewidth=1.8, alpha=0.85, label=label)


def set_axes_equal_3d(ax, points_list):
    """Centra e scala uniformemente il box 3D attorno ai punti rilevanti."""
    pts = np.vstack(points_list)
    x_min, x_max = np.min(pts[:, 0]), np.max(pts[:, 0])
    y_min, y_max = np.min(pts[:, 1]), np.max(pts[:, 1])
    z_min, z_max = np.min(pts[:, 2]), np.max(pts[:, 2])

    max_range = max(x_max - x_min, y_max - y_min, z_max - z_min) * 0.65
    x_mid = (x_max + x_min) / 2.0
    y_mid = (y_max + y_min) / 2.0
    z_mid = (z_max + z_min) / 2.0

    ax.set_xlim3d(x_mid - max_range, x_mid + max_range)
    ax.set_ylim3d(y_mid - max_range, y_mid + max_range)
    ax.set_zlim3d(z_mid - max_range, z_mid + max_range)


class NavalConfigAnimator:
    """Gestisce la renderizzazione dei singoli frame e la creazione dell'animazione."""

    def __init__(self, data: dict, args):
        self.data = data
        self.args = args
        self.ts = load.timescale()
        self.configs = data.get("configurations", [])
        if args.max_frames is not None:
            self.configs = self.configs[:args.max_frames]

        self.obs_name = data.get("observer_position", "Roma")
        self.obs_lat, self.obs_lon = get_observer_coordinates(self.obs_name)
        self.obs_pos = wgs84.latlon(self.obs_lat, self.obs_lon)

        self.vessel_name = data.get("vessel_name", "Vessel")

        # Parametri angolari Cupola e Buffer Zone da config
        self.phi_max, self.phi_buffer = load_phi_settings()
        self.bzed = self.phi_max - self.phi_buffer  # Angolo di Buffer Zone (es. 40 - 15 = 25°)

        # Cache degli oggetti EarthSatellite per velocizzare i calcoli
        self.sat_cache = {}
        self._init_sat_cache()

    def _init_sat_cache(self):
        """Pre-inizializza la cache degli oggetti EarthSatellite dai dati TLE."""
        for step in self.configs:
            for s in step.get("configuration", []):
                name = s.get("satellite")
                if name not in self.sat_cache:
                    tle_list = s.get("TLE-DATA", [])
                    if tle_list:
                        tle = tle_list[0]
                        self.sat_cache[name] = EarthSatellite(
                            tle["line1"], tle["line2"], tle["name"], self.ts
                        )

    def compute_frame_positions(self, step: dict):
        """Calcola posizioni 3D cartesiane per tutti i satelliti, la nave e l'observer al tempo t."""
        time_str = step["time"]
        dt = datetime.fromisoformat(time_str)
        t_sky = self.ts.from_datetime(dt)

        # Coordinate Observer e Vessel
        v_obs = self.obs_pos.at(t_sky).position.km
        vessel_info = step.get("vessel_position", {})
        v_lat = vessel_info.get("lat", self.obs_lat)
        v_lon = vessel_info.get("lon", self.obs_lon)
        vessel_pos = wgs84.latlon(v_lat, v_lon)
        v_vessel = vessel_pos.at(t_sky).position.km

        # Calcolo posizioni satelliti
        sat_positions = {}
        for s in step.get("configuration", []):
            name = s.get("satellite")
            sat_obj = self.sat_cache.get(name)
            if sat_obj is not None:
                pos = sat_obj.at(t_sky).position.km
                sat_positions[name] = pos

        return t_sky, dt, v_obs, v_vessel, sat_positions, v_lat, v_lon

    def render_frame(self, ax, frame_idx: int):
        """Renderizza un singolo frame sul grafico 3D."""
        ax.cla()
        step = self.configs[frame_idx]
        t_sky, dt, v_obs, v_vessel, sat_pos_dict, v_lat, v_lon = self.compute_frame_positions(step)

        # Configurazione sfondo scuro elegante
        ax.set_facecolor("#0B0F19")
        ax.grid(False)
        for pane in [ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane]:
            pane.fill = False
            pane.set_edgecolor("#1E293B")

        # 1. Disegna Terra
        draw_earth_wireframe(ax, R=EARTH_RADIUS_KM)

        # 2. Rotta di navigazione tra Nave e Observer
        draw_great_circle_route(ax, v_obs, v_vessel, R=EARTH_RADIUS_KM)

        # 3. Footprint della Cupola (40°) e della Buffer Zone (25°) sopra la Nave
        draw_ground_circle(ax, v_vessel, angular_radius_deg=5.2, R=EARTH_RADIUS_KM,
                           color="#00E676", label=f"Cupola (>{int(self.phi_max)}° Elev)", lw=2.0)
        draw_ground_circle(ax, v_vessel, angular_radius_deg=8.5, R=EARTH_RADIUS_KM,
                           color="#FF9F1C", label=f"Buffer Zone (>{int(self.bzed)}° Elev)", linestyle="--", lw=1.6, alpha=0.85)

        # 4. Observer e Vessel Marker
        ax.scatter(*v_obs, color="#38BDF8", s=130, marker="o", edgecolors="white",
                   linewidths=1.2, depthshade=False, zorder=8, label=f"Observer ({self.obs_name})")
        ax.scatter(*v_vessel, color="#EF4444", s=150, marker="X", edgecolors="white",
                   linewidths=1.2, depthshade=False, zorder=8, label=f"Vessel ({self.vessel_name})")

        # 5. Classificazione satelliti: LIFE (VERDE), BUFFER ZONE (ARANCIO), AP, TRANSITO CORRIDOIO
        life_positions = []
        life_names = []
        buffer_positions = []
        buffer_names = []
        ap_positions = []
        ap_names = []
        corridor_positions = []

        all_points = [v_obs, v_vessel]

        for s in step.get("configuration", []):
            name = s.get("satellite")
            pos = sat_pos_dict.get(name)
            if pos is None:
                continue

            all_points.append(pos)
            elev_deg = s.get("elev_angle", 0.0)
            has_life = (
                s.get("life") is not None
                and s["life"].get("time_until_set_seconds") is not None
            )
            is_ap = s.get("is_access_point", False)

            if has_life or elev_deg > self.phi_max:
                # 1. Cupola Principale (Verde brillante)
                life_positions.append(pos)
                life_names.append(name)
                ground_pt = (pos / np.linalg.norm(pos)) * EARTH_RADIUS_KM
                ax.plot([ground_pt[0], pos[0]], [ground_pt[1], pos[1]], [ground_pt[2], pos[2]],
                        color="#00E676", linestyle=":", linewidth=1.2, alpha=0.7)
            elif elev_deg > self.bzed:
                # 2. Buffer Zone (Phi_max - Phi_buffer = 25° -> Arancione/Ambra brillante)
                buffer_positions.append(pos)
                buffer_names.append(name)
                ground_pt = (pos / np.linalg.norm(pos)) * EARTH_RADIUS_KM
                ax.plot([ground_pt[0], pos[0]], [ground_pt[1], pos[1]], [ground_pt[2], pos[2]],
                        color="#FF9F1C", linestyle=":", linewidth=1.0, alpha=0.55)
            elif is_ap:
                # 3. Access Point esterno
                ap_positions.append(pos)
                ap_names.append(name)
            else:
                # 4. Satelliti ordinari del corridoio
                corridor_positions.append(pos)

        # 6. Scatter dei satelliti con colorazione esplicita
        # A) Satelliti ordinari del corridoio (azzurro/grigio)
        if corridor_positions:
            c_pts = np.array(corridor_positions)
            ax.scatter(c_pts[:, 0], c_pts[:, 1], c_pts[:, 2],
                       color="#64748B", s=22, marker="^", alpha=0.45,
                       depthshade=False, zorder=4, label=f"Corridoio ({len(corridor_positions)})")

        # B) Access Point fuori dalla cupola/buffer (giallo/oro)
        if ap_positions:
            ap_pts = np.array(ap_positions)
            ax.scatter(ap_pts[:, 0], ap_pts[:, 1], ap_pts[:, 2],
                       color="#FBBF24", s=75, marker="*", edgecolors="#D97706",
                       depthshade=False, zorder=7, label=f"Access Points ({len(ap_positions)})")

        # C) Satelliti BUFFER ZONE (elev > 25° e <= 40°) -> ARANCIONE BRILLANTE!
        if buffer_positions:
            b_pts = np.array(buffer_positions)
            ax.scatter(b_pts[:, 0], b_pts[:, 1], b_pts[:, 2],
                       color="#FF9F1C", s=65, marker="o", edgecolors="#FFFFFF",
                       linewidths=1.2, depthshade=False, zorder=8,
                       label=f"Buffer Zone >{int(self.bzed)}° (ARANCIO: {len(buffer_positions)})")

        # D) Satelliti CUPOLA PRINCIPALE (elev > 40° con LIFE) -> VERDE BRILLANTE!
        if life_positions:
            l_pts = np.array(life_positions)
            ax.scatter(l_pts[:, 0], l_pts[:, 1], l_pts[:, 2],
                       color="#00E676", s=85, marker="o", edgecolors="#FFFFFF",
                       linewidths=1.5, depthshade=False, zorder=10,
                       label=f"Cupola/Life >{int(self.phi_max)}° (VERDI: {len(life_positions)})")

        # 7. Disegno dei collegamenti ISL tra nodi vicini
        if not self.args.no_isls:
            segments = []
            drawn_pairs = set()
            for s in step.get("configuration", []):
                name1 = s.get("satellite")
                p1 = sat_pos_dict.get(name1)
                if p1 is None:
                    continue
                for neigh in s.get("neighbors", []):
                    name2 = neigh.get("name")
                    p2 = sat_pos_dict.get(name2)
                    if p2 is not None:
                        pair = tuple(sorted([name1, name2]))
                        if pair not in drawn_pairs:
                            drawn_pairs.add(pair)
                            segments.append([p1, p2])
            if segments:
                line_coll = Line3DCollection(segments, colors="#475569", linewidths=0.6, alpha=0.25)
                ax.add_collection3d(line_coll)

        # 8. Regolazione visuale e prospettiva
        corridor_mid = (v_obs + v_vessel) / 2.0
        corridor_dist = np.linalg.norm(v_obs - v_vessel)
        u_mid = corridor_mid / np.linalg.norm(corridor_mid)
        lat_mid = float(np.degrees(np.arcsin(u_mid[2])))
        lon_mid = float(np.degrees(np.arctan2(u_mid[1], u_mid[0])))

        u_vessel = v_vessel / np.linalg.norm(v_vessel)
        lat_vessel = float(np.degrees(np.arcsin(u_vessel[2])))
        lon_vessel = float(np.degrees(np.arctan2(u_vessel[1], u_vessel[0])))

        # Calcolo angoli ottimali
        if self.args.elev is not None and self.args.azim is not None:
            base_elev = self.args.elev
            base_azim = self.args.azim
        elif self.args.view_mode == "vessel_perp":
            # Vista puramente perpendicolare/zenitale sopra la nave (Nadir)
            base_elev = lat_vessel
            base_azim = lon_vessel
        elif self.args.view_mode == "zenith":
            base_elev = lat_mid
            base_azim = lon_mid
        elif self.args.view_mode == "polar":
            base_elev = 75.0
            base_azim = lon_mid
        elif self.args.view_mode == "topdown":
            base_elev = lat_mid + self.args.elev_offset
            base_azim = lon_mid
        else:
            base_elev = self.args.elev if self.args.elev is not None else lat_vessel
            base_azim = self.args.azim if self.args.azim is not None else lon_vessel

        # Calcolo box 3D e centratura
        center_mode = "globe" if self.args.full_globe else self.args.center_on
        if center_mode == "globe":
            lim = 8500.0
            ax.set_xlim3d(-lim, lim)
            ax.set_ylim3d(-lim, lim)
            ax.set_zlim3d(-lim, lim)
        elif center_mode == "vessel":
            # Zoom ad alta precisione perpendicolare sulla nave
            draw_local_range_rings(ax, v_vessel)
            span = self.args.span
            ax.set_xlim3d(v_vessel[0] - span, v_vessel[0] + span)
            ax.set_ylim3d(v_vessel[1] - span, v_vessel[1] + span)
            ax.set_zlim3d(v_vessel[2] - span, v_vessel[2] + span)
        elif center_mode == "corridor":
            half_span = max(corridor_dist * 0.58, 3500.0)
            ax.set_xlim3d(corridor_mid[0] - half_span, corridor_mid[0] + half_span)
            ax.set_ylim3d(corridor_mid[1] - half_span, corridor_mid[1] + half_span)
            ax.set_zlim3d(corridor_mid[2] - half_span, corridor_mid[2] + half_span)
        else:
            set_axes_equal_3d(ax, all_points)

        # 8.2 Etichette di testo sui satelliti della Cupola (Verdi) e Buffer (Arancioni)
        if not self.args.no_labels and (center_mode == "vessel" or len(life_positions) <= 20):
            for s in step.get("configuration", []):
                name = s.get("satellite")
                elev_deg = s.get("elev_angle", 0.0)
                has_life = (
                    s.get("life") is not None
                    and s["life"].get("time_until_set_seconds") is not None
                )
                if name in sat_pos_dict:
                    pos = sat_pos_dict[name]
                    short_name = name.replace("STARLINK-", "SL-").replace("[DTC]", "").strip()
                    if has_life or elev_deg > self.phi_max:
                        ax.text(pos[0], pos[1], pos[2] + 25, f"{short_name}\n({elev_deg:.0f}°)",
                                color="#00FF66", fontsize=7.2, weight="bold",
                                horizontalalignment="center", alpha=0.95, zorder=12)
                    elif elev_deg > self.bzed and center_mode == "vessel":
                        ax.text(pos[0], pos[1], pos[2] + 20, f"{short_name}\n({elev_deg:.0f}°)",
                                color="#FFB703", fontsize=6.8, weight="normal",
                                horizontalalignment="center", alpha=0.9, zorder=11)

        current_azim = base_azim + frame_idx * self.args.rotate
        ax.view_init(elev=base_elev, azim=current_azim)

        # Assi trasparenti e puliti
        ax.set_axis_off()

        # 9. Pannello HUD informativo in sovrimpressione
        total_dome_zone = len(life_positions) + len(buffer_positions)
        hud_text = (
            f"SECMOTIONMODEL NAVAL TOPOLOGY\n"
            f"─────────────────────────────────────\n"
            f"Step:         {frame_idx + 1:02d} / {len(self.configs):02d}\n"
            f"Orario UTC:   {dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Nave:         {self.vessel_name} (Lat {v_lat:+.2f}°, Lon {v_lon:+.2f}°)\n"
            f"Observer:     {self.obs_name} (Lat {self.obs_lat:+.2f}°, Lon {self.obs_lon:+.2f}°)\n"
            f"★ Cupola >{int(self.phi_max)}°:  {len(life_positions):2d} Satelliti (VERDE)\n"
            f"◆ Buffer >{int(self.bzed)}°:  {len(buffer_positions):2d} Satelliti (ARANCIO)\n"
            f"▶ Tot. Sopra: {total_dome_zone:2d} Satelliti (> {int(self.bzed)}°)\n"
            f"Corridoio:    {len(sat_pos_dict)} Satelliti totali"
        )
        ax.text2D(
            0.02, 0.96, hud_text, transform=ax.transAxes,
            fontsize=9.2, family="monospace", color="#F1F5F9",
            verticalalignment="top",
            bbox=dict(boxstyle="round,pad=0.6", facecolor="#0F172A", edgecolor="#334155", alpha=0.9)
        )

        # Legenda in basso a destra
        ax.legend(
            loc="lower right", facecolor="#0F172A", edgecolor="#334155",
            labelcolor="#E2E8F0", fontsize=8.5, framealpha=0.9
        )


def main():
    args = parse_arguments()
    print(f"\n[PLOTTER] Caricamento configurazioni da '{args.config_file}'...")
    data = load_configurations(args.config_file)
    configs = data.get("configurations", [])
    if not configs:
        sys.exit(f"[ERRORE] Nessuna configurazione trovata in '{args.config_file}'.")

    total_configs = len(configs)
    print(f"[PLOTTER] Trovate {total_configs} configurazioni temporali.")

    animator = NavalConfigAnimator(data, args)

    fig = plt.figure(figsize=(12, 10), facecolor="#0B0F19")
    ax = fig.add_subplot(111, projection="3d")

    # Caso 1: Esportazione di un singolo frame statico
    if args.frame is not None:
        frame_idx = max(0, min(args.frame, len(animator.configs) - 1))
        out_png = args.output if args.output.endswith(".png") else f"NavalOrbit/animations/naval_frame_{frame_idx}.png"
        print(f"[PLOTTER] Renderizzazione frame singolo {frame_idx} -> '{out_png}'...")
        animator.render_frame(ax, frame_idx)
        plt.tight_layout()
        os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
        plt.savefig(out_png, dpi=args.dpi, facecolor=fig.get_facecolor(), edgecolor="none")
        print(f"[PLOTTER] Frame salvato con successo in '{out_png}'.")
        return

    # Caso 2: Finestra interattiva a schermo
    if args.show:
        print("[PLOTTER] Apertura finestra interattiva...")
        anim = FuncAnimation(
            fig, animator.render_frame, frames=len(animator.configs),
            interval=1000 // args.fps, repeat=True
        )
        plt.show()
        return

    # Caso 3: Esportazione dell'animazione completa (GIF o MP4)
    out_path = args.output
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    num_frames = len(animator.configs)
    print(f"[PLOTTER] Creazione animazione ({num_frames} frame a {args.fps} FPS) -> '{out_path}'...")

    def update(frame):
        if (frame + 1) % max(1, num_frames // 5) == 0 or frame == num_frames - 1:
            print(f"  > Progresso: frame {frame + 1}/{num_frames} ({(frame + 1) / num_frames * 100:.0f}%)")
        animator.render_frame(ax, frame)

    anim = FuncAnimation(fig, update, frames=num_frames, interval=1000 // args.fps)

    if out_path.endswith(".mp4"):
        writer = FFMpegWriter(fps=args.fps, metadata=dict(artist="SECMotionModel"), bitrate=2000)
        anim.save(out_path, writer=writer, dpi=args.dpi)
    else:
        writer = PillowWriter(fps=args.fps)
        anim.save(out_path, writer=writer, dpi=args.dpi)

    print(f"[PLOTTER] Animazione completata e salvata con successo in: '{out_path}'\n")


if __name__ == "__main__":
    main()
