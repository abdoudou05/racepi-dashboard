from __future__ import annotations

import csv
import json
import queue
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox, ttk

import paho.mqtt.client as mqtt


# Configuration du broker MQTT local
BROKER_HOST = "localhost"
BROKER_PORT = 1884
TOPIC_SUBSCRIBE = "racepi/#"


@dataclass
class Runner:
    # Pour stocker les infos de chaque coureur
    name: str
    best_lap: float = 0.0
    current_lap: int = 0


@dataclass
class State:
    # État global du dashboard (on veut pas utiliser de variables globales)
    status: str = "EN ATTENTE"
    connected: bool = False
    active_runner: str = "-"
    elapsed: float = 0.0
    sector_time: float = 0.0
    best_lap: float = 0.0
    max_speed: float = 0.0
    max_accel: float = 0.0
    distance_total: float = 1.50
    active_sensor: str = "-"
    active_segment: str = "-"
    messages: int = 0
    runners: dict[str, Runner] = field(default_factory=dict)
    sector_rows: list[tuple[str, str, str, str, str, str]] = field(default_factory=list)


class Dashboard(tk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, bg="#1f1f1f")
        self.root = root
        self.state = State()
        self.inbox: queue.Queue[tuple[str, dict]] = queue.Queue() # File d'attente pour les messages

        # Setup du client MQTT
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        self.pack(fill="both", expand=True)
        self.create_ui()
        self.connect_mqtt()

        # On lance les boucles pour processer les messages et rafraîchir l'UI
        self.after(100, self.process_mqtt)
        self.after(250, self.refresh)

    def create_ui(self):
        # Construit l'interface graphique (labels, boutons, tableaux...)
        tk.Label(
            self,
            text="RacePi Dashboard",
            bg="#1f1f1f",
            fg="white",
            font=("Consolas", 24, "bold"),
        ).pack(pady=(12, 4))

        self.connection_label = tk.Label(
            self,
            text="MQTT: connexion...",
            bg="#1f1f1f",
            fg="orange",
            font=("Consolas", 11),
        )
        self.connection_label.pack()

        self.status_label = tk.Label(
            self,
            text="EN ATTENTE",
            bg="#153f32",
            fg="#24c78e",
            font=("Consolas", 18, "bold"),
            padx=20,
            pady=6,
        )
        self.status_label.pack(pady=10)

        self.time_label = tk.Label(
            self,
            text="00:00.00",
            bg="#1f1f1f",
            fg="#24c78e",
            font=("Consolas", 40, "bold"),
        )
        self.time_label.pack()

        self.info_label = tk.Label(
            self,
            text="Coureur: - | Capteur: - | Segment: -",
            bg="#1f1f1f",
            fg="white",
            font=("Consolas", 12),
        )
        self.info_label.pack(pady=6)

        # Section des boutons d'action
        buttons = tk.Frame(self, bg="#1f1f1f")
        buttons.pack(pady=8)

        tk.Button(
            buttons,
            text="START COURSE",
            width=18,
            bg="#24c78e",
            fg="black",
            font=("Consolas", 11, "bold"),
            command=self.cmd_start,
        ).grid(row=0, column=0, padx=6)

        tk.Button(
            buttons,
            text="STOP / RESET",
            width=18,
            bg="#b43737",
            fg="white",
            font=("Consolas", 11, "bold"),
            command=self.cmd_stop,
        ).grid(row=0, column=1, padx=6)

        tk.Button(
            buttons,
            text="CHARGER CSV",
            width=18,
            bg="#3488db",
            fg="white",
            font=("Consolas", 11, "bold"),
            command=self.load_csv,
        ).grid(row=0, column=2, padx=6)

        metrics = tk.Frame(self, bg="#1f1f1f")
        metrics.pack(fill="x", padx=18, pady=8)

        self.metric_time = self.make_metric(metrics, "TEMPS TOTAL", "0.00 s")
        self.metric_sector = self.make_metric(metrics, "TEMPS SEGMENT", "0.00 s")
        self.metric_speed = self.make_metric(metrics, "VITESSE MAX", "0.00 km/h")
        self.metric_accel = self.make_metric(metrics, "ACCÉL. MAX", "0.00 m/s²")
        self.metric_distance = self.make_metric(metrics, "DISTANCE TOTALE", "1.50 m")

        for i, metric in enumerate(
            [
                self.metric_time,
                self.metric_sector,
                self.metric_speed,
                self.metric_accel,
                self.metric_distance,
            ]
        ):
            metric.grid(row=0, column=i, sticky="ew", padx=4)
            metrics.columnconfigure(i, weight=1)

        self.sector_tree = ttk.Treeview(
            self,
            columns=("capteur", "segment", "distance", "temps", "vitesse", "accel"),
            show="headings",
            height=4,
        )

        for col, label, width in [
            ("capteur", "Capteur", 100),
            ("segment", "Segment mesuré", 180),
            ("distance", "Distance", 120),
            ("temps", "Temps segment", 150),
            ("vitesse", "Vitesse", 150),
            ("accel", "Accélération", 150),
        ]:
            self.sector_tree.heading(col, text=label)
            self.sector_tree.column(col, width=width, anchor="center")

        self.sector_tree.pack(fill="x", padx=18, pady=8)

        self.runner_tree = ttk.Treeview(
            self,
            columns=("pos", "name", "lap", "best"),
            show="headings",
            height=3,
        )

        for col, label, width in [
            ("pos", "Pos", 60),
            ("name", "Coureur", 220),
            ("lap", "Tour", 100),
            ("best", "Meilleur temps", 160),
        ]:
            self.runner_tree.heading(col, text=label)
            self.runner_tree.column(col, width=width, anchor="center")

        self.runner_tree.pack(fill="x", padx=18, pady=8)

        # Zone de texte en bas pour afficher les logs comme dans un terminal
        self.log_box = tk.Text(
            self,
            height=8,
            bg="#111111",
            fg="#00ff88",
            insertbackground="white",
            font=("Consolas", 9),
        )
        self.log_box.pack(fill="both", expand=True, padx=18, pady=(6, 14))

    def make_metric(self, parent, title: str, value: str):
        # Petit helper pour créer les boîtes de statistiques (temps, vitesse, etc.)
        frame = tk.Frame(parent, bg="#2a2a2a", height=70)
        frame.grid_propagate(False)

        tk.Label(
            frame,
            text=title,
            bg="#2a2a2a",
            fg="#8a8a8a",
            font=("Consolas", 8),
        ).pack(anchor="w", padx=10, pady=(8, 2))

        label = tk.Label(
            frame,
            text=value,
            bg="#2a2a2a",
            fg="white",
            font=("Consolas", 13, "bold"),
        )
        label.pack(anchor="w", padx=10)

        frame.value_label = label
        return frame

    def log(self, text: str):
        print(text)
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def connect_mqtt(self):
        # Tente de se connecter au broker
        try:
            self.client.connect(BROKER_HOST, BROKER_PORT, 60)
            self.client.loop_start()
            self.log(f"Connexion MQTT sur {BROKER_HOST}:{BROKER_PORT}")
        except Exception as exc:
            self.log(f"ERREUR MQTT: {exc}")

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        self.state.connected = True
        client.subscribe(TOPIC_SUBSCRIBE)
        self.log(f"MQTT connecté, écoute {TOPIC_SUBSCRIBE}")

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.state.connected = False
        self.log("MQTT déconnecté")

    def on_message(self, client, userdata, msg):
        # On décode le payload et on l'ajoute dans la file pour le traiter plus tard
        raw = msg.payload.decode("utf-8", errors="replace")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}

        self.log(f"REÇU {msg.topic} -> {payload}")
        self.inbox.put((msg.topic, payload))

    def publish(self, topic: str, payload: dict):
        result = self.client.publish(topic, json.dumps(payload, ensure_ascii=False))
        self.log(f"ENVOYÉ {topic} -> {payload} | rc={result.rc}")

    def cmd_start(self):
        self.publish("racepi/control/start", {})

    def cmd_stop(self):
        self.publish("racepi/control/stop", {})
        self.state.status = "ARRÊTÉ"
        self.state.elapsed = 0.0
        self.state.sector_time = 0.0
        self.state.best_lap = 0.0
        self.state.max_speed = 0.0
        self.state.max_accel = 0.0
        self.state.active_runner = "-"
        self.state.active_sensor = "-"
        self.state.active_segment = "-"
        self.state.runners.clear()
        self.state.sector_rows.clear()

    def get_runner(self, name: str) -> Runner:
        if name not in self.state.runners:
            self.state.runners[name] = Runner(name=name)
        return self.state.runners[name]

    def process_mqtt(self):
        # Dépile et traite tous les messages reçus depuis la dernière fois
        while not self.inbox.empty():
            topic, payload = self.inbox.get()
            self.state.messages += 1
            self.handle_message(topic, payload)

        self.after(100, self.process_mqtt)

    def handle_message(self, topic: str, payload: dict):
        # Gère la logique de la course selon le topic reçu
        if topic == "racepi/status":
            if payload.get("status") == "attente":
                self.state.status = "EN ATTENTE"
            return

        if topic == "racepi/race/start":
            self.state.status = "PRÊT"
            self.state.elapsed = 0.0
            self.state.sector_time = 0.0
            self.state.best_lap = 0.0
            self.state.max_speed = 0.0
            self.state.max_accel = 0.0
            self.state.active_sensor = "-"
            self.state.active_segment = "-"
            self.state.sector_rows.clear()

            coureur = str(payload.get("coureur", "INCONNU"))
            self.state.active_runner = coureur
            self.get_runner(coureur)

        elif topic == "racepi/race/sectors":
            coureur = str(payload.get("coureur", "INCONNU"))
            sensor = self.safe_int(payload.get("secteur", 0), 0)
            capteur = str(payload.get("capteur", f"IR{sensor}"))
            segment = str(payload.get("segment", self.segment_from_capteur(capteur)))
            total_time = self.safe_float(payload.get("temps", 0.0))
            sector_time = self.safe_float(payload.get("temps_secteur", 0.0))
            distance = self.safe_float(payload.get("distance_m", 0.0))
            speed = self.safe_float(payload.get("vitesse_kmh", 0.0))
            accel = self.safe_float(payload.get("acceleration_ms2", 0.0))

            runner = self.get_runner(coureur)
            runner.current_lap = self.safe_int(payload.get("tour", 1), 1)

            self.state.status = "COURSE"
            self.state.active_runner = coureur
            self.state.active_sensor = capteur
            self.state.active_segment = segment
            self.state.elapsed = total_time
            self.state.sector_time = sector_time
            self.state.max_speed = max(self.state.max_speed, speed)
            self.state.max_accel = max(self.state.max_accel, abs(accel))

            self.state.sector_rows.append(
                (
                    capteur,
                    segment,
                    f"{distance:.3f} m",
                    f"{sector_time:.3f} s",
                    f"{speed:.2f} km/h",
                    f"{accel:.2f} m/s²",
                )
            )

        elif topic == "racepi/race/laps":
            coureur = str(payload.get("coureur", "INCONNU"))
            lap_time = self.safe_float(payload.get("temps", 0.0))

            runner = self.get_runner(coureur)
            runner.current_lap = self.safe_int(payload.get("tour", 1), 1)
            runner.best_lap = lap_time
            self.state.best_lap = lap_time

        elif topic == "racepi/race/end":
            self.state.status = "TERMINÉ"
            self.state.active_runner = str(payload.get("coureur", self.state.active_runner))
            self.state.elapsed = self.safe_float(payload.get("temps_total", self.state.elapsed))
            self.state.best_lap = self.safe_float(payload.get("meilleur_tour", self.state.best_lap))
            self.state.max_speed = self.safe_float(payload.get("vitesse_max", self.state.max_speed))
            self.state.max_accel = self.safe_float(payload.get("acceleration_max", self.state.max_accel))
            self.state.distance_total = self.safe_float(payload.get("distance_totale_m", self.state.distance_total))

        elif topic in ("racepi/race/faux_depart", "racepi/race/false_start"):
            self.state.status = "FAUX DÉPART"

        elif topic == "racepi/race/stopped":
            self.state.status = "ARRÊTÉ"

    def load_csv(self):
        # Permet de charger un historique de course manuellement depuis un CSV
        path = filedialog.askopenfilename(
            title="Choisir un fichier CSV de course",
            filetypes=[
                ("Fichiers CSV", "*.csv"),
                ("Tous les fichiers", "*.*"),
            ],
        )

        if not path:
            return

        try:
            with open(path, newline="", encoding="utf-8-sig") as file:
                reader = csv.DictReader(file)
                rows = list(reader)
        except Exception as exc:
            messagebox.showerror("Erreur CSV", f"Impossible de lire le fichier:\n{exc}")
            return

        if not rows:
            messagebox.showwarning("CSV vide", "Le fichier CSV ne contient aucune donnée.")
            return

        self.state.status = "CSV CHARGÉ"
        self.state.messages += 1
        self.state.runners.clear()
        self.state.sector_rows.clear()

        max_speed = 0.0
        max_accel = 0.0
        total_time = 0.0
        last_sector_time = 0.0
        last_runner = "-"
        last_capteur = "-"
        last_segment = "-"
        distance_total = 0.0
        false_start_detected = False

        # On parcourt le fichier ligne par ligne pour simuler les données
        for row in rows:
            runner_name = row.get("coureur") or row.get("pilote") or row.get("runner") or "INCONNU"
            runner_name = str(runner_name)

            tour_raw = row.get("tour", "1")
            sector_raw = row.get("secteur", "-")
            sector_time_raw = row.get("temps_secteur_s") or row.get("temps_secteur") or "0"
            distance_raw = row.get("distance_m") or row.get("distance") or "0"
            speed_ms_raw = row.get("vitesse_ms") or "0"
            accel_raw = row.get("acceleration_ms2") or row.get("acceleration") or "0"
            false_start_raw = str(row.get("faux_depart", "NON")).strip().upper()

            false_start = false_start_raw in ("OUI", "TRUE", "1", "YES")
            false_start_detected = false_start_detected or false_start

            sector_time = self.safe_float(sector_time_raw)
            distance = self.safe_float(distance_raw)
            speed_ms = self.safe_float(speed_ms_raw)
            accel = self.safe_float(accel_raw)
            speed_kmh = speed_ms * 3.6

            capteur = self.normalize_capteur(str(sector_raw))
            segment = self.segment_from_capteur(capteur)

            tour = self.safe_int(str(tour_raw).replace("T", ""), 1)

            runner = self.get_runner(runner_name)
            runner.current_lap = max(runner.current_lap, tour)

            last_runner = runner_name
            last_sector_time = sector_time
            total_time += sector_time
            distance_total += distance
            max_speed = max(max_speed, speed_kmh)
            max_accel = max(max_accel, abs(accel))
            last_capteur = capteur
            last_segment = segment

            self.state.sector_rows.append(
                (
                    capteur,
                    segment,
                    f"{distance:.3f} m",
                    f"{sector_time:.3f} s",
                    f"{speed_kmh:.2f} km/h",
                    f"{accel:.2f} m/s²",
                )
            )

        self.state.active_runner = last_runner
        self.state.elapsed = total_time
        self.state.sector_time = last_sector_time
        self.state.best_lap = total_time
        self.state.max_speed = max_speed
        self.state.max_accel = max_accel
        self.state.distance_total = distance_total if distance_total > 0 else 1.50
        self.state.active_sensor = last_capteur
        self.state.active_segment = last_segment

        runner = self.get_runner(self.state.active_runner)
        runner.best_lap = total_time

        if false_start_detected:
            self.state.status = "CSV CHARGÉ - FAUX DÉPART"

        self.log(f"CSV chargé: {path}")
        messagebox.showinfo("CSV chargé", f"{len(rows)} lignes chargées.")

    def normalize_capteur(self, value: str) -> str:
        clean = value.strip().upper()

        if clean.startswith("IR"):
            return clean

        if clean.startswith("T"):
            return clean

        if clean in ("-", "", "0"):
            return "-"

        return f"IR{clean}"

    def segment_from_capteur(self, capteur: str) -> str:
        mapping = {
            "IR1": "Départ",
            "IR2": "S1 IR1-IR2",
            "IR3": "S2 IR2-IR3",
            "IR4": "S3 IR3-IR4",
        }
        return mapping.get(capteur, "-")

    def safe_float(self, value, default: float = 0.0) -> float:
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return default

    def safe_int(self, value, default: int = 0) -> int:
        try:
            return int(str(value).replace("T", "").replace("IR", ""))
        except (TypeError, ValueError):
            return default

    def refresh(self):
        # Met à jour les valeurs de l'UI avec l'état actuel
        minutes = int(self.state.elapsed // 60)
        seconds = self.state.elapsed % 60

        self.status_label.config(text=self.state.status)
        self.time_label.config(text=f"{minutes:02d}:{seconds:05.2f}")

        self.connection_label.config(
            text=f"MQTT: {'connecté' if self.state.connected else 'déconnecté'} | messages: {self.state.messages}",
            fg="#24c78e" if self.state.connected else "#ff5555",
        )

        self.info_label.config(
            text=f"Coureur: {self.state.active_runner} | Capteur: {self.state.active_sensor} | Segment: {self.state.active_segment}"
        )

        self.metric_time.value_label.config(text=f"{self.state.elapsed:.2f} s")
        self.metric_sector.value_label.config(text=f"{self.state.sector_time:.3f} s")
        self.metric_speed.value_label.config(text=f"{self.state.max_speed:.2f} km/h")
        self.metric_accel.value_label.config(text=f"{self.state.max_accel:.2f} m/s²")
        self.metric_distance.value_label.config(text=f"{self.state.distance_total:.2f} m")

        self.sector_tree.delete(*self.sector_tree.get_children())
        for row in self.state.sector_rows[-4:]:
            self.sector_tree.insert("", "end", values=row)

        self.runner_tree.delete(*self.runner_tree.get_children())
        runners = sorted(
            self.state.runners.values(),
            key=lambda r: r.best_lap if r.best_lap else 9999,
        )

        for pos, runner in enumerate(runners, start=1):
            best = f"{runner.best_lap:.2f}s" if runner.best_lap else "-"
            self.runner_tree.insert("", "end", values=(pos, runner.name, runner.current_lap, best))

        self.after(250, self.refresh)

    def shutdown(self):
        self.client.loop_stop()
        self.client.disconnect()
        self.root.destroy()


def main():
    # Point d'entrée de l'application
    root = tk.Tk()
    root.title("RacePi Dashboard")
    root.geometry("1100x720")
    root.configure(bg="#1f1f1f")

    app = Dashboard(root)
    root.protocol("WM_DELETE_WINDOW", app.shutdown)
    root.mainloop()


if __name__ == "__main__":
    main()