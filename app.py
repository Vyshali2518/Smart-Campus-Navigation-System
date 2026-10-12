"""CampusNav: OpenStreetMap-backed campus routing and event prototype."""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "campusnav-local-development-key")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOCATIONS_CSV = DATA_DIR / "locations.csv"
EVENTS_CSV = DATA_DIR / "events.csv"
ACCESSIBILITY_CSV = DATA_DIR / "accessibility.csv"
EVENT_FIELDS = [
    "id", "title", "description", "date", "end_date", "start_time", "end_time",
    "category", "location", "organizer", "image_url", "priority",
]
EVENT_TIME_FORMAT = "%Y-%m-%d %H:%M"
VALHALLA_ROUTE_URL = os.environ.get(
    "VALHALLA_ROUTE_URL",
    "https://valhalla1.openstreetmap.de/route",
)
ROUTE_COSTING = {"walking": "pedestrian", "cycling": "bicycle", "car": "auto"}
EVENT_CATEGORIES = {
    "workshop", "seminar", "technical event", "cultural event",
    "sports event", "club activity", "guest lecture", "notice", "emergency",
    "event", "academic", "sports",
}


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
ACCESSIBILITY_ROUTES = _load_csv(ACCESSIBILITY_CSV)

def _decode_polyline6(encoded: str) -> list[list[float]]:
    """Decode a Valhalla precision-6 shape into [latitude, longitude] points."""
    coordinates = []
    index = 0
    latitude = longitude = 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            result = shift = 0
            while True:
                if index >= len(encoded):
                    raise ValueError("Incomplete encoded route geometry")
                value = ord(encoded[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += deltas[0]
        longitude += deltas[1]
        coordinates.append([latitude / 1_000_000, longitude / 1_000_000])
    return coordinates


def _normalise_trip(trip: dict, label: str) -> dict:
    summary = trip.get("summary") or {}
    legs = trip.get("legs") or []
    coordinates = []
    instructions = []
    for leg in legs:
        shape = leg.get("shape", "")
        if shape:
            points = _decode_polyline6(shape)
            coordinates.extend(points if not coordinates else points[1:])
        for maneuver in leg.get("maneuvers", []):
            instruction = maneuver.get("instruction")
            if instruction:
                instructions.append(instruction)
    if not coordinates or not summary:
        raise ValueError("Routing service returned an incomplete trip")
    return {
        "name": label,
        "distance_m": round(float(summary["length"]) * 1000),
        "duration_seconds": round(float(summary["time"])),
        "time_min": max(1, round(float(summary["time"]) / 60)),
        "coordinates": coordinates,
        "instructions": instructions,
    }


def _request_real_routes(source: str, destination: str, mode: str) -> list[dict]:
    """Get real OSM-network routes from Valhalla; never fall back to a sketch."""
    source_location = LOCATIONS_BY_NAME[source]
    destination_location = LOCATIONS_BY_NAME[destination]
    payload = {
        "locations": [
            {
                "lat": float(source_location["latitude"]),
                "lon": float(source_location["longitude"]),
                "type": "break",
            },
            {
                "lat": float(destination_location["latitude"]),
                "lon": float(destination_location["longitude"]),
                "type": "break",
            },
        ],
        "costing": ROUTE_COSTING[mode],
        "alternates": 2,
        "units": "kilometers",
        "directions_options": {"units": "kilometers"},
    }
    response = requests.post(VALHALLA_ROUTE_URL, json=payload, timeout=15)
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise ValueError(data["error"])
    trips = [data.get("trip", {})]
    trips.extend(
        alternative["trip"]
        for alternative in data.get("alternates", [])
        if isinstance(alternative, dict) and isinstance(alternative.get("trip"), dict)
    )
    routes = []
    for index, trip in enumerate(trips):
        if trip:
            routes.append(_normalise_trip(trip, "Fastest route" if index == 0 else f"Alternative {index}"))
    if not routes:
        raise ValueError("No real route is available for this mode and location pair.")
    return routes


def _location_categories() -> list[str]:
    return sorted({location.get("category", "other") for location in LOCATIONS})


def _event_status(event: dict[str, str], now: datetime) -> str:
    event_date = event.get("date", "")
    if not event_date:
        return "Date needs review"
    end_date = event.get("end_date") or event_date
    start_time = event.get("start_time") or "00:00"
    end_time = event.get("end_time") or "23:59"
    try:
        start = datetime.strptime(f"{event_date} {start_time}", EVENT_TIME_FORMAT)
        end = datetime.strptime(f"{end_date} {end_time}", EVENT_TIME_FORMAT)
    except ValueError:
        return "Date needs review"
    if end < start:
        return "Date/time mismatch"
    if end < now:
        return "Over"
    if start <= now <= end:
        return "In progress"
    return "Upcoming"


def _normalise_event(event: dict[str, str]) -> dict[str, str]:
    item = dict(event)
    start = item.get("start_time", "")
    end = item.get("end_time", "")
    if " " in start:
        start_date, item["start_time"] = start.split(" ", 1)
        item["date"] = item.get("date") or start_date
    elif not item.get("date") and len(start) >= 10:
        item["date"] = start[:10]
    if " " in end:
        end_date, item["end_time"] = end.split(" ", 1)
        item["end_date"] = item.get("end_date") or end_date
    item["end_date"] = item.get("end_date") or item.get("date", "")
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
    end_date = form.get("end_date", "").strip() or event_date
    start_time = form.get("start_time", "").strip()
    end_time = form.get("end_time", "").strip()
    location = form.get("location", "").strip()
    if not title or not event_date or not location:
        return None, "Title, date, and location are required."
    try:
        datetime.strptime(event_date, "%Y-%m-%d")
        datetime.strptime(end_date, "%Y-%m-%d")
        if start_time:
            datetime.strptime(start_time, "%H:%M")
        if end_time:
            datetime.strptime(end_time, "%H:%M")
    except ValueError:
        return None, "Enter a valid date and time."
    start = datetime.strptime(f"{event_date} {start_time or '00:00'}", EVENT_TIME_FORMAT)
    end = datetime.strptime(f"{end_date} {end_time or '23:59'}", EVENT_TIME_FORMAT)
    if end < start:
        return None, "End date and time must not be before the start date and time."
    category = form.get("category", "workshop").strip().lower() or "workshop"
    if category not in EVENT_CATEGORIES:
        return None, "Choose a category from the list."
    image_url = form.get("image_url", "").strip()
    if image_url and urlsplit(image_url).scheme not in {"http", "https"}:
        return None, "Image URL must use http or https."
    return {
        "title": title[:100],
        "description": form.get("description", "").strip()[:1000],
        "date": event_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
        "category": category,
        "location": location[:120],
        "organizer": form.get("organizer", "").strip()[:120],
        "image_url": image_url[:500],
        "priority": form.get("priority", "medium").strip() or "medium",
    }, None


@app.route("/")
def index():
    return redirect(url_for("home"))


@app.route("/home")
def home():
    return render_template("home.html", active="navigate")


@app.route("/map")
def campus_map():
    requested_mode = request.args.get("mode", "walking")
    return render_template(
        "campus_map.html",
        active="map",
        locations=LOCATIONS,
        categories=_location_categories(),
        selected_source=request.args.get("source", "") if request.args.get("source", "") in LOCATIONS_BY_NAME else "",
        selected_destination=request.args.get("destination", "") if request.args.get("destination", "") in LOCATIONS_BY_NAME else "",
        selected_mode=requested_mode if requested_mode in ROUTE_COSTING else "walking",
    )


@app.route("/result", methods=["POST"])
def result():
    source = request.form.get("source", "").strip()
    destination = request.form.get("destination", "").strip()
    return redirect(
        url_for(
            "campus_map",
            source=source,
            destination=destination,
            mode=request.form.get("mode", "walking"),
        ) + "#route-planner"
    )


@app.route("/accessibility")
def accessibility():
    return render_template(
        "accessibility.html",
        active="accessibility",
        accessibility_routes=ACCESSIBILITY_ROUTES,
    )


@app.route("/events")
def events():
    now = datetime.now()
    all_events = sorted(
        _all_events(),
        key=lambda event: (event.get("date", ""), event.get("start_time", ""), event["title"].lower()),
    )
    for event in all_events:
        event["status"] = _event_status(event, now)
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
    if error or event is None:
        flash(error or "Event could not be saved.", "error")
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
        if error or updated is None:
            flash(error or "Event could not be saved.", "error")
            return redirect(url_for("events_edit", event_id=event_id))
        updated["id"] = event_id
        _save_events([updated if item.get("id") == event_id else item for item in all_events])
        flash("Event changes saved.", "success")
        return redirect(url_for("events"))
    for item in all_events:
        item["status"] = _event_status(item, datetime.now())
    event["status"] = _event_status(event, datetime.now())
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
    if mode not in ROUTE_COSTING:
        return jsonify({"error": "mode must be walking, cycling, or car"}), 400
    if source == destination:
        return jsonify({"error": "Choose different starting and destination locations."}), 400
    try:
        routes = _request_real_routes(source, destination, mode)
        return jsonify({
            "routes": routes,
            "mode": mode,
            "provider": "OpenStreetMap via Valhalla",
        })
    except requests.RequestException as exc:
        app.logger.warning("Valhalla route request failed for %s -> %s (%s): %s", source, destination, mode, exc)
        return jsonify({"error": "The real routing service is temporarily unavailable. Please try again."}), 502
    except (KeyError, TypeError, ValueError) as exc:
        app.logger.warning("Valhalla returned an unusable route for %s -> %s: %s", source, destination, exc)
        return jsonify({"error": str(exc)}), 422


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", message="The page you requested does not exist."), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)