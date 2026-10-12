# CampusNav

CampusNav is a Flask-based campus-navigation prototype. It provides an interactive Leaflet map with real OpenStreetMap-network routes, demonstration campus locations, an accessibility information page, and CSV-backed event listings.

## Features

- Four main pages: Navigate, Map, Accessibility, and Events.
- One shared location dataset in `data/locations.csv`.
- Walking, cycling, and car routes requested from Valhalla using OpenStreetMap network data.
- Real route geometry, route distance, estimated travel time, and turn-by-turn directions on the Map page.
- Displays alternative routes only when the routing service returns them; there is no generated-graph fallback.
- Leaflet map with OpenStreetMap tiles, location search, category filters, and location markers.
- Event add, edit, delete, title search, category/date filters, and CSV persistence.
- Event status is calculated from its date and times, including an automatic **Over** label once the event has ended.
- The Accessibility page displays the supplied route table with distance, ramp, lift, and note fields.

## Data status and limitations

Location names, coordinates, and event entries are demonstration data and may not match current campus information. Route requests use the coordinates in `data/locations.csv` and the external Valhalla service (`https://valhalla1.openstreetmap.de/route` by default). Network access is required to retrieve routes. Service or map-data coverage may affect availability and results; the application reports routing failures instead of drawing a generated route.

OpenStreetMap route data does not certify that a route, entrance, facility, or surface is accessible. Confirm route conditions and accessibility with authoritative campus information before travelling. Route estimates are not guarantees. There is no GPS-based positioning.

Events are stored in `data/events.csv` and persist across refreshes and application restarts. Do not put sensitive information in this demonstration file.

## Run in VS Code on Windows

In the integrated PowerShell terminal, run:

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

If PowerShell does not allow virtual-environment activation, use the interpreter directly:

```powershell
.\.venv\Scripts\python.exe app.py
```

Then open <http://127.0.0.1:5000>. For a fresh environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

## Test the prototype

1. Open Map, choose a start, destination, and travel mode, then request routes.
2. Select a returned route to highlight its geometry and expand its directions.
3. Search/filter map locations or select a marker to start planning a route.
4. On Events, add an event, refresh, edit it, then delete it; the CSV is the persistence store.
5. Confirm event status updates to **Over** after its end time.

## Structure

```text
app.py                 Flask routes, Valhalla integration, and event persistence
data/locations.csv     Shared demonstration locations and coordinates
data/events.csv        Demonstration events
static/style.css       Shared responsive light theme
templates/             Jinja pages and layouts
requirements.txt       Flask, requests and Gunicorn
```
