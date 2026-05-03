"""
Smart Campus Navigation System (SCNS)
=====================================
Software Engineering Lab Project
Course: 15B11CI513 - Software Engineering Lab
Program: B.Tech CSE - Jaypee Institute of Information Technology

Modules (per project synopsis):
    1. Map Navigation       (/, /home, /result)
    2. Accessibility Routes (/accessibility)
    3. Event & Emergency    (/events)
    4. Indoor Positioning   (/indoor)
    5. Directions API       (/api/directions)  - OSRM-backed walking route
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for
import csv
import os
import requests
from datetime import datetime

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

LOCATIONS_CSV    = os.path.join(DATA_DIR, "locations.csv")
EVENTS_CSV       = os.path.join(DATA_DIR, "events.csv")
ACCESSIBILITY_CSV = os.path.join(DATA_DIR, "accessibility.csv")
INDOOR_CSV       = os.path.join(DATA_DIR, "indoor_beacons.csv")


# --------------------------------------------------------------------- #
# Data loading                                                          #
# --------------------------------------------------------------------- #
def _load_csv(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
    return rows


LOCATIONS     = _load_csv(LOCATIONS_CSV)
EVENTS        = _load_csv(EVENTS_CSV)
ACCESSIBILITY = _load_csv(ACCESSIBILITY_CSV)
INDOOR        = _load_csv(INDOOR_CSV)


def _location_by_name(name):
    name = (name or "").strip().lower()
    for loc in LOCATIONS:
        if loc["name"].lower() == name:
            return loc
    return None


# --------------------------------------------------------------------- #
# Page routes                                                           #
# --------------------------------------------------------------------- #
@app.route("/")
def index():
    # Campus map is the default landing page
    return redirect(url_for("campus_map"))


@app.route("/welcome")
def welcome():
    # Original welcome / feature overview page kept at /welcome
    return render_template("index.html")


@app.route("/home")
def home():
    return render_template(
        "home.html",
        locations=[loc["name"] for loc in LOCATIONS],
    )


@app.route("/map")
def campus_map():
    return render_template("campus_map.html")


@app.route("/result", methods=["POST"])
def result():
    source = request.form.get("source", "").strip()
    destination = request.form.get("destination", "").strip()

    src = _location_by_name(source)
    dst = _location_by_name(destination)

    if not src or not dst:
        return render_template(
            "error.html",
            message="One or both locations were not found in the campus database.",
            source=source,
            destination=destination,
        )

    if source.lower() == destination.lower():
        return render_template(
            "error.html",
            message="Source and destination cannot be the same location.",
            source=source,
            destination=destination,
        )

    # Straight-line distance for a quick estimate (Haversine)
    distance_m = _haversine_m(
        float(src["latitude"]), float(src["longitude"]),
        float(dst["latitude"]), float(dst["longitude"]),
    )
    walk_min = max(1, round(distance_m / 80))   # ~80 m/min walking pace

    return render_template(
        "result.html",
        source=src["name"],
        destination=dst["name"],
        src=src,
        dst=dst,
        distance_m=int(distance_m),
        walk_min=walk_min,
    )


@app.route("/accessibility")
def accessibility():
    return render_template("accessibility.html", routes=ACCESSIBILITY)


EVENT_FIELDS = ["id", "title", "category", "location",
                "start_time", "end_time", "description", "priority"]


def _save_events():
    with open(EVENTS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        w.writeheader()
        for e in EVENTS:
            w.writerow({k: e.get(k, "") for k in EVENT_FIELDS})


def _split_events_by_time():
    """Bucket EVENTS into active / upcoming / past by current server time."""
    now = datetime.now()
    fmt = "%Y-%m-%d %H:%M"

    def parse(ts):
        try:
            return datetime.strptime(ts.strip(), fmt)
        except Exception:
            return None

    active, upcoming, past = [], [], []
    for e in EVENTS:
        start = parse(e.get("start_time", ""))
        end   = parse(e.get("end_time",   ""))
        item = dict(e)
        item["_start"] = start
        item["_end"]   = end
        if start and end and start <= now <= end:
            active.append(item)
        elif start and start > now:
            upcoming.append(item)
        elif end and end < now:
            past.append(item)
        else:
            upcoming.append(item)

    active.sort(key=lambda e: (e["category"] != "emergency", e.get("_start") or now))
    upcoming.sort(key=lambda e: e.get("_start") or now)
    past.sort(key=lambda e: e.get("_end") or now, reverse=True)
    return active, upcoming, past, now


@app.route("/events")
def events():
    active_events, upcoming, past, now = _split_events_by_time()
    return render_template(
        "events.html",
        active_events=active_events,
        upcoming=upcoming,
        past=past[:5],
        now=now.strftime("%d %b %Y, %H:%M"),
    )


@app.route("/events/add", methods=["POST"])
def events_add():
    """Append a new event to events.csv and reload."""
    f = request.form
    new_id = str(max([int(e.get("id") or 0) for e in EVENTS] + [0]) + 1)
    EVENTS.append({
        "id":          new_id,
        "title":       f.get("title", "").strip() or "Untitled",
        "category":    f.get("category", "event").strip() or "event",
        "location":    f.get("location", "Campus-wide").strip() or "Campus-wide",
        "start_time":  f.get("start_time", "").strip(),
        "end_time":    f.get("end_time", "").strip(),
        "description": f.get("description", "").strip(),
        "priority":    f.get("priority", "medium").strip() or "medium",
    })
    _save_events()
    return redirect(url_for("events"))


@app.route("/events/delete/<event_id>", methods=["POST"])
def events_delete(event_id):
    """Remove an event by id from events.csv and reload."""
    global EVENTS
    EVENTS = [e for e in EVENTS if str(e.get("id")) != str(event_id)]
    _save_events()
    return redirect(url_for("events"))


@app.route("/indoor")
def indoor():
    buildings = sorted({b["building"] for b in INDOOR})
    return render_template("indoor.html", beacons=INDOOR, buildings=buildings)


# --------------------------------------------------------------------- #
# JSON APIs                                                             #
# --------------------------------------------------------------------- #
@app.route("/api/locations")
def api_locations():
    return jsonify(LOCATIONS)


@app.route("/api/directions", methods=["POST"])
def api_directions():
    """
    Walking-route directions using the public OSRM server (no API key required).
    Body: { "origin": {"lat":..,"lng":..}, "destination": {"lat":..,"lng":..} }
    """
    data = request.get_json(silent=True) or {}
    origin = data.get("origin")
    destination = data.get("destination")
    if not origin or not destination:
        return jsonify({"error": "origin and destination required"}), 400

    osrm_url = (
        "https://router.project-osrm.org/route/v1/foot/"
        f"{origin['lng']},{origin['lat']};{destination['lng']},{destination['lat']}"
        "?overview=full&geometries=geojson&steps=true"
    )
    try:
        resp = requests.get(osrm_url, timeout=8)
        return jsonify(resp.json())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


# --------------------------------------------------------------------- #
# Helpers                                                               #
# --------------------------------------------------------------------- #
def _haversine_m(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt
    R = 6_371_000   # earth radius in metres
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


# --------------------------------------------------------------------- #
# Error handler                                                         #
# --------------------------------------------------------------------- #
@app.errorhandler(404)
def not_found(_):
    return render_template("error.html",
                           message="The page you requested does not exist."), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)
