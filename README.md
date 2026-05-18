# RacePi Dashboard

Interface graphique PC pour le projet intégrateur **RacePi** — un système de chronométrage de course sur piste basé sur Raspberry Pi et capteurs infrarouges.

## Description

Le dashboard reçoit les données de course en temps réel via **MQTT** et les affiche dans une interface tkinter. Il permet aussi de charger des historiques de course depuis un fichier CSV.

### Fonctionnalités

- Connexion MQTT automatique au broker local
- Affichage en temps réel : timer, statut de course, coureur actif
- Métriques : temps total, temps de segment, vitesse max, accélération max, distance
- Tableau des secteurs (4 derniers passages)
- Classement multi-coureurs avec meilleur tour
- Chargement de fichiers CSV de course
- Log terminal intégré

## Architecture MQTT

| Topic | Direction | Description |
|---|---|---|
| `racepi/#` | Subscribe | Tous les messages de la course |
| `racepi/status` | Subscribe | Statut du système |
| `racepi/race/start` | Subscribe | Début de course |
| `racepi/race/sectors` | Subscribe | Passage d'un secteur |
| `racepi/race/laps` | Subscribe | Fin de tour |
| `racepi/race/end` | Subscribe | Fin de course |
| `racepi/control/start` | Publish | Commande démarrage |
| `racepi/control/stop` | Publish | Commande arrêt/reset |

## Prérequis

- Python 3.10+
- Broker MQTT sur `localhost:1884`

## Installation

```bash
pip install -r requirements.txt
```

## Lancement

```bash
python racepi_dashboard.py
```

## Format CSV

Le fichier CSV doit contenir les colonnes suivantes :

| Colonne | Description |
|---|---|
| `coureur` | Nom du coureur |
| `tour` | Numéro du tour |
| `secteur` | Numéro du capteur IR |
| `temps_secteur_s` | Temps du segment en secondes |
| `distance_m` | Distance en mètres |
| `vitesse_ms` | Vitesse en m/s |
| `acceleration_ms2` | Accélération en m/s² |
| `faux_depart` | `True`/`False` |

Des fichiers CSV d'exemple sont inclus dans le repo (`course.csv`, `course-test-gui.csv`).
