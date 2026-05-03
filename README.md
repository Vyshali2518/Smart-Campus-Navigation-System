# Smart Campus Navigation System (SCNS)

A modular, mobile-first campus navigation platform built with Flask, Leaflet and OpenStreetMap, designed for **JIIT Sector 128, Noida**.

> Submitted for the Software Engineering Lab — `15B11CI513` — B.Tech CSE.

---

## Features

- **Live campus map** with numbered pins for every key location (Main Gate, LRC, MPH, Computer Labs, OAT, Innovation Hub, Hostels' parking, Mess, Cafeteria, etc.) — locked to the JIIT-128 boundary so the map can't drift away.
- **Click-to-route planner** — pick any two pins and get a walking route over the live OSM tiles plus turn-by-turn directions from the public OSRM router (no API key required).
- **Accessibility module** — a curated table of step-free / ramped / elevator-equipped routes with notes for differently-abled users.
- **Time-aware events feed** — events are bucketed into *Active Now* / *Upcoming* / *Recently Ended* by comparing each event's `start_time`/`end_time` against the server clock. Add or remove events in-app via a simple form, or by editing `data/events.csv` directly.
- **Indoor positioning registry** — Wi-Fi/BLE beacon table with reference RSSI values for fingerprint localisation inside LRC, MPH, Innovation Hub and the Computer Labs.

---

## Tech stack

- **Backend:** Python 3, Flask 3
- **Frontend:** HTML5, CSS3 (Poppins), Vanilla JS, Leaflet 1.9
- **Maps:** OpenStreetMap tiles + OSRM walking router
- **Data:** CSV files in `data/` — easy to swap for any other campus
- **Deployment:** Procfile + Gunicorn (Render / Heroku / Railway ready)

---

## Project structure

```
Smart-Campus-Navigation-System/
├── app.py                  # Flask routes + APIs
├── wsgi.py                 # WSGI entry point
├── Procfile                # Gunicorn run command
├── requirements.txt
├── README.md
├── .gitignore
├── static/
│   ├── style.css           # Shared dark theme
│   └── logo.png
├── templates/
│   ├── _base.html
│   ├── index.html          # /welcome
│   ├── home.html           # Source / Destination form
│   ├── campus_map.html     # /map (default landing)
│   ├── result.html         # Route page with Leaflet map
│   ├── accessibility.html
│   ├── events.html
│   ├── indoor.html
│   └── error.html
└── data/
    ├── locations.csv
    ├── accessibility.csv
    ├── events.csv
    └── indoor_beacons.csv
```

---

## Running locally

```bash
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5000/` — you'll land on the campus map.

---

## Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/` | Redirects to `/map` |
| `GET`  | `/map` | Full campus map with numbered pins + side list |
| `GET`  | `/home` | Source / destination form |
| `POST` | `/result` | Route page (map + turn-by-turn) |
| `GET`  | `/accessibility` | Step-free routes |
| `GET`  | `/events` | Active / Upcoming / Past events feed |
| `POST` | `/events/add` | Append a new event |
| `POST` | `/events/delete/<id>` | Delete an event |
| `GET`  | `/indoor` | Indoor beacon registry |
| `GET`  | `/welcome` | Original welcome / overview page |
| `GET`  | `/api/locations` | Locations as JSON |
| `POST` | `/api/directions` | Walking route from OSRM |

---

## Contributors

| Name | GitHub |
|------|--------|
| **Mitanshu Finaviya** *(lead)* | [@Mitanshu4529](https://github.com/Mitanshu4529) |
| Deepanshu Bhalia | — |
| Raunak Kheshwani | — |
| Devanshi Srivastava | — |

---

## License

Academic project — JIIT B.Tech CSE Software Engineering Lab.
