"""
CampusNav: demonstration campus navigation and accessibility prototype.

Locations and the walking/cycling graph are illustrative sample data, not an
officially verified campus map or audited accessibility network.
"""

from __future__ import annotations

import csv
import heapq
import os
from datetime import datetime
from itertools import count
from pathlib import Path

import requests
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "campusnav-local-development-key")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOCATIONS_CSV = DATA_DIR / "locations.csv"
EVENTS_CSV = DATA_DIR / "events.csv"
EVENT_FIELDS = [
    "id", "title", "description", "date", "start_time", "end_time",
    "category", "location", "organizer", "image_url", "priority",
]
EVENT_TIME_FORMAT = "%Y-%m-%d %H:%M"
SPEED_METRES_PER_MINUTE = {"walking": 80, "cycling": 250}


def _load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        return [
            {key.strip(): (value or "").strip() for key, value in row.items() if key}
            for row in csv.DictReader(file)
        ]


LOCATIONS = _load_csv(LOCATIONS_CSV)
LOCATIONS_BY_NAME = {location["name"]: location for location in LOCATIONS}

# Each connection is an illustrative graph edge: (from, to, metres, modes,
# step_free, stairs, ramp). All attributes require on-campus verification.
GRAPH_EDGES = [
    ("Main Gate (Gate 1)", "Gate 2", 145, ("walking", "cycling"), True, False, True),
    ("Main Gate (Gate 1)", "Parking (Students Cars)", 100, ("walking", "cycling"), True, False, True),
    ("Main Gate (Gate 1)", "Parking (Students Bikes)", 105, ("walking", "cycling"), True, False, True),
    ("Main Gate (Gate 1)", "Parking (Teachers)", 70, ("walking", "cycling"), True, False, True),
    ("Main Gate (Gate 1)", "LRC", 180, ("walking", "cycling"), True, False, True),
    ("Main Gate (Gate 1)", "MPH", 160, ("walking", "cycling"), True, False, True),
    ("Gate 2", "Innovation Hub", 95, ("walking",), True, False, True),
    ("Gate 2", "OAT", 80, ("walking", "cycling"), True, False, True),
    ("Gate 2", "Cafeteria", 120, ("walking", "cycling"), True, False, True),
    ("LRC", "Computer Lab 1", 90, ("walking", "cycling"), True, False, True),
    ("Computer Lab 1", "Computer Lab 2", 40, ("walking",), True, False, False),
    ("Computer Lab 1", "CSE Department", 55, ("walking", "cycling"), True, False, True),
    ("Computer Lab 2", "ECE Department", 85, ("walking", "cycling"), True, False, True),
    ("CSE Department", "Academic Block", 75, ("walking", "cycling"), True, False, True),
    ("ECE Department", "Academic Block", 65, ("walking", "cycling"), True, False, True),
    ("Academic Block", "Administration Office", 110, ("walking", "cycling"), True, False, True),
    ("Academic Block", "Seminar Hall", 90, ("walking",), True, False, False),
    ("Seminar Hall", "Auditorium", 135, ("walking", "cycling"), True, False, True),
    ("MPH", "Auditorium", 125, ("walking", "cycling"), True, False, True),
    ("MPH", "Main Ground", 115, ("walking", "cycling"), True, False, True),
    ("Main Ground", "Sports Ground", 170, ("walking",), True, False, False),
    ("Sports Ground", "Football Ground", 230, ("walking", "cycling"), True, False, True),
    ("LRC", "Mess", 210, ("walking", "cycling"), True, False, True),
    ("Mess", "Cafeteria", 40, ("walking", "cycling"), True, False, True),
    ("Cafeteria", "Main Canteen", 35, ("walking",), True, False, False),
    ("Main Canteen", "Food Court", 60, ("walking", "cycling"), True, False, True),
    ("Food Court", "Canteen 2", 80, ("walking", "cycling"), True, False, True),
    ("Mess", "Hostel Dining Hall", 160, ("walking", "cycling"), True, False, True),
    ("Hostel Dining Hall", "Boys' Hostel", 100, ("walking",), True, False, False),
    ("Hostel Dining Hall", "Girls' Hostel", 125, ("walking", "cycling"), True, False, True),
    ("Innovation Hub", "Medical Centre", 185, ("walking", "cycling"), True, False, True),
    ("Innovation Hub", "Student Activity Centre", 120, ("walking",), True, False, False),
    ("Student Activity Centre", "OAT", 75, ("walking", "cycling"), True, False, True),
    ("Medical Centre", "Bus Stop", 140, ("walking", "cycling"), True, False, True),
    ("Bus Stop", "Secondary Gate", 90, ("walking", "cycling"), True, False, True),
    ("Secondary Gate", "Visitor Parking", 65, ("walking", "cycling"), True, False, True),
    ("Visitor Parking", "Main Gate (Gate 1)", 155, ("walking", "cycling"), True, False, True),
    ("Parking Area", "Visitor Parking", 55, ("walking", "cycling"), True, False, True),
    ("Parking Area", "Administration Office", 185, ("walking", "cycling"), True, False, True),
    ("Parking (Students Cars)", "Parking Area", 80, ("walking", "cycling"), True, False, True),
    ("Parking (Students Bikes)", "MPH", 70, ("walking", "cycling"), True, False, True),
    ("Parking (Teachers)", "MPH", 80, ("walking", "cycling"), True, False, True),
    ("Football Ground", "Main Gate (Gate 1)", 200, ("walking", "cycling"), True, False, True),
]


def _neighbors(location: str, mode: str, step_free: bool) -> list[tuple[str, int, bool]]:
    adjacent = []
    for start, end, distance, modes, is_step_free, _stairs, _ramp in GRAPH_EDGES:
        if mode not in modes or (step_free and not is_step_free):
            continue
        if location == start:
            adjacent.append((end, distance, is_step_free))
        elif location == end:
            adjacent.append((start, distance, is_step_free))
    return adjacent


def _shortest_paths(source: str, destination: str, mode: str, step_free: bool, limit: int = 3) -> list[dict]:
    """Uniform-cost search over simple graph paths, returning the k shortest."""
    if source not in LOCATIONS_BY_NAME or destination not in LOCATIONS_BY_NAME:
        return []
    if mode not in SPEED_METRES_PER_MINUTE:
        return []
    queue: list[tuple[int, int, tuple[str, ...]]] = []
    sequence = count()
    heapq.heappush(queue, (0, next(sequence), (source,)))
    found = []
    while queue and len(found) < limit:
        distance, _order, path = heapq.heappop(queue)
        current = path[-1]
        if current == destination:
            found.append({
                "path": list(path),
                "distance_m": distance,
                "time_min": max(1, round(distance / SPEED_METRES_PER_MINUTE[mode])),
                "step_free": all(
                    edge[4]
                    for first, second in zip(path, path[1:])
                    for edge in GRAPH_EDGES
                    if {edge[0], edge[1]} == {first, second}
                ),
            })
            continue
        for neighbor, edge_distance, _is_step_free in _neighbors(current, mode, step_free):
            if neighbor not in path:
                heapq.heappush(
                    queue,
                    (distance + edge_distance, next(sequence), path + (neighbor,)),
                )
    return found


def _location_categories() -> list[str]:
    return sorted({location.get("category", "other") for location in LOCATIONS})


def _normalise_event(event: dict[str, str]) -> dict[str, str]:
    item = dict(event)
    start = item.get("start_time", "")
    end = item.get("end_time", "")
    if not item.get("date") and start:
        item["date"] = start[:10]
    if " " in start:
        item["start_time"] = start.split(" ", 1)[1]
    if " " in end:
        item["end_time"] = end.split(" ", 1)[1]
    for field, default in (
        ("description", ""), ("organizer", ""), ("image_url", ""),
        ("priority", "medium"), ("category", "event"), ("location", ""),
    ):
        item.setdefault(field, default)
    return item


def _all_events() -> list[dict[str, str]]:
    return [_normalise_event(event) for event in _load_csv(EVENTS_CSV)]


def _save_events(events: list[dict[str, str]]) -> None:
    with EVENTS_CSV.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        for event in events:
            item = _normalise_event(event)
            writer.writerow({field: item.get(field, "") for field in EVENT_FIELDS})


def _parse_event_form(form) -> tuple[dict[str, str] | None, str | None]:
    title = form.get("title", "").strip()
    event_date = form.get("date", "").strip()
    start_time = form.get("start_time", "").strip()
    end_time = form.get("end_time", "").strip()
    location = form.get("location", "").strip()
    if not title or not event_date or not location:
        return None, "Title, date, and location are required."
    try:
        datetime.strptime(event_date, "%Y-%m-%d")
        if start_time:
            datetime.strptime(start_time, "%H:%M")
        if end_time:
            datetime.strptime(end_time, "%H:%M")
    except ValueError:
        return None, "Enter a valid date and time."
    if start_time and end_time and end_time < start_time:
        return None, "End time must not be before start time."
    return {
        "title": title[:100],
        "description": form.get("description", "").strip()[:1000],
        "date": event_date,
        "start_time": start_time,
        "end_time": end_time,
        "category": form.get("category", "workshop").strip() or "workshop",
        "location": location[:120],
        "organizer": form.get("organizer", "").strip()[:120],
        "image_url": form.get("image_url", "").strip()[:500],
        "priority": form.get("priority", "medium").strip() or "medium",
    }, None


@app.route("/")
def index():
    return redirect(url_for("campus_map"))


@app.route("/welcome")
def welcome():
    return redirect(url_for("about"))


@app.route("/about")
def about():
    return render_template("about.html", active="about")


@app.route("/home")
def home():
    return render_template(
        "home.html",
        active="navigate",
        locations=LOCATIONS,
        selected_source=request.args.get("source", ""),
        selected_destination=request.args.get("destination", ""),
        selected_mode=request.args.get("mode", "walking"),
        step_free=request.args.get("step_free") == "1",
    )


@app.route("/map")
def campus_map():
    return render_template(
        "campus_map.html",
        active="map",
        locations=LOCATIONS,
        categories=_location_categories(),
    )


@app.route("/result", methods=["POST"])
def result():
    source = request.form.get("source", "").strip()
    destination = request.form.get("destination", "").strip()
    mode = request.form.get("mode", "walking").strip().lower()
    step_free = request.form.get("step_free") == "on"
    src = LOCATIONS_BY_NAME.get(source)
    dst = LOCATIONS_BY_NAME.get(destination)

    if not src or not dst:
        flash("Choose a starting point and destination from the location list.", "error")
        return redirect(url_for("home"))
    if source == destination:
        flash("Starting point and destination must be different.", "error")
        return redirect(url_for("home", source=source, destination=destination))

    routes = _shortest_paths(source, destination, mode, step_free)
    if mode == "car":
        message = "Car routes are unavailable: this prototype has no verified vehicle-road network."
    elif not routes:
        message = "No connected route is available for these locations and preferences."
    else:
        message = None
    return render_template(
        "result.html",
        active="navigate",
        source=source,
        destination=destination,
        src=src,
        dst=dst,
        locations=LOCATIONS,
        mode=mode,
        step_free=step_free,
        routes=routes,
        message=message,
    )


@app.route("/accessibility")
def accessibility():
    return render_template(
        "accessibility.html",
        active="accessibility",
        locations=LOCATIONS,
        routes=GRAPH_EDGES,
    )


@app.route("/events")
def events():
    all_events = sorted(
        _all_events(),
        key=lambda event: (event.get("date", ""), event.get("start_time", ""), event["title"].lower()),
    )
    query = request.args.get("q", "").strip().lower()
    category = request.args.get("category", "").strip().lower()
    event_date = request.args.get("date", "").strip()
    filtered = [
        event for event in all_events
        if (not query or query in event["title"].lower())
        and (not category or event["category"].lower() == category)
        and (not event_date or event["date"] == event_date)
    ]
    return render_template(
        "events.html",
        active="events",
        events=filtered,
        categories=sorted({event["category"] for event in all_events}),
        filters={"q": request.args.get("q", ""), "category": category, "date": event_date},
        editing=None,
    )


@app.route("/events/add", methods=["POST"])
def events_add():
    event, error = _parse_event_form(request.form)
    if error:
        flash(error, "error")
        return redirect(url_for("events"))
    all_events = _all_events()
    try:
        next_id = max((int(item.get("id", "0")) for item in all_events), default=0) + 1
    except ValueError:
        next_id = len(all_events) + 1
    event["id"] = str(next_id)
    all_events.append(event)
    _save_events(all_events)
    flash("Demonstration event added.", "success")
    return redirect(url_for("events"))


@app.route("/events/edit/<event_id>", methods=["GET", "POST"])
def events_edit(event_id: str):
    all_events = _all_events()
    event = next((item for item in all_events if item.get("id") == event_id), None)
    if event is None:
        flash("That event could not be found.", "error")
        return redirect(url_for("events"))
    if request.method == "POST":
        updated, error = _parse_event_form(request.form)
        if error:
            flash(error, "error")
            return redirect(url_for("events_edit", event_id=event_id))
        updated["id"] = event_id
        _save_events([updated if item.get("id") == event_id else item for item in all_events])
        flash("Event changes saved.", "success")
        return redirect(url_for("events"))
    return render_template(
        "events.html",
        active="events",
        events=all_events,
        categories=sorted({item["category"] for item in all_events}),
        filters={"q": "", "category": "", "date": ""},
        editing=event,
    )


@app.route("/events/delete/<event_id>", methods=["POST"])
def events_delete(event_id: str):
    all_events = _all_events()
    remaining = [event for event in all_events if event.get("id") != event_id]
    if len(remaining) == len(all_events):
        flash("That event could not be found.", "error")
    else:
        _save_events(remaining)
        flash("Event deleted.", "success")
    return redirect(url_for("events"))


@app.route("/api/locations")
def api_locations():
    return jsonify(LOCATIONS)


@app.route("/api/routes", methods=["POST"])
def api_routes():
    data = request.get_json(silent=True) or {}
    source = data.get("source")
    destination = data.get("destination")
    mode = data.get("mode", "walking")
    if not isinstance(source, str) or not isinstance(destination, str):
        return jsonify({"error": "source and destination are required"}), 400
    if source not in LOCATIONS_BY_NAME or destination not in LOCATIONS_BY_NAME:
        return jsonify({"error": "unknown location"}), 400
    if mode == "car":
        return jsonify({"error": "Car routing is unavailable without a verified road network."}), 422
    if mode not in SPEED_METRES_PER_MINUTE:
        return jsonify({"error": "mode must be walking, cycling, or car"}), 400
    return jsonify({
        "routes": _shortest_paths(source, destination, mode, bool(data.get("step_free")))
    })


@app.route("/api/directions", methods=["POST"])
def api_directions():
    """Proxy optional walking directions from the public OSRM service."""
    data = request.get_json(silent=True) or {}
    origin = data.get("origin")
    destination = data.get("destination")
    try:
        coordinates = [
            (float(origin["lat"]), float(origin["lng"])),
            (float(destination["lat"]), float(destination["lng"])),
        ]
    except (TypeError, KeyError, ValueError):
        return jsonify({"error": "valid origin and destination coordinates are required"}), 400
    if any(not (-90 <= lat <= 90 and -180 <= lng <= 180) for lat, lng in coordinates):
        return jsonify({"error": "coordinates are out of range"}), 400
    osrm_url = (
        "https://router.project-osrm.org/route/v1/foot/"
        f"{coordinates[0][1]},{coordinates[0][0]};{coordinates[1][1]},{coordinates[1][0]}"
        "?overview=full&geometries=geojson&steps=true"
    )
    try:
        response = requests.get(osrm_url, timeout=8)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.RequestException as exc:
        app.logger.warning("OSRM directions request failed: %s", exc)
        return jsonify({"error": "Walking directions service is temporarily unavailable."}), 502
    except ValueError:
        return jsonify({"error": "Walking directions service returned invalid data."}), 502


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", message="The page you requested does not exist."), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)