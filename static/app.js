"use strict";

const COLORS = ["#3f6ad8", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6", "#16a085"];

const map = L.map("map").setView([52.52, 13.405], 13);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

let currentStart = null;
let startMarker = null;
let routeLayers = [];

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setStatus(msg, kind) {
  const el = $("status");
  el.textContent = msg;
  el.className = "status" + (kind ? " " + kind : "");
}

function setStart(lat, lon) {
  if (startMarker) map.removeLayer(startMarker);
  startMarker = L.marker([lat, lon], { draggable: true }).addTo(map);
  startMarker.on("dragend", () => {
    const p = startMarker.getLatLng();
    currentStart = [p.lat, p.lng];
  });
  currentStart = [lat, lon];
  map.setView([lat, lon], Math.max(map.getZoom(), 14));
}

map.on("click", (e) => setStart(e.latlng.lat, e.latlng.lng));

// --- address search ---------------------------------------------------------
const searchInput = $("search");
const resultsEl = $("search-results");
let searchTimer = null;

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (q.length < 3) { resultsEl.innerHTML = ""; return; }
  searchTimer = setTimeout(async () => {
    try {
      const res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      resultsEl.innerHTML = "";
      for (const r of data.results || []) {
        const btn = document.createElement("button");
        btn.className = "result";
        btn.textContent = r.display_name;
        btn.addEventListener("click", () => {
          setStart(r.lat, r.lon);
          resultsEl.innerHTML = "";
          searchInput.value = r.display_name;
        });
        resultsEl.appendChild(btn);
      }
    } catch (e) {
      // silently ignore search errors
    }
  }, 350);
});

document.addEventListener("click", (e) => {
  if (!resultsEl.contains(e.target) && e.target !== searchInput) {
    resultsEl.innerHTML = "";
  }
});

// --- length slider ----------------------------------------------------------
const lengthInput = $("length");
const lengthLabel = $("length-label");
lengthInput.addEventListener("input", () => {
  lengthLabel.textContent = lengthInput.value + " km";
});

// --- generate ---------------------------------------------------------------
$("generate").addEventListener("click", generate);

async function generate() {
  if (!currentStart) {
    setStatus("Bitte zuerst einen Startpunkt wählen (in die Karte klicken).", "error");
    return;
  }

  const btn = $("generate");
  btn.disabled = true;
  setStatus("Generiere Routen …", "loading");
  $("route-list").innerHTML = "";
  routeLayers.forEach((l) => map.removeLayer(l));
  routeLayers = [];

  const body = {
    lat: currentStart[0],
    lon: currentStart[1],
    length_km: parseFloat(lengthInput.value),
    route_type: $("route-type").value,
    prefer: $("prefer").value,
    count: parseInt($("count").value, 10),
  };

  try {
    const res = await fetch("/api/routes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    drawRoutes(data.routes || []);
    setStatus(`${data.routes.length} Routen gefunden`, "ok");
  } catch (e) {
    setStatus("Fehler: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

function drawRoutes(routes) {
  const list = $("route-list");
  routes.forEach((r, i) => {
    const color = COLORS[i % COLORS.length];
    const latlngs = r.coordinates.map(([la, lo]) => [la, lo]);
    const poly = L.polyline(latlngs, { color, weight: 4, opacity: 0.85 }).addTo(map);
    routeLayers.push(poly);

    const green = r.green_score > 0.05
      ? ` · grün ${Math.round(r.green_score * 100)}%`
      : "";
    const card = document.createElement("div");
    card.className = "route-card";
    card.innerHTML = `
      <div class="swatch" style="background:${color}"></div>
      <div class="info">
        <div class="name">${escapeHtml(r.name)}</div>
        <div class="meta">${r.distance_km} km · ~${r.duration_min} min${green}</div>
      </div>
      <a class="gpx" href="${r.gpx_url}" download>GPX</a>`;
    list.appendChild(card);
  });

  if (routes.length) {
    const bounds = L.latLngBounds(
      routes.flatMap((r) => r.coordinates.map(([la, lo]) => [la, lo]))
    );
    map.fitBounds(bounds, { padding: [40, 40] });
  }
}
