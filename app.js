/* YuuTraffic static widget — vanilla JS + Leaflet.
   Loads route/stop/geometry data from ./data/ (published by GitHub Actions).
   Fetches live ETA directly from HK gov APIs (all CORS-open). */
(() => {
  "use strict";

  const DATA_BASE = "./data";
  const POLL_MS = 20_000;
  const MAX_BACKOFF_MS = 120_000;
  const IDLE_STOP_MS = 10 * 60_000; // stop polling after 10 min of inactivity

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

  const state = {
    routes: [],
    stops: {},
    meta: null,
    selectedRoute: null,
    selectedDirection: 1,
    selectedStop: null,
    geometry: null,
    map: null,
    routeLayer: null,
    stopLayers: [],
    selectedStopLayer: null,
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

  // -------------------------------------------------------------------- init

  async function init() {
    applyEmbedMode();
    // Map can render before any data arrives — blank base layer shows instantly.
    initMap();
    initSearch();
    initDirectionToggle();
    initActivityTracking();
    initVisibility();
    $("yuu-meta").textContent = "Loading routes…";

    // Only routes.json + meta.json are needed for search / welcome.
    // stops.json is deferred — Phase 1 doesn't use it (geometry files carry
    // per-route stop coords). Trip Planner / MTR routing will load it lazily.
    try {
      const [routes, meta] = await Promise.all([
        fetchJson(`${DATA_BASE}/routes.json`),
        fetchJson(`${DATA_BASE}/meta.json`),
      ]);
      state.routes = routes;
      state.meta = meta;
      renderMeta();
    } catch (err) {
      console.error("Failed to load bundles", err);
      $("yuu-meta").textContent =
        "Failed to load transport data. The build may not have run yet.";
    }
  }

  function applyEmbedMode() {
    const params = new URLSearchParams(location.search);
    if (params.get("embed") === "1" || params.has("embed")) {
      document.documentElement.classList.add("yuu-embedded");
    }
  }

  async function ensureStopsLoaded() {
    if (state.stops && Object.keys(state.stops).length > 0) return state.stops;
    state.stops = await fetchJson(`${DATA_BASE}/stops.json`);
    return state.stops;
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
      `${c.routes || state.routes.length} routes · ${c.stops || Object.keys(state.stops).length} stops · refreshed ${date}`;
  }

  // ------------------------------------------------------------------ search

  function initSearch() {
    const input = $("yuu-search-input");
    const results = $("yuu-search-results");

    input.addEventListener("input", () => {
      bumpActivity();
      runSearch(input.value);
    });

    input.addEventListener("focus", () => {
      if (input.value.trim()) runSearch(input.value);
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

    const matches = state.routes
      .filter((r) => {
        const id = (r.id || "").toUpperCase();
        if (id === query) return true;
        if (id.startsWith(query)) return true;
        if (id.includes(query)) return true;
        if ((r.oe || "").toUpperCase().includes(query)) return true;
        if ((r.de || "").toUpperCase().includes(query)) return true;
        if ((r.ot || "").includes(q)) return true;
        if ((r.dt || "").includes(q)) return true;
        return false;
      })
      .slice(0, 25);

    if (matches.length === 0) {
      results.innerHTML = '<div class="yuu-search-empty">No matching routes</div>';
      results.hidden = false;
      return;
    }

    results.innerHTML = matches
      .map((r) => `
        <div class="yuu-search-result" data-rk="${escapeHtml(r.rk)}">
          <span class="yuu-badge ${r.co}">${escapeHtml(r.id)}</span>
          <span>${escapeHtml(r.oe)} ↔ ${escapeHtml(r.de)}</span>
        </div>`)
      .join("");
    results.hidden = false;

    results.querySelectorAll(".yuu-search-result[data-rk]").forEach((node) => {
      node.addEventListener("click", () => {
        const route = state.routes.find((r) => r.rk === node.dataset.rk);
        if (route) selectRoute(route);
      });
    });
  }

  // ------------------------------------------------------------- route panel

  async function selectRoute(route) {
    bumpActivity();
    state.selectedRoute = route;
    state.selectedStop = null;
    state.selectedDirection = (route.dirs && route.dirs[0]) || 1;

    $("yuu-search-input").value = route.id;
    $("yuu-search-results").hidden = true;
    $("yuu-welcome").hidden = true;
    $("yuu-route").hidden = false;
    $("yuu-eta").hidden = true;
    stopEtaPolling();

    // Section visibility may change available map width on mobile; poke
    // Leaflet so it recomputes tile grid.
    if (state.map) setTimeout(() => state.map.invalidateSize(), 0);

    const badge = $("yuu-route-badge");
    badge.textContent = route.id;
    badge.className = `yuu-badge ${route.co}`;

    // Direction button visibility
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

  async function loadDirection() {
    const r = state.selectedRoute;
    const d = state.selectedDirection;
    if (!r) return;
    const url = `${DATA_BASE}/geometry/${r.rk}_${d}.json`;

    try {
      const geo = await fetchJson(url);
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
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      maxZoom: 19,
      subdomains: "abcd",
    }).addTo(state.map);
  }

  function renderRouteOnMap(geo) {
    if (state.routeLayer) {
      state.map.removeLayer(state.routeLayer);
      state.routeLayer = null;
    }
    state.stopLayers.forEach((l) => state.map.removeLayer(l));
    state.stopLayers = [];
    if (state.selectedStopLayer) {
      state.map.removeLayer(state.selectedStopLayer);
      state.selectedStopLayer = null;
    }

    const coords = Array.isArray(geo.coords) ? geo.coords : [];
    if (coords.length > 1) {
      state.routeLayer = L.polyline(coords, {
        color: "#e63946", weight: 4, opacity: 0.85,
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
        radius: 5, fillColor: "#e63946",
        color: "#ffffff", weight: 2, fillOpacity: 1,
      }).addTo(state.map);
      marker.bindTooltip(`${s.sequence}. ${s.stop_name || s.stop_name_tc || s.stop_id}`);
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
    el.innerHTML = stops
      .map((s) => `
        <div class="yuu-stop-item" data-stop-id="${escapeHtml(s.stop_id)}" data-seq="${s.sequence}">
          <span class="yuu-stop-seq">${s.sequence}</span>
          <span class="yuu-stop-name">${escapeHtml(s.stop_name || s.stop_name_tc || s.stop_id)}</span>
        </div>`)
      .join("");

    el.querySelectorAll(".yuu-stop-item").forEach((node) => {
      node.addEventListener("click", () => {
        const stop = stops.find((x) => x.stop_id === node.dataset.stopId);
        if (stop) selectStop(stop);
      });
    });
  }

  function selectStop(stop) {
    bumpActivity();
    state.selectedStop = stop;

    document.querySelectorAll(".yuu-stop-item").forEach((n) =>
      n.classList.toggle("active", n.dataset.stopId === stop.stop_id)
    );

    $("yuu-eta").hidden = false;
    $("yuu-eta-stop").textContent =
      `${stop.sequence}. ${stop.stop_name || stop.stop_name_tc || stop.stop_id}`;
    $("yuu-eta-list").innerHTML = '<li class="yuu-eta-empty">Loading…</li>';
    $("yuu-eta-fresh").textContent = "";

    if (state.selectedStopLayer) state.map.removeLayer(state.selectedStopLayer);
    if (typeof stop.lat === "number" && typeof stop.lng === "number") {
      state.selectedStopLayer = L.circleMarker([stop.lat, stop.lng], {
        radius: 9, fillColor: "#ffd23f",
        color: "#e63946", weight: 3, fillOpacity: 1,
      }).addTo(state.map);
      state.map.setView([stop.lat, stop.lng], 16, { animate: true });
    }

    startEtaPolling();
    // Scroll stop row into view in the list
    const row = document.querySelector(`.yuu-stop-item[data-stop-id="${CSS.escape(stop.stop_id)}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // ---------------------------------------------------------------- ETA poll

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

    const buildUrl = ETA_PROVIDERS[r.co];
    if (!buildUrl) {
      renderEta([], `Live ETA not yet supported for ${r.co}`);
      stopEtaPolling();
      return;
    }
    const url = buildUrl(r, s);
    if (!url) {
      renderEta([], "Missing provider identifier for this route");
      stopEtaPolling();
      return;
    }

    try {
      const raw = await fetchJson(url, { cache: "no-store" });
      const parsed = parseEta(r.co, raw);
      const filtered = filterEta(r, state.selectedDirection, parsed);
      renderEta(filtered, null);
      if (state.etaErrorCount > 0) {
        state.etaErrorCount = 0;
        clearInterval(state.etaTimer);
        state.etaTimer = setInterval(pollEta, POLL_MS);
      }
    } catch (err) {
      console.error("ETA fetch failed", err);
      state.etaErrorCount += 1;
      const backoff = Math.min(POLL_MS * 2 ** (state.etaErrorCount - 1), MAX_BACKOFF_MS);
      clearInterval(state.etaTimer);
      state.etaTimer = setInterval(pollEta, backoff);
      renderEta([], `Failed to fetch ETA (retry in ${Math.round(backoff / 1000)}s)`);
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
      const enabled = data.enabled !== false;
      if (!enabled) return [];
      return (data.eta || []).map((e) => ({
        eta: e.timestamp,
        dir: null,
        dest: "",
        remark: e.remarks_en || e.remarks_tc || "",
        // GMB marks each entry explicitly; fall back to remark heuristic.
        scheduled: e.diff_in_seconds == null && e.scheduled === true
          ? true
          : isScheduledEntry(e.remarks_en, e.remarks_tc),
      }));
    }
    return [];
  }

  // KMB marks schedule-based entries with rmk_en: "Scheduled Bus"
  // (rmk_tc: "原定班次"). CTB is typically empty on real-time entries.
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
      list.innerHTML = '<li class="yuu-eta-empty">No upcoming buses in the schedule</li>';
      return;
    }
    list.innerHTML = valid.slice(0, 5).map((e) => {
      const mins = etaMinutes(e.eta);
      const arriving = mins !== null && mins <= 0;
      const cls = arriving ? "yuu-arriving" : (e.scheduled ? "yuu-scheduled" : "yuu-live");
      const badge = e.scheduled ? "⏱" : "⚡";
      return `<li class="yuu-eta-item">
        <span class="yuu-eta-time ${cls}">${badge} ${escapeHtml(etaText(e.eta))}</span>
        <span class="yuu-eta-dest">${escapeHtml(e.dest || "")}</span>
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

  // ------------------------------------------------------------------- boot

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
