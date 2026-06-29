import json
import math
import urllib.request
from pathlib import Path

URL = "https://images.parkrun.com/events.json"
OUT_HTML = Path("parkrun_map.html")
OUT_JSON = Path("parkrun_filtered.json")
OVERLAY_IMAGE = Path("canada_usa_parkrun.png")


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


with urllib.request.urlopen(URL) as resp:
    data = json.load(resp)

features = data["events"]["features"]
selected = []
for f in features:
    props = f.get("properties", {})
    code = props.get("countrycode")
    coords = f.get("geometry", {}).get("coordinates")
    if code not in {14, 98}:
        continue
    if not coords or len(coords) != 2:
        continue
    lon, lat = coords
    selected.append(
        {
            "id": props.get("id"),
            "name": props.get("EventShortName") or props.get("eventname"),
            "eventname": props.get("eventname"),
            "countrycode": code,
            "lat": lat,
            "lon": lon,
        }
    )

code14 = [e for e in selected if e["countrycode"] == 14]
code98 = [e for e in selected if e["countrycode"] == 98]
if not code14 or not code98:
    raise RuntimeError("No events left in one or both groups after filtering.")

edges = []
for e in code14:
    nearest = min(code98, key=lambda x: haversine_km(e["lat"], e["lon"], x["lat"], x["lon"]))
    dist_km = haversine_km(e["lat"], e["lon"], nearest["lat"], nearest["lon"])
    edges.append({"from": e, "to": nearest, "direction": "14_to_98", "distance_km": dist_km})

for e in code98:
    nearest = min(code14, key=lambda x: haversine_km(e["lat"], e["lon"], x["lat"], x["lon"]))
    dist_km = haversine_km(e["lat"], e["lon"], nearest["lat"], nearest["lon"])
    edges.append({"from": e, "to": nearest, "direction": "98_to_14", "distance_km": dist_km})

OUT_JSON.write_text(json.dumps({"events": selected, "edges": edges}, indent=2))

avg_lat = sum(e["lat"] for e in selected) / len(selected)
avg_lon = sum(e["lon"] for e in selected) / len(selected)
max_edge_distance = math.ceil(max(e["distance_km"] for e in edges))
default_distance = max_edge_distance
overlay_src = OVERLAY_IMAGE.name

html = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>parkrun nearest-neighbor map</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\" />
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    .legend, .controls {{ background: white; padding: 8px; line-height: 1.4; border-radius: 4px; }}
    .controls {{ min-width: 240px; }}
    .controls input {{ width: 100%; }}
    .corner-image-wrapper {{
      background: white;
      padding: 6px;
      border-radius: 4px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.25);
    }}
    .corner-image-wrapper img {{
      display: block;
      max-width: 260px;
      height: auto;
    }}
  </style>
</head>
<body>
<div id=\"map\"></div>
<script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\"></script>
<script>
const payload = {json.dumps({'events': selected, 'edges': edges})};
const map = L.map('map').setView([{avg_lat}, {avg_lon}], 6);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}}).addTo(map);

const edgeLayer = L.layerGroup().addTo(map);

function renderEdges(limitKm) {{
  edgeLayer.clearLayers();
  let visible = 0;
  for (const edge of payload.edges) {{
    if (edge.distance_km > limitKm) continue;
    visible += 1;
    const color = edge.direction === '14_to_98' ? '#1f77b4' : '#d62728';
    L.polyline([
      [edge.from.lat, edge.from.lon],
      [edge.to.lat, edge.to.lon]
    ], {{color, weight: 2, opacity: 0.65}})
    .bindTooltip(`${{edge.from.name}} -> ${{edge.to.name}} (${{edge.distance_km.toFixed(0)}} km)`)
    .addTo(edgeLayer);
  }}
  document.getElementById('edgeCount').textContent = String(visible);
  document.getElementById('distanceValue').textContent = `${{limitKm}} km`;
}}

for (const e of payload.events) {{
  const color = e.countrycode === 14 ? '#1f77b4' : '#d62728';
  L.circleMarker([e.lat, e.lon], {{ radius: 4, color, fillOpacity: 0.9 }})
    .bindPopup(`<a href='https://parkrun.${{e.countrycode === 14 ? 'ca' : 'us'}}/${{e.eventname}}'>${{e.name}}</a>`)
    .addTo(map);
}}

const controls = L.control({{position: 'topright'}});
controls.onAdd = function() {{
  const div = L.DomUtil.create('div', 'controls');
  div.innerHTML = `
    <div><b>Max distance</b></div>
    <input id="distanceSlider" type="range" min="1" max="{max_edge_distance}" value="{default_distance}" step="1" />
    <div><span id="distanceValue">{default_distance} km</span></div>
    <div>Visible edges: <span id="edgeCount">0</span> / ${{payload.edges.length}}</div>
  `;
  L.DomEvent.disableClickPropagation(div);
  return div;
}};
controls.addTo(map);

const slider = document.getElementById('distanceSlider');
slider.addEventListener('input', (e) => renderEdges(Number(e.target.value)));
renderEdges(Number(slider.value));

const legend = L.control({{position: 'bottomright'}});
legend.onAdd = function() {{
  const div = L.DomUtil.create('div', 'legend');
  div.innerHTML = `
    <div><b>Legend</b></div>
    <div><span style=\"color:#1f77b4\">●</span> 🇨🇦 CA</div>
    <div><span style=\"color:#d62728\">●</span> 🇺🇸 US</div>
    <div><span style=\"color:#1f77b4\">━</span> 🇨🇦 CA ➡️ closest 🇺🇸 US</div>
    <div><span style=\"color:#d62728\">━</span> 🇺🇸 US ➡️ closest 🇨🇦 CA</div>
  `;
  return div;
}};
legend.addTo(map);

const imageControl = L.control({{position: 'bottomleft'}});
imageControl.onAdd = function() {{
  const div = L.DomUtil.create('div', 'corner-image-wrapper');
  div.innerHTML = `<img src="{overlay_src}" alt="Canada & USA parkrun Canada Day & Thanksgiving 5Ks" />`;
  L.DomEvent.disableClickPropagation(div);
  return div;
}};
imageControl.addTo(map);
</script>
</body>
</html>
"""
OUT_HTML.write_text(html)

print(f"Events: {len(selected)} (🇨🇦 CA: {len(code14)}, 🇺🇸 US: {len(code98)})")
if not OVERLAY_IMAGE.exists():
    print(
        f"Overlay image not found at {OVERLAY_IMAGE}"
    )
