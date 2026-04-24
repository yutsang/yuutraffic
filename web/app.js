/* YuuTraffic static widget — vanilla JS + Leaflet.
   Loads route/stop/geometry data from ./data/ (published by GitHub Actions).
   Fetches live ETA directly from HK gov APIs (all CORS-open). */
(() => {
  "use strict";

  const DATA_BASE = "./data";
  const POLL_MS = 20_000;
  const MAX_BACKOFF_MS = 120_000;
  const IDLE_STOP_MS = 10 * 60_000;
  const NEAR_ME_RADIUS_M = 300;
  const NEAR_ME_MAX_STOPS = 20;

  const ETA_PROVIDERS = {
    KMB: (route, stop) =>
      `https://data.etabus.gov.hk/v1/transport/kmb/eta/${encodeURIComponent(stop.stop_id)}/${encodeURIComponent(route.id)}/${route.st || 1}`,
    CTB: (route, stop) =>
      `https://rt.data.gov.hk/v2/transport/citybus/eta/CTB/${encodeURIComponent(stop.stop_id)}/${encodeURIComponent(route.id)}`,
    GMB: (route, stop) =>
      route.pid
        ? `https://data.etagmb.gov.hk/eta/route-stop/${encodeURIComponent(route.pid)}/${encodeURIComponent(stop.stop_id)}`
        : null,
  };

  const COMPANY_LABEL = {
    KMB: "KMB / LWB",
    CTB: "Citybus",
    GMB: "Green Minibus",
    MTRB: "MTR Bus",
    RMB: "Red Minibus",
  };

  // Heuristic labels derived from the HK route-number suffix/prefix. Used to
  // surface schedule hints like "Peak only" / "Holiday only" without needing
  // a full timetable data source.
  function scheduleBadges(id) {
    const s = (id || "").toUpperCase();
    const out = [];
    if (s.startsWith("N"))            out.push({ en: "Night only",    tc: "通宵" });
    else if (s.startsWith("A"))       out.push({ en: "Airport",       tc: "機場" });
    else if (s.startsWith("E"))       out.push({ en: "Airport",       tc: "機場" });
    if (s.endsWith("X"))              out.push({ en: "Express",       tc: "特快" });
    else if (s.endsWith("P"))         out.push({ en: "Peak only",     tc: "繁忙時段" });
    else if (s.endsWith("S"))         out.push({ en: "Special",       tc: "特別班次" });
    else if (s.endsWith("R"))         out.push({ en: "Race days",     tc: "賽馬日" });
    else if (s.endsWith("M"))         out.push({ en: "MTR feeder",    tc: "地鐵接駁" });
    else if (s.endsWith("H"))         out.push({ en: "Holiday only",  tc: "只於假日" });
    else if (s.endsWith("B"))         out.push({ en: "Boundary",      tc: "邊境" });
    return out;
  }

  // Operators for which the precomputed geometry uses best-effort coordinates
  // (the public APIs don't expose exact stop locations for these companies).
  const APPROXIMATE_OPERATORS = new Set(["MTRB", "RMB"]);

  // Simple RGB midpoint blend so joint routes get a single blended colour
  // (KMB red + Citybus yellow → orange) instead of a diagonal split.
  function blendHex(c1, c2) {
    const parse = (h) => {
      h = h.replace("#", "");
      return [parseInt(h.slice(0, 2), 16),
              parseInt(h.slice(2, 4), 16),
              parseInt(h.slice(4, 6), 16)];
    };
    const [r1, g1, b1] = parse(c1);
    const [r2, g2, b2] = parse(c2);
    const hex = (v) => Math.round(v).toString(16).padStart(2, "0");
    return `#${hex((r1 + r2) / 2)}${hex((g1 + g2) / 2)}${hex((b1 + b2) / 2)}`;
  }

  function withAlpha(hex, alpha) {
    const parse = (h) => {
      h = h.replace("#", "");
      return [parseInt(h.slice(0, 2), 16),
              parseInt(h.slice(2, 4), 16),
              parseInt(h.slice(4, 6), 16)];
    };
    const [r, g, b] = parse(hex);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  const state = {
    routes: [],
    stops: null,            // lazy
    stopRoutes: null,       // lazy
    meta: null,
    selectedRoute: null,
    selectedDirection: 1,
    selectedStop: null,
    geometry: null,
    map: null,
    routeLayer: null,
    stopLayers: [],
    selectedStopLayer: null,
    youAreHereLayer: null,
    nearbyRoutes: null,     // cached result of geolocation search
    etaTimer: null,
    etaErrorCount: 0,
    lastUserActionAt: Date.now(),
  };

  // --------------------------------------------------------- utility helpers

  const $ = (id) => document.getElementById(id);

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  // Client-side fallback for the title-casing the pipeline already applies.
  // Keeps old cached data rendering correctly until the user re-runs
  // publish.sh to regenerate the bundles.
  const TITLE_PRESERVE = new Set([
    "MTR", "LRT", "HK", "HKIA", "HKU", "HKUST", "CUHK", "UST", "POLYU",
    "GPO", "AEL", "TCL", "TWL", "KTL", "EAL", "ISL", "SIL", "WRL",
    "KMB", "LWB", "CTB", "NWFB", "GMB", "MOL", "SEL", "DRL",
    "HKCEC", "IFC", "YMCA", "HSBC", "ICBC", "UK", "US",
  ]);

  function displayEn(s) {
    if (!s) return s;
    // If already mixed case, leave as-is
    if (/[a-z]/.test(s)) return s;
    return s.split(/(\s+|[()/\-])/).map((w) => {
      if (!w || /^\s+$/.test(w) || "()/-".includes(w)) return w;
      if (/\d/.test(w)) return w;
      const up = w.toUpperCase();
      if (TITLE_PRESERVE.has(up)) return up;
      return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
    }).join("");
  }

  function fetchJson(url, opts) {
    return fetch(url, opts).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
      return r.json();
    });
  }

  function etaMinutes(iso) {
    if (!iso) return null;
    const diffMs = new Date(iso).getTime() - Date.now();
    return Math.round(diffMs / 60_000);
  }

  function etaText(iso) {
    const mins = etaMinutes(iso);
    if (mins === null) return "—";
    if (mins <= 0) return "Now";
    if (mins === 1) return "1 min";
    return `${mins} min`;
  }

  function bumpActivity() {
    state.lastUserActionAt = Date.now();
  }

  // Natural sort: "1" < "1A" < "2" < "10" < "100A"
  function compareRouteIds(a, b) {
    return String(a).localeCompare(String(b), "en", {
      numeric: true, sensitivity: "base",
    });
  }

  // Haversine distance in metres
  function distanceM(lat1, lng1, lat2, lng2) {
    const toRad = (d) => d * Math.PI / 180;
    const R = 6371000;
    const dLat = toRad(lat2 - lat1);
    const dLng = toRad(lng2 - lng1);
    const a = Math.sin(dLat / 2) ** 2 +
              Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
              Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  // -------------------------------------------------------------------- init

  async function init() {
    applyEmbedMode();
    initMap();
    initSearch();
    initDirectionToggle();
    initActivityTracking();
    initVisibility();
    initRefreshButton();
    initViewportResize();
    $("yuu-meta").textContent = "Loading routes…";

    try {
      const [routes, meta] = await Promise.all([
        fetchJson(`${DATA_BASE}/routes.json`),
        fetchJson(`${DATA_BASE}/meta.json`),
      ]);
      // Whether routes are joint (e.g. KMB + Citybus 101) is determined
      // by the pipeline using stop-set overlap — too data-heavy to replicate
      // client-side. If the bundle already has `partners` fields, they're
      // respected; otherwise every route stays solo.
      state.routes = routes;
      state.meta = meta;
      renderMeta();
    } catch (err) {
      console.error("Failed to load bundles", err);
      $("yuu-meta").textContent =
        "Failed to load transport data. The build may not have run yet.";
      return;
    }

    // Ask for location on load. If permission already granted, runs
    // silently. If not, the browser shows its native prompt — user can
    // allow/deny without affecting the rest of the page.
    maybeAutoLocate();
  }

  async function maybeAutoLocate() {
    if (!navigator.geolocation) return;
    try {
      if (navigator.permissions && navigator.permissions.query) {
        const p = await navigator.permissions.query({ name: "geolocation" });
        if (p.state === "denied") return;
      }
    } catch { /* Safari may not support permissions API — fall through */ }
    navigator.geolocation.getCurrentPosition(
      (pos) => computeNearbyRoutes(pos.coords.latitude, pos.coords.longitude)
                 .catch((e) => console.warn(e)),
      (err) => console.info("Location unavailable:", err.message),
      { enableHighAccuracy: false, timeout: 12_000, maximumAge: 5 * 60_000 }
    );
  }

  function applyEmbedMode() {
    const params = new URLSearchParams(location.search);
    if (params.has("embed")) {
      document.documentElement.classList.add("yuu-embedded");
    }
  }

  async function ensureStopsLoaded() {
    if (state.stops) return state.stops;
    state.stops = await fetchJson(`${DATA_BASE}/stops.json`);
    return state.stops;
  }

  async function ensureStopRoutesLoaded() {
    if (state.stopRoutes) return state.stopRoutes;
    try {
      state.stopRoutes = await fetchJson(`${DATA_BASE}/stop_routes.json`);
    } catch (err) {
      console.warn("stop_routes.json not available — re-run publish.sh", err);
      state.stopRoutes = {};
    }
    return state.stopRoutes;
  }

  function renderMeta() {
    const m = state.meta;
    if (!m) return;
    const when = new Date(m.generated_at);
    const date = when.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
    const c = m.counts || {};
    $("yuu-meta").textContent =
      `${c.routes || state.routes.length} routes · refreshed ${date}`;
  }

  // ------------------------------------------------------------------ search

  function initSearch() {
    const input = $("yuu-search-input");
    const results = $("yuu-search-results");

    input.addEventListener("input", () => {
      bumpActivity();
      if (input.value.trim() === "") {
        showNearbySuggestions();
      } else {
        runSearch(input.value);
      }
    });

    input.addEventListener("focus", () => {
      if (input.value.trim()) runSearch(input.value);
      else showNearbySuggestions();
    });

    document.addEventListener("click", (e) => {
      if (!e.target.closest(".yuu-search")) results.hidden = true;
    });

    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { input.value = ""; results.hidden = true; }
    });
  }

  function runSearch(q) {
    const results = $("yuu-search-results");
    const query = q.trim().toUpperCase();
    if (query.length < 1) { results.hidden = true; return; }

    const prefix = [];
    const contains = [];
    for (const r of state.routes) {
      const id = (r.id || "").toUpperCase();
      if (id.startsWith(query)) { prefix.push(r); continue; }
      if (id.includes(query) ||
          (r.oe || "").toUpperCase().includes(query) ||
          (r.de || "").toUpperCase().includes(query) ||
          (r.ot || "").includes(q) || (r.dt || "").includes(q)) {
        contains.push(r);
      }
    }
    prefix.sort((a, b) => compareRouteIds(a.id, b.id));
    contains.sort((a, b) => compareRouteIds(a.id, b.id));
    const matches = prefix.concat(contains).slice(0, 30);

    renderSearchResults(matches);
  }

  function renderSearchResults(matches, title) {
    const results = $("yuu-search-results");
    if (matches.length === 0) {
      results.innerHTML = '<div class="yuu-search-empty">No matching routes</div>';
      results.hidden = false;
      return;
    }
    const heading = title
      ? `<div class="yuu-search-heading">${escapeHtml(title)}</div>` : "";
    results.innerHTML = heading + matches.map((r) => {
      const tc = (r.ot && r.dt)
        ? `<span class="yuu-search-result-tc">${escapeHtml(r.ot)} ↔ ${escapeHtml(r.dt)}</span>`
        : "";
      const coLabel = r.partners && r.partners.length > 1
        ? r.partners.map((p) => COMPANY_LABEL[p.co] || p.co).join(" + ")
        : (COMPANY_LABEL[r.co] || r.co);
      const chips = scheduleBadges(r.id).map((b) =>
        `<span class="yuu-search-chip">${escapeHtml(b.en)} · ${escapeHtml(b.tc)}</span>`
      ).join("");
      return `<div class="yuu-search-result" data-rk="${escapeHtml(r.rk)}">
        <span class="yuu-badge ${r.co}">${escapeHtml(r.id)}</span>
        <div class="yuu-search-result-body">
          <span class="yuu-search-result-name">${escapeHtml(displayEn(r.oe))} ↔ ${escapeHtml(displayEn(r.de))}</span>
          ${tc}
          <span class="yuu-search-result-co">${escapeHtml(coLabel)}${chips ? " " + chips : ""}</span>
        </div>
      </div>`;
    }).join("");
    results.hidden = false;

    results.querySelectorAll(".yuu-search-result[data-rk]").forEach((node) => {
      node.addEventListener("click", () => {
        const route = state.routes.find((r) => r.rk === node.dataset.rk);
        if (route) selectRoute(route);
      });
    });
  }

  // ---------------------------------------------------------------- near me

  // Cache nearby results so focusing the empty search box repeatedly doesn't
  // re-trigger geolocation or reload stops.json/stop_routes.json.
  async function computeNearbyRoutes(lat, lng) {
    if (state.youAreHereLayer) state.map.removeLayer(state.youAreHereLayer);
    state.youAreHereLayer = L.circleMarker([lat, lng], {
      radius: 8, fillColor: "#3b82f6", color: "#ffffff",
      weight: 3, fillOpacity: 0.95,
    }).bindTooltip("You are here").addTo(state.map);
    state.map.setView([lat, lng], 16);

    const [stops, stopRoutes] = await Promise.all([
      ensureStopsLoaded(),
      ensureStopRoutesLoaded(),
    ]);

    const nearby = [];
    for (const [stopId, s] of Object.entries(stops)) {
      const d = distanceM(lat, lng, s.la, s.lg);
      if (d <= NEAR_ME_RADIUS_M) nearby.push({ stopId, d });
    }
    nearby.sort((a, b) => a.d - b.d);
    const topStops = nearby.slice(0, NEAR_ME_MAX_STOPS);

    const routeKeys = new Set();
    for (const n of topStops) {
      (stopRoutes[n.stopId] || []).forEach((rk) => routeKeys.add(rk));
    }

    const routes = state.routes
      .filter((r) => routeKeys.has(r.rk))
      .sort((a, b) => compareRouteIds(a.id, b.id));

    state.nearbyRoutes = {
      routes,
      stopCount: topStops.length,
      radiusM: NEAR_ME_RADIUS_M,
    };

    // If the search box is already empty and focused, refresh the dropdown.
    const input = $("yuu-search-input");
    if (input === document.activeElement && input.value.trim() === "") {
      showNearbySuggestions();
    }
  }

  function showNearbySuggestions() {
    const n = state.nearbyRoutes;
    if (!n || n.routes.length === 0) {
      $("yuu-search-results").hidden = true;
      return;
    }
    renderSearchResults(
      n.routes,
      `Near you (${n.radiusM} m · ${n.stopCount} stops)`
    );
  }

  // ------------------------------------------------------------- route panel

  async function selectRoute(route) {
    bumpActivity();
    state.selectedRoute = route;
    state.selectedStop = null;
    state.selectedDirection = (route.dirs && route.dirs[0]) || 1;

    // Theme the widget by company (colours polyline, stop-seq badges, etc.)
    const yuu = $("yuu");
    yuu.dataset.company = route.co || "";
    // Joint routes: blend the partner colours into one accent so the map
    // and stop badges show a unified hue (KMB red + Citybus yellow = orange).
    if (route.partners && route.partners.length > 1) {
      const colors = route.partners.map((p) => companyColor(p.co));
      const blended = colors.reduce((a, b) => blendHex(a, b));
      yuu.dataset.joint = "true";
      yuu.style.setProperty("--yuu-route-color", blended);
      yuu.style.setProperty("--yuu-route-color-soft", withAlpha(blended, 0.18));
      yuu.style.setProperty("--yuu-route-text", "#ffffff");
    } else {
      yuu.dataset.joint = "false";
      yuu.style.removeProperty("--yuu-route-color");
      yuu.style.removeProperty("--yuu-route-color-soft");
      yuu.style.removeProperty("--yuu-route-text");
    }

    $("yuu-search-input").value = route.id;
    $("yuu-search-results").hidden = true;
    $("yuu-welcome").hidden = true;
    $("yuu-route").hidden = false;
    $("yuu-eta").hidden = true;
    stopEtaPolling();

    if (state.map) setTimeout(() => state.map.invalidateSize(), 0);

    const badge = $("yuu-route-badge");
    badge.textContent = route.id;
    badge.className = `yuu-badge ${route.co}`;

    const operatorLabel = route.partners && route.partners.length > 1
      ? route.partners.map((p) => COMPANY_LABEL[p.co] || p.co).join(" + ")
      : (COMPANY_LABEL[route.co] || route.co);
    const badges = scheduleBadges(route.id).map((b) =>
      `<span class="yuu-schedule-chip">${escapeHtml(b.en)} · ${escapeHtml(b.tc)}</span>`
    ).join("");
    const allApprox = (route.partners && route.partners.length > 0
                        ? route.partners
                        : [{ co: route.co }])
                      .every((p) => APPROXIMATE_OPERATORS.has(p.co));
    const approxChip = allApprox
      ? `<span class="yuu-schedule-chip yuu-approx-chip" title="Coordinates are best-effort">Approximate route · 路線僅供參考</span>`
      : "";
    $("yuu-company-label").innerHTML =
      `<span class="yuu-op-text">${escapeHtml(operatorLabel)}</span>${badges}${approxChip}`;

    const dirs = route.dirs && route.dirs.length ? route.dirs : [1];
    document.querySelectorAll(".yuu-dir-btn").forEach((btn) => {
      const d = Number(btn.dataset.dir);
      btn.style.display = dirs.includes(d) ? "" : "none";
      btn.classList.toggle("active", d === state.selectedDirection);
    });

    updateRouteTitle();
    await loadDirection();
  }

  function initDirectionToggle() {
    document.querySelectorAll(".yuu-dir-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        bumpActivity();
        const d = Number(btn.dataset.dir);
        if (!state.selectedRoute) return;
        state.selectedDirection = d;
        state.selectedStop = null;
        $("yuu-eta").hidden = true;
        stopEtaPolling();
        document.querySelectorAll(".yuu-dir-btn").forEach((b) =>
          b.classList.toggle("active", b === btn)
        );
        updateRouteTitle();
        loadDirection();
      });
    });
  }

  function updateRouteTitle() {
    const r = state.selectedRoute;
    if (!r) return;
    const outbound = state.selectedDirection === 1;
    const from = outbound ? r.oe : r.de;
    const to = outbound ? r.de : r.oe;
    const fromTc = outbound ? r.ot : r.dt;
    const toTc = outbound ? r.dt : r.ot;
    const en = `${from || "?"} → ${to || "?"}`;
    const tc = (fromTc && toTc) ? `${fromTc} → ${toTc}` : "";
    $("yuu-route-title").innerHTML = tc
      ? `${escapeHtml(en)}<br><span class="yuu-route-subtitle">${escapeHtml(tc)}</span>`
      : escapeHtml(en);
  }

  // For KMB routes, the precomputed geometry uses whichever service_type was
  // stored last in SQLite — which is wrong when the user picked a different
  // variant (e.g., 219X/st=1 Laguna City vs 219X/st=4 Ko Ling Road) and also
  // drops seq=1 on circular routes. Fetch the authoritative stop list from
  // the live KMB API for the selected variant, and replace geo.stops.
  async function replaceStopsFromLiveKmb(geo, route, direction) {
    const bound = direction === 1 ? "outbound" : "inbound";
    const st = route.st || 1;
    try {
      const resp = await fetchJson(
        `https://data.etabus.gov.hk/v1/transport/kmb/route-stop/${encodeURIComponent(route.id)}/${bound}/${st}`
      );
      const upstream = (resp.data || []).slice().sort(
        (a, b) => Number(a.seq) - Number(b.seq)
      );
      if (upstream.length === 0) return;

      const stops = await ensureStopsLoaded();
      const rebuilt = upstream.map((e) => {
        const info = stops[e.stop] || {};
        return {
          stop_id: e.stop,
          stop_name: info.ne || "",
          stop_name_tc: info.nt || "",
          sequence: Number(e.seq),
          company: "KMB",
          lat: info.la,
          lng: info.lg,
        };
      });
      geo.stops = rebuilt;
    } catch (err) {
      console.warn("Could not fetch live KMB stops; falling back to bundled geometry", err);
    }
  }

  async function loadDirection() {
    const r = state.selectedRoute;
    const d = state.selectedDirection;
    if (!r) return;
    const url = `${DATA_BASE}/geometry/${r.rk}_${d}.json`;

    try {
      const geo = await fetchJson(url);
      // KMB: fetch the live per-variant stop list (fixes circular seq=1
      // gap AND service_type variants that share a geometry file).
      if (r.co === "KMB") {
        await replaceStopsFromLiveKmb(geo, r, d);
      }
      if (Array.isArray(geo.stops)) {
        geo.stops.forEach((s, i) => { s.sequence = i + 1; });
      }
      state.geometry = geo;
      renderRouteOnMap(geo);
      renderStops(geo);
    } catch (err) {
      console.warn("No geometry for", r.rk, d, err);
      state.geometry = null;
      renderStops({ stops: [] });
      if (state.routeLayer) {
        state.map.removeLayer(state.routeLayer);
        state.routeLayer = null;
      }
      state.stopLayers.forEach((l) => state.map.removeLayer(l));
      state.stopLayers = [];
      const el = $("yuu-stops");
      el.innerHTML = '<div class="yuu-search-empty">No route data available for this direction.</div>';
    }
  }

  // ------------------------------------------------------------------- map

  function initMap() {
    state.map = L.map("yuu-map", { zoomControl: true })
      .setView([22.3193, 114.1694], 11);
    // Voyager: colourful CARTO basemap — faster than osm.org and friendlier
    // on the eye than light_all (which was grayscale).
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: "abcd",
      maxZoom: 20,
    }).addTo(state.map);
  }

  function companyColor(co) {
    return ({
      KMB: "#e63946",
      CTB: "#f5b800",  // slightly darker yellow for better legibility on maps
      GMB: "#2a9d8f",
      MTRB: "#1d3557",
      RMB: "#d62828",
    })[co] || "#00338d";
  }

  function renderRouteOnMap(geo) {
    if (state.routeLayer) {
      state.map.removeLayer(state.routeLayer);
      state.routeLayer = null;
    }
    if (state.partnerLayer) {
      state.map.removeLayer(state.partnerLayer);
      state.partnerLayer = null;
    }
    state.stopLayers.forEach((l) => state.map.removeLayer(l));
    state.stopLayers = [];
    if (state.selectedStopLayer) {
      state.map.removeLayer(state.selectedStopLayer);
      state.selectedStopLayer = null;
    }

    const route = state.selectedRoute;
    const isJoint = route?.partners && route.partners.length > 1;
    const primaryColor = isJoint
      ? route.partners.map((p) => companyColor(p.co)).reduce((a, b) => blendHex(a, b))
      : companyColor(route?.co);

    const coords = Array.isArray(geo.coords) ? geo.coords : [];
    if (coords.length > 1) {
      state.routeLayer = L.polyline(coords, {
        color: primaryColor, weight: 5, opacity: 0.88,
      }).addTo(state.map);
    } else if (geo.stops && geo.stops.length > 1) {
      const fallback = geo.stops
        .map((s) => [s.lat, s.lng])
        .filter(([a, b]) => typeof a === "number" && typeof b === "number");
      state.routeLayer = L.polyline(fallback, {
        color: "#999", weight: 2, dashArray: "5, 5",
      }).addTo(state.map);
    }

    (geo.stops || []).forEach((s) => {
      if (typeof s.lat !== "number" || typeof s.lng !== "number") return;
      const marker = L.circleMarker([s.lat, s.lng], {
        radius: 5, fillColor: primaryColor,
        color: "#ffffff", weight: 2, fillOpacity: 1,
      }).addTo(state.map);
      const tc = s.stop_name_tc ? ` · ${s.stop_name_tc}` : "";
      marker.bindTooltip(`${s.sequence}. ${displayEn(s.stop_name) || s.stop_id}${tc}`);
      marker.on("click", () => selectStop(s));
      state.stopLayers.push(marker);
    });

    if (state.routeLayer) {
      state.map.fitBounds(state.routeLayer.getBounds(), { padding: [30, 30] });
    }
  }

  // ------------------------------------------------------------------ stops

  function renderStops(geo) {
    const el = $("yuu-stops");
    const stops = geo.stops || [];
    if (stops.length === 0) {
      el.innerHTML = '<div class="yuu-search-empty">No stops listed</div>';
      return;
    }
    el.innerHTML = stops.map((s) => `
      <div class="yuu-stop-item" data-stop-id="${escapeHtml(s.stop_id)}" data-seq="${s.sequence}">
        <span class="yuu-stop-seq">${s.sequence}</span>
        <div class="yuu-stop-labels">
          <span class="yuu-stop-name">${escapeHtml(displayEn(s.stop_name) || s.stop_id)}</span>
          ${s.stop_name_tc
            ? `<span class="yuu-stop-name-tc">${escapeHtml(s.stop_name_tc)}</span>`
            : ""}
        </div>
      </div>`).join("");

    el.querySelectorAll(".yuu-stop-item").forEach((node) => {
      node.addEventListener("click", () => {
        const stop = stops.find((x) => x.stop_id === node.dataset.stopId);
        if (stop) selectStop(stop);
      });
    });
  }

  function selectStop(stop) {
    bumpActivity();
    // Allow re-clicking the already-selected stop to force a manual refresh.
    const sameStop = state.selectedStop && state.selectedStop.stop_id === stop.stop_id;
    state.selectedStop = stop;

    document.querySelectorAll(".yuu-stop-item").forEach((n) =>
      n.classList.toggle("active", n.dataset.stopId === stop.stop_id)
    );

    $("yuu-eta").hidden = false;
    $("yuu-eta-stop").innerHTML =
      `${stop.sequence}. ${escapeHtml(displayEn(stop.stop_name) || stop.stop_id)}` +
      (stop.stop_name_tc ? ` <span class="yuu-eta-stop-tc">${escapeHtml(stop.stop_name_tc)}</span>` : "");
    if (!sameStop) {
      $("yuu-eta-list").innerHTML = '<li class="yuu-eta-empty">Loading…</li>';
      $("yuu-eta-fresh").textContent = "";
    }

    if (state.selectedStopLayer) state.map.removeLayer(state.selectedStopLayer);
    const color = companyColor(state.selectedRoute?.co);
    if (typeof stop.lat === "number" && typeof stop.lng === "number") {
      state.selectedStopLayer = L.circleMarker([stop.lat, stop.lng], {
        radius: 10, fillColor: color,
        color: "#ffffff", weight: 4, fillOpacity: 1,
      }).addTo(state.map);
      state.map.setView([stop.lat, stop.lng], 16, { animate: true });
      // On mobile, the ETA sheet docks from the bottom and can cover the
      // stop marker. Nudge the map so the marker sits in the upper portion
      // of the visible area above the sheet.
      if (window.matchMedia("(max-width: 768px)").matches) {
        const nudge = () => {
          const sheetH = ($("yuu-eta")?.offsetHeight) || 0;
          if (sheetH > 0) state.map.panBy([0, sheetH * 0.45], { animate: true });
        };
        setTimeout(nudge, 260);
      }
    }

    startEtaPolling();
    const row = document.querySelector(`.yuu-stop-item[data-stop-id="${CSS.escape(stop.stop_id)}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // ---------------------------------------------------------------- ETA poll

  function initRefreshButton() {
    $("yuu-eta-refresh").addEventListener("click", () => {
      bumpActivity();
      if (!state.selectedStop) return;
      const btn = $("yuu-eta-refresh");
      btn.classList.add("spinning");
      pollEta().finally(() => {
        setTimeout(() => btn.classList.remove("spinning"), 400);
      });
    });
  }

  function startEtaPolling() {
    stopEtaPolling();
    state.etaErrorCount = 0;
    pollEta();
    state.etaTimer = setInterval(pollEta, POLL_MS);
  }

  function stopEtaPolling() {
    if (state.etaTimer) {
      clearInterval(state.etaTimer);
      state.etaTimer = null;
    }
  }

  async function pollEta() {
    if (document.hidden) return;
    if (Date.now() - state.lastUserActionAt > IDLE_STOP_MS) {
      stopEtaPolling();
      $("yuu-eta-fresh").textContent = "Paused (idle) — click a stop to resume";
      return;
    }

    const r = state.selectedRoute;
    const s = state.selectedStop;
    if (!r || !s) return;

    // Joint routes (e.g. KMB+CTB 101) have a `partners` list; query every
    // operator and merge results. Solo routes fall through to [self].
    const operators = (r.partners && r.partners.length > 0)
      ? r.partners
      : [{ co: r.co, id: r.id, pid: r.pid, st: r.st, rk: r.rk }];

    const viable = operators
      .map((op) => ({ op, url: (ETA_PROVIDERS[op.co] || (() => null))(op, s) }))
      .filter((x) => x.url);
    if (viable.length === 0) {
      renderEta([], "Live ETA not yet supported for this route");
      stopEtaPolling();
      return;
    }

    const results = await Promise.allSettled(
      viable.map(({ op, url }) =>
        fetchJson(url, { cache: "no-store" })
          .then((raw) => parseEta(op.co, raw).map((e) => ({ ...e, _co: op.co })))
      )
    );

    const successes = results.filter((r2) => r2.status === "fulfilled");
    if (successes.length === 0) {
      state.etaErrorCount += 1;
      const backoff = Math.min(POLL_MS * 2 ** (state.etaErrorCount - 1), MAX_BACKOFF_MS);
      clearInterval(state.etaTimer);
      state.etaTimer = setInterval(pollEta, backoff);
      renderEta([], `Failed to fetch ETA (retry in ${Math.round(backoff / 1000)}s)`);
      return;
    }

    const merged = successes.flatMap((r2) => r2.value);
    const filtered = filterEta(r, state.selectedDirection, merged);
    renderEta(filtered, null);
    if (state.etaErrorCount > 0) {
      state.etaErrorCount = 0;
      clearInterval(state.etaTimer);
      state.etaTimer = setInterval(pollEta, POLL_MS);
    }
  }

  function parseEta(company, raw) {
    if (company === "KMB" || company === "CTB") {
      return (raw.data || []).map((e) => ({
        eta: e.eta,
        dir: e.dir,
        route: e.route,
        dest: e.dest_en || e.dest_tc || "",
        remark: e.rmk_en || e.rmk_tc || "",
        scheduled: isScheduledEntry(e.rmk_en, e.rmk_tc),
      }));
    }
    if (company === "GMB") {
      const data = raw.data;
      if (!data) return [];
      if (data.enabled === false) return [];
      return (data.eta || []).map((e) => ({
        eta: e.timestamp,
        dir: null,
        dest: "",
        remark: e.remarks_en || e.remarks_tc || "",
        scheduled: isScheduledEntry(e.remarks_en, e.remarks_tc),
      }));
    }
    return [];
  }

  function isScheduledEntry(rmkEn, rmkTc) {
    const en = (rmkEn || "").toLowerCase();
    const tc = rmkTc || "";
    return en.includes("scheduled") || tc.includes("原定") || tc.includes("時間表");
  }

  function filterEta(route, direction, etas) {
    if (route.co === "KMB" || route.co === "CTB") {
      const wanted = direction === 1 ? "O" : "I";
      return etas.filter((e) =>
        (!e.dir || e.dir === wanted) &&
        (!e.route || e.route === route.id)
      );
    }
    return etas;
  }

  function renderEta(etas, errorMsg) {
    const list = $("yuu-eta-list");
    const fresh = $("yuu-eta-fresh");
    const now = new Date();
    fresh.textContent = errorMsg ? "" : `Updated ${now.toLocaleTimeString()}`;

    if (errorMsg) {
      list.innerHTML = `<li class="yuu-eta-error">${escapeHtml(errorMsg)}</li>`;
      return;
    }
    const valid = etas
      .filter((e) => e.eta)
      .sort((a, b) => new Date(a.eta) - new Date(b.eta));
    if (valid.length === 0) {
      list.innerHTML = '<li class="yuu-eta-empty">No upcoming buses</li>';
      return;
    }
    list.innerHTML = valid.slice(0, 5).map((e) => {
      const mins = etaMinutes(e.eta);
      const arriving = mins !== null && mins <= 0;
      const cls = arriving ? "yuu-arriving" : (e.scheduled ? "yuu-scheduled" : "yuu-live");
      const badge = e.scheduled ? "⏱" : "⚡";
      const kind = e.scheduled ? "Scheduled" : "Live";
      // Tag each row with the operator when the route is jointly operated.
      const op = (state.selectedRoute.partners && state.selectedRoute.partners.length > 1 && e._co)
        ? `<span class="yuu-eta-op">${escapeHtml(COMPANY_LABEL[e._co] || e._co)}</span>`
        : "";
      return `<li class="yuu-eta-item">
        <span class="yuu-eta-time ${cls}" title="${kind}">${badge} ${escapeHtml(etaText(e.eta))}</span>
        <span class="yuu-eta-dest">${op}${escapeHtml(displayEn(e.dest) || "")}</span>
      </li>`;
    }).join("");
  }

  // --------------------------------------------------------- misc listeners

  function initActivityTracking() {
    ["click", "keydown", "touchstart"].forEach((ev) => {
      document.addEventListener(ev, bumpActivity, { passive: true });
    });
  }

  function initVisibility() {
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && state.selectedStop && !state.etaTimer) {
        startEtaPolling();
      } else if (!document.hidden && state.selectedStop) {
        pollEta();
      }
    });
  }

  // Re-tile the map on orientation change / URL-bar show-hide so the tile
  // grid covers the new viewport without a manual pan.
  function initViewportResize() {
    const resync = () => {
      if (state.map) state.map.invalidateSize();
    };
    window.addEventListener("resize", resync);
    window.addEventListener("orientationchange", () => setTimeout(resync, 120));
    // iOS Safari fires visualViewport.resize when the URL bar shows/hides.
    if (window.visualViewport) {
      window.visualViewport.addEventListener("resize", resync);
    }
  }

  // ------------------------------------------------------------------- boot

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
