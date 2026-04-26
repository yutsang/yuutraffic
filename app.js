/* YuuTraffic static widget — vanilla JS + Leaflet.
   Loads route/stop/geometry data from ./data/ (published by GitHub Actions).
   Fetches live ETA directly from HK gov APIs (all CORS-open). */
(() => {
  "use strict";

  // Page can override where data bundles live by setting window.YUU_DATA_BASE
  // before app.js loads — useful when the same widget is embedded at a path
  // that isn't its data root (e.g. /projects/yuutraffic/ pointing to /yuutraffic/data/).
  const DATA_BASE = (typeof window !== "undefined" && window.YUU_DATA_BASE)
    ? String(window.YUU_DATA_BASE).replace(/\/$/, "")
    : "./data";
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
    // MTR rail uses (line, station) — both come from the geometry stop's
    // mtr_line / mtr_code carried over from the export step.
    MTR: (route, stop) =>
      stop.mtr_line && stop.mtr_code
        ? `https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php?line=${encodeURIComponent(stop.mtr_line)}&sta=${encodeURIComponent(stop.mtr_code)}`
        : null,
  };

  const COMPANY_LABEL = {
    KMB: "KMB / LWB",
    CTB: "Citybus",
    GMB: "Green Minibus",
    MTRB: "MTR Bus",
    RMB: "Red Minibus",
    MTR: "MTR Rail",
  };

  // Top-level tabs map to the set of company codes that show up in search.
  // The Bus tab also accepts a sub-filter via the operator <select>.
  const TAB_COMPANIES = {
    bus: new Set(["KMB", "CTB", "GMB", "MTRB", "RMB"]),
    mtr: new Set(["MTR"]),
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
    userLocation: null,     // {lat, lng} after permission granted
    activeTab: "bus",       // "bus" | "mtr" | "plan"
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

  // Stops typically come back from KMB as "Laguna City Bus Terminus (LT970)"
  // (English) and "麗港城總站 (LT970)" (Chinese). The code at the end is
  // duplicated; strip it from the English when both halves carry it.
  function splitStopLabels(stop) {
    const tcRaw = stop.stop_name_tc || "";
    let en = displayEn(stop.stop_name || stop.stop_id || "");
    const codeRe = /\s*\(([A-Z0-9-]{3,})\)\s*$/i;
    const tcCode = tcRaw.match(codeRe);
    const enCode = en.match(codeRe);
    if (tcCode && enCode && tcCode[1].toUpperCase() === enCode[1].toUpperCase()) {
      en = en.replace(codeRe, "").trim();
    }
    return { tc: tcRaw, en };
  }

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
    initModeFilter();
    initModeTabs();
    initTripPlanner();
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
      (pos) => {
        state.userLocation = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
        };
        computeNearbyRoutes(pos.coords.latitude, pos.coords.longitude)
          .catch((e) => console.warn(e));
      },
      (err) => console.info("Location unavailable:", err.message),
      { enableHighAccuracy: false, timeout: 12_000, maximumAge: 5 * 60_000 }
    );
  }

  // Three tabs:
  //   Bus  → search across KMB/CTB/GMB/MTRB/RMB; operator <select> narrows
  //   MTR  → MTR rail only; operator <select> hidden
  //   Plan → trip planner panel (search input hidden)
  function initModeTabs() {
    document.querySelectorAll(".yuu-tab").forEach((btn) => {
      btn.addEventListener("click", () => activateTab(btn.dataset.tab));
    });
    activateTab("bus");
  }

  function activateTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".yuu-tab").forEach((b) => {
      const on = b.dataset.tab === tab;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });

    const explore = $("yuu-explore-controls");
    const planSec = $("yuu-plan");
    const welcome = $("yuu-welcome");
    const route   = $("yuu-route");
    const sel     = $("yuu-mode-select");

    if (tab === "plan") {
      if (explore) explore.hidden = true;
      if (welcome) welcome.hidden = true;
      if (route)   route.hidden   = true;
      if (planSec) planSec.hidden = false;
      $("yuu-plan-from")?.focus();
      return;
    }

    if (planSec) planSec.hidden = true;
    if (explore) explore.hidden = false;
    // Operator-narrow dropdown only makes sense on the Bus tab.
    if (sel) sel.style.display = (tab === "bus") ? "" : "none";

    // Refresh the visible content depending on whether a route is selected
    // and whether it belongs to the active tab.
    const r = state.selectedRoute;
    const fits = r && (TAB_COMPANIES[tab]?.has(r.co) ||
                       (r.partners && r.partners.some((p) => TAB_COMPANIES[tab]?.has(p.co))));
    if (fits) {
      if (welcome) welcome.hidden = true;
      if (route)   route.hidden   = false;
    } else {
      if (welcome) welcome.hidden = false;
      if (route)   route.hidden   = true;
    }

    // Refresh search dropdown to show only routes matching the new tab.
    const input = $("yuu-search-input");
    if (input) {
      if (input.value.trim()) runSearch(input.value);
      else showNearbySuggestions();
    }
  }

  function initModeFilter() {
    const sel = $("yuu-mode-select");
    if (!sel) return;
    sel.addEventListener("change", () => {
      bumpActivity();
      const input = $("yuu-search-input");
      if (input.value.trim() === "") showNearbySuggestions();
      else runSearch(input.value);
    });
  }

  // ============================================================ Trip Planner
  // MVP: direct routes only (one bus / MTR line from origin → destination).
  // Interchange routing is a follow-up — flagged below.

  function initTripPlanner() {
    const from = $("yuu-plan-from");
    const to = $("yuu-plan-to");
    const swap = $("yuu-plan-swap");
    const go = $("yuu-plan-go");
    if (!from || !to || !go) return;

    setupStopAutocomplete(from, $("yuu-plan-from-suggest"));
    setupStopAutocomplete(to, $("yuu-plan-to-suggest"));

    swap.addEventListener("click", () => {
      const fv = from.value, fid = from.dataset.stopId || "";
      from.value = to.value;
      from.dataset.stopId = to.dataset.stopId || "";
      to.value = fv;
      to.dataset.stopId = fid;
    });

    go.addEventListener("click", async () => {
      const fromId = from.dataset.stopId;
      const toId = to.dataset.stopId;
      if (!fromId || !toId) {
        $("yuu-plan-results").innerHTML =
          `<div class="yuu-plan-empty">Pick a stop from each suggestion list first.</div>`;
        return;
      }
      $("yuu-plan-results").innerHTML = `<div class="yuu-plan-loading">Searching for direct routes…</div>`;
      const trips = await planTrip(fromId, toId);
      renderPlanResults(trips);
    });
  }

  function setupStopAutocomplete(input, suggest) {
    if (!input || !suggest) return;
    let timer = null;
    input.addEventListener("input", () => {
      delete input.dataset.stopId;
      clearTimeout(timer);
      timer = setTimeout(() => searchStops(input.value, suggest, input), 180);
    });
    input.addEventListener("focus", () => {
      if (input.value.trim()) searchStops(input.value, suggest, input);
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".yuu-plan-input-wrap")) suggest.hidden = true;
    });
  }

  async function searchStops(q, suggest, input) {
    const query = (q || "").trim();
    if (query.length < 2) { suggest.hidden = true; return; }
    const stops = await ensureStopsLoaded();
    const lower = query.toLowerCase();
    const matches = [];
    for (const [id, s] of Object.entries(stops)) {
      if (matches.length >= 14) break;
      const ne = (s.ne || "").toLowerCase();
      const nt = s.nt || "";
      if (ne.includes(lower) || nt.includes(query)) {
        matches.push({ id, ...s });
      }
    }
    if (matches.length === 0) {
      suggest.innerHTML = `<div class="yuu-plan-suggest-empty">No matching stops</div>`;
      suggest.hidden = false;
      return;
    }
    suggest.innerHTML = matches.map((m) => {
      const tcRow = m.nt ? `<span class="yuu-plan-suggest-tc">${escapeHtml(m.nt)}</span>` : "";
      const en = displayEn(m.ne || "");
      return `<div class="yuu-plan-suggest-item" data-stop-id="${escapeHtml(m.id)}" data-display="${escapeHtml(m.nt || en)}">
        ${tcRow}
        <span class="yuu-plan-suggest-en">${escapeHtml(en)}</span>
        <span class="yuu-plan-suggest-co">${escapeHtml(m.co || "")}</span>
      </div>`;
    }).join("");
    suggest.hidden = false;
    suggest.querySelectorAll(".yuu-plan-suggest-item").forEach((el) => {
      el.addEventListener("click", () => {
        input.value = el.dataset.display || "";
        input.dataset.stopId = el.dataset.stopId;
        suggest.hidden = true;
      });
    });
  }

  async function planTrip(fromId, toId) {
    const sr = await ensureStopRoutesLoaded();
    const fromRoutes = new Set(sr[fromId] || []);
    const toRoutes = new Set(sr[toId] || []);
    // Direct: routes that serve both stops in the right order
    const directRks = [...fromRoutes].filter((rk) => toRoutes.has(rk));
    const direct = [];
    for (const rk of directRks) {
      const route = state.routes.find((r) => r.rk === rk);
      if (!route) continue;
      for (const d of (route.dirs && route.dirs.length ? route.dirs : [1])) {
        try {
          const geo = await fetchJson(`${DATA_BASE}/geometry/${rk}_${d}.json`);
          const stops = geo.stops || [];
          const fIdx = stops.findIndex((s) => s.stop_id === fromId);
          const tIdx = stops.findIndex((s) => s.stop_id === toId);
          if (fIdx >= 0 && tIdx > fIdx) {
            direct.push({
              route, dir: d,
              fromIdx: fIdx, toIdx: tIdx,
              hops: tIdx - fIdx,
              fromName: stops[fIdx].stop_name_tc || stops[fIdx].stop_name,
              toName: stops[tIdx].stop_name_tc || stops[tIdx].stop_name,
            });
          }
        } catch (e) { /* missing geometry: skip */ }
      }
    }
    // Sort: fewest hops first, then natural by route id
    direct.sort((a, b) =>
      a.hops - b.hops || compareRouteIds(a.route.id, b.route.id)
    );
    return { direct };
  }

  function renderPlanResults(trips) {
    const el = $("yuu-plan-results");
    if (!trips.direct.length) {
      el.innerHTML =
        `<div class="yuu-plan-empty">No direct route between these stops. ` +
        `<small>Interchange routing is on the way — for now try picking stops on the same bus or MTR line.</small></div>`;
      return;
    }
    el.innerHTML = `<div class="yuu-plan-section-title">${trips.direct.length} direct route${trips.direct.length === 1 ? "" : "s"}</div>` +
      trips.direct.map((t) => {
        const rc = routeColor(t.route);
        const opName = COMPANY_LABEL[t.route.co] || t.route.co;
        const dirLabel = (t.dir === 1 ? t.route.de : t.route.oe) || "";
        return `<div class="yuu-plan-card">
          <div class="yuu-plan-card-head" style="--card-color:${rc}">
            <span class="yuu-badge ${t.route.co}" style="background:${rc};color:#fff">${escapeHtml(t.route.id)}</span>
            <div class="yuu-plan-card-meta">
              <span class="yuu-plan-card-co">${escapeHtml(opName)}</span>
              <span class="yuu-plan-card-direction">→ ${escapeHtml(displayEn(dirLabel))}</span>
            </div>
            <span class="yuu-plan-card-hops">${t.hops} stop${t.hops === 1 ? "" : "s"}</span>
          </div>
          <div class="yuu-plan-card-body">
            <span class="yuu-plan-card-leg">${escapeHtml(t.fromName || "")} → ${escapeHtml(t.toName || "")}</span>
            <button type="button" class="yuu-plan-open" data-rk="${escapeHtml(t.route.rk)}" data-dir="${t.dir}">View →</button>
          </div>
        </div>`;
      }).join("");
    el.querySelectorAll(".yuu-plan-open").forEach((btn) => {
      btn.addEventListener("click", () => {
        const route = state.routes.find((r) => r.rk === btn.dataset.rk);
        if (!route) return;
        // Switch back to the matching tab (Bus or MTR) before selecting.
        activateTab(route.co === "MTR" ? "mtr" : "bus");
        state.selectedDirection = Number(btn.dataset.dir) || 1;
        selectRoute(route);
      });
    });
  }

  function passesModeFilter(route) {
    // Top-level tab gate first: route must belong to the active tab's mode.
    const tab = state.activeTab || "bus";
    const tabSet = TAB_COMPANIES[tab];
    if (tabSet) {
      const inTab = tabSet.has(route.co) ||
        (route.partners && route.partners.some((p) => tabSet.has(p.co)));
      if (!inTab) return false;
    }
    // Bus-tab sub-filter via operator <select>: empty = any operator inside
    // the tab's set; specific = only that operator.
    if (tab === "bus") {
      const op = $("yuu-mode-select")?.value || "";
      if (!op) return true;
      if (route.co === op) return true;
      if (route.partners && route.partners.some((p) => p.co === op)) return true;
      return false;
    }
    return true;
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
      if (!passesModeFilter(r)) continue;
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

    // For each candidate route, remember the distance to its closest nearby
    // stop. This becomes the primary sort key.
    const routeMinDist = new Map();
    for (const n of topStops) {
      for (const rk of (stopRoutes[n.stopId] || [])) {
        const prev = routeMinDist.get(rk);
        if (prev === undefined || prev > n.d) routeMinDist.set(rk, n.d);
      }
    }

    const routes = state.routes
      .filter((r) => routeMinDist.has(r.rk))
      .sort((a, b) => {
        const dA = routeMinDist.get(a.rk) ?? Infinity;
        const dB = routeMinDist.get(b.rk) ?? Infinity;
        // Bucket distances in 50 m increments so routes at "the same stop"
        // get the secondary natural sort by route id.
        const bucketA = Math.floor(dA / 50);
        const bucketB = Math.floor(dB / 50);
        if (bucketA !== bucketB) return bucketA - bucketB;
        return compareRouteIds(a.id, b.id);
      });

    state.nearbyRoutes = {
      routes,
      stopCount: topStops.length,
      radiusM: NEAR_ME_RADIUS_M,
    };

    const input = $("yuu-search-input");
    if (input === document.activeElement && input.value.trim() === "") {
      showNearbySuggestions();
    }
  }

  function showNearbySuggestions() {
    const n = state.nearbyRoutes;
    if (!n) {
      $("yuu-search-results").hidden = true;
      return;
    }
    const filtered = n.routes.filter(passesModeFilter);
    if (filtered.length === 0) {
      $("yuu-search-results").hidden = true;
      return;
    }
    renderSearchResults(
      filtered,
      `Near you (${n.radiusM} m · ${n.stopCount} stops)`
    );
  }

  // ------------------------------------------------------------- route panel

  async function selectRoute(route) {
    bumpActivity();
    // Auto-switch to the matching tab so the user doesn't have to flip
    // between Bus and MTR manually when picking a route from search.
    if (route.co === "MTR" && state.activeTab !== "mtr") activateTab("mtr");
    else if (route.co !== "MTR" && state.activeTab === "mtr") activateTab("bus");

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
    } else if (route.co === "MTR" && MTR_LINE_COLOR[route.id]) {
      // MTR lines have their own brand colours — pick the line's hue.
      const c = MTR_LINE_COLOR[route.id];
      yuu.dataset.joint = "false";
      yuu.style.setProperty("--yuu-route-color", c);
      yuu.style.setProperty("--yuu-route-color-soft", withAlpha(c, 0.18));
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

    renderRouteChips(route);
    updateRouteTitle();
    await loadDirection({ autoFlip: true });
  }

  // The chip toolbar shown in the route header: operator name, schedule
  // hint chips, an optional "approximate route" chip, and the direction
  // toggles — all inline so they share a row instead of stacking.
  function renderRouteChips(route) {
    const host = $("yuu-route-chips");
    if (!host) return;

    const opNames = (route.partners && route.partners.length > 1)
      ? route.partners.map((p) => COMPANY_LABEL[p.co] || p.co).join(" + ")
      : (COMPANY_LABEL[route.co] || route.co);

    const badges = scheduleBadges(route.id);
    const allApprox = (route.partners && route.partners.length > 0
                        ? route.partners
                        : [{ co: route.co }])
                      .every((p) => APPROXIMATE_OPERATORS.has(p.co));
    const dirs = route.dirs && route.dirs.length ? route.dirs : [1];

    const dirLabel = (d) => {
      const r = state.selectedRoute;
      if (!r) return d === 1 ? "Out" : "In";
      const outName = d === 1 ? r.de : r.oe;
      const trim = (s) => (s || "").split(/[(]|·|,/)[0].trim().slice(0, 14);
      return `→ ${trim(outName) || (d === 1 ? "Out" : "In")}`;
    };

    const parts = [];
    parts.push(`<span class="yuu-op-text">${escapeHtml(opNames)}</span>`);
    badges.forEach((b) => {
      parts.push(`<span class="yuu-schedule-chip">${escapeHtml(b.en)} · ${escapeHtml(b.tc)}</span>`);
    });
    if (allApprox) {
      parts.push(`<span class="yuu-schedule-chip yuu-approx-chip" title="Coordinates are best-effort">Approximate · 路線僅供參考</span>`);
    }
    dirs.forEach((d) => {
      const active = d === state.selectedDirection ? " active" : "";
      parts.push(
        `<button type="button" class="yuu-dir-chip${active}" data-dir="${d}">${escapeHtml(dirLabel(d))}</button>`
      );
    });
    host.innerHTML = parts.join("");

    host.querySelectorAll(".yuu-dir-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        bumpActivity();
        const d = Number(btn.dataset.dir);
        if (!state.selectedRoute || d === state.selectedDirection) return;
        state.selectedDirection = d;
        state.selectedStop = null;
        $("yuu-eta").hidden = true;
        stopEtaPolling();
        renderRouteChips(state.selectedRoute); // re-mark active
        updateRouteTitle();
        loadDirection({ autoFlip: false });
      });
    });
  }

  // Empty stub kept for backward compat (init flow used to call this).
  function initDirectionToggle() {}

  // After a route's geometry is loaded, see whether the user is actually
  // closer to the OTHER direction's origin (= this direction's destination).
  // Returns true if a flip happened (caller should bail since loadDirection
  // re-runs with the new direction).
  async function maybeSmartFlipDirection(route) {
    if (!state.userLocation) return false;
    if (!route?.dirs || route.dirs.length < 2) return false;
    const stops = state.geometry?.stops;
    if (!stops || stops.length < 2) return false;
    const first = stops[0];
    const last = stops[stops.length - 1];
    if (typeof first.lat !== "number" || typeof last.lat !== "number") return false;

    const u = state.userLocation;
    const dFirst = distanceM(u.lat, u.lng, first.lat, first.lng);
    const dLast = distanceM(u.lat, u.lng, last.lat, last.lng);
    // Only flip if the other end is meaningfully closer (avoids ping-pong
    // when user is roughly equidistant). 200 m of margin.
    if (dLast + 200 >= dFirst) return false;

    const otherDir = state.selectedDirection === 1 ? 2 : 1;
    if (!route.dirs.includes(otherDir)) return false;

    state.selectedDirection = otherDir;
    if (state.selectedRoute) renderRouteChips(state.selectedRoute);
    updateRouteTitle();
    await loadDirection({ autoFlip: false });
    return true;
  }

  // Picks a default stop for the freshly-loaded route so the ETA panel isn't
  // empty. Prefers the stop closest to the user's location; otherwise falls
  // back to stop 1.
  // Move the ETA card inline (right after the selected stop row) on mobile,
  // back to its home in the stops-pane on desktop. Re-running renderStops
  // wipes the row, so we always restore the home parent before re-rendering.
  function placeEtaForRow(row) {
    const eta = $("yuu-eta");
    if (!eta) return;
    const home = document.querySelector(".yuu-stops-pane");
    const isMobile = window.matchMedia("(max-width: 768px)").matches;
    if (isMobile && row) {
      row.insertAdjacentElement("afterend", eta);
    } else if (home && eta.parentElement !== home) {
      home.appendChild(eta);
    }
  }

  function returnEtaHome() {
    const eta = $("yuu-eta");
    const home = document.querySelector(".yuu-stops-pane");
    if (eta && home && eta.parentElement !== home) home.appendChild(eta);
  }

  function autoSelectDefaultStop() {
    const stops = state.geometry?.stops;
    if (!stops || stops.length === 0) return;
    if (state.selectedStop) return;
    let chosen = null;
    if (state.userLocation) {
      const u = state.userLocation;
      let best = Infinity;
      for (const s of stops) {
        if (typeof s.lat !== "number" || typeof s.lng !== "number") continue;
        const d = distanceM(u.lat, u.lng, s.lat, s.lng);
        if (d < best) { best = d; chosen = s; }
      }
    }
    if (!chosen) chosen = stops[0];
    if (chosen) selectStop(chosen);
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

  async function loadDirection({ autoFlip = false } = {}) {
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

      // Smart-default direction: if the user is closer to the OTHER end of
      // the route than this direction's origin, flip. Only on initial load
      // of the route (autoFlip=true), not on a manual direction-button tap.
      if (autoFlip && (await maybeSmartFlipDirection(r))) {
        return; // recursive load already ran with the flipped direction
      }
      autoSelectDefaultStop();
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
      MTR: "#1d3557",  // generic; per-line override below
    })[co] || "#00338d";
  }

  // Each MTR rail line has its own brand colour. Used for the route polyline
  // and the route badge when a single line is selected.
  const MTR_LINE_COLOR = {
    AEL: "#00888a",  // Airport Express turquoise
    TCL: "#f7943e",  // Tung Chung orange
    TWL: "#e2231a",  // Tsuen Wan red
    ISL: "#0075c2",  // Island blue
    KTL: "#00a040",  // Kwun Tong green
    TKL: "#7e3c93",  // Tseung Kwan O purple
    EAL: "#5eb6e4",  // East Rail light blue
    TML: "#923011",  // Tuen Ma brown
    SIL: "#bac429",  // South Island lime-olive
    DRL: "#f173ac",  // Disneyland pink
  };

  function routeColor(route) {
    if (!route) return "#00338d";
    if (route.co === "MTR" && MTR_LINE_COLOR[route.id]) return MTR_LINE_COLOR[route.id];
    return companyColor(route.co);
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
      : routeColor(route);

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
      const labels = splitStopLabels(s);
      const tip = labels.tc
        ? `${s.sequence}. ${labels.en} · ${labels.tc}`
        : `${s.sequence}. ${labels.en}`;
      marker.bindTooltip(tip);
      marker.on("click", () => selectStop(s));
      state.stopLayers.push(marker);
    });

    if (state.routeLayer) {
      state.map.fitBounds(state.routeLayer.getBounds(), { padding: [30, 30] });
    }
  }

  // ------------------------------------------------------------------ stops

  function renderStops(geo) {
    // The ETA card might have been moved INTO a stop row on mobile; pull it
    // back to the stops-pane before we wipe stops.innerHTML or it gets lost.
    returnEtaHome();
    const el = $("yuu-stops");
    const stops = geo.stops || [];
    if (stops.length === 0) {
      el.innerHTML = '<div class="yuu-search-empty">No stops listed</div>';
      return;
    }
    el.innerHTML = stops.map((s) => {
      const labels = splitStopLabels(s);
      const tcRow = labels.tc
        ? `<span class="yuu-stop-name-tc">${escapeHtml(labels.tc)}</span>`
        : "";
      return `<div class="yuu-stop-item" data-stop-id="${escapeHtml(s.stop_id)}" data-seq="${s.sequence}">
        <span class="yuu-stop-seq">${s.sequence}</span>
        <div class="yuu-stop-labels">
          ${tcRow}
          <span class="yuu-stop-name">${escapeHtml(labels.en)}</span>
        </div>
      </div>`;
    }).join("");

    el.querySelectorAll(".yuu-stop-item").forEach((node) => {
      node.addEventListener("click", () => {
        // Circular routes have identical stop_id at seq=1 and seq=last;
        // distinguish by sequence so tapping stop 1 vs stop N behaves
        // independently.
        const stopId = node.dataset.stopId;
        const seq = Number(node.dataset.seq);
        const stop = stops.find(
          (x) => x.stop_id === stopId && x.sequence === seq
        ) || stops.find((x) => x.stop_id === stopId);
        if (stop) selectStop(stop);
      });
    });
  }

  function selectStop(stop) {
    bumpActivity();
    // Allow re-clicking the already-selected stop to force a manual refresh.
    const sameStop = state.selectedStop &&
      state.selectedStop.stop_id === stop.stop_id &&
      state.selectedStop.sequence === stop.sequence;
    state.selectedStop = stop;

    // Match on both stop_id AND sequence so circular routes don't light up
    // two rows (seq=1 and seq=N) when only one is selected.
    document.querySelectorAll(".yuu-stop-item").forEach((n) =>
      n.classList.toggle("active",
        n.dataset.stopId === stop.stop_id &&
        Number(n.dataset.seq) === stop.sequence)
    );

    $("yuu-eta").hidden = false;
    {
      const labels = splitStopLabels(stop);
      $("yuu-eta-stop").innerHTML =
        `${stop.sequence}. ${escapeHtml(labels.tc || labels.en)}` +
        (labels.tc ? ` <span class="yuu-eta-stop-tc">${escapeHtml(labels.en)}</span>` : "");
    }
    if (!sameStop) {
      $("yuu-eta-list").innerHTML = '<li class="yuu-eta-empty">Loading…</li>';
      $("yuu-eta-fresh").textContent = "";
    }

    if (state.selectedStopLayer) state.map.removeLayer(state.selectedStopLayer);
    const color = routeColor(state.selectedRoute);
    if (typeof stop.lat === "number" && typeof stop.lng === "number") {
      state.selectedStopLayer = L.circleMarker([stop.lat, stop.lng], {
        radius: 10, fillColor: color,
        color: "#ffffff", weight: 4, fillOpacity: 1,
      }).addTo(state.map);
      const labels = splitStopLabels(stop);
      state.selectedStopLayer
        .bindPopup(
          `<div class="yuu-map-popup"><strong>${escapeHtml(labels.tc || labels.en)}</strong>` +
          (labels.tc ? `<div class="yuu-map-popup-en">${escapeHtml(labels.en)}</div>` : "") +
          `<ol class="yuu-map-popup-eta"><li class="yuu-eta-empty">Loading…</li></ol></div>`,
          { maxWidth: 240, className: "yuu-popup-wrap" }
        )
        .openPopup();
    }

    startEtaPolling();

    // On mobile, render the ETA card inline immediately after the selected
    // stop row so the live information sits next to its stop in the list.
    const row = document.querySelector(
      `.yuu-stop-item[data-stop-id="${CSS.escape(stop.stop_id)}"][data-seq="${stop.sequence}"]`
    );
    placeEtaForRow(row);
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
    const filtered = filterEta(r, state.selectedDirection, s, merged);
    renderEta(filtered, null);
    if (state.etaErrorCount > 0) {
      state.etaErrorCount = 0;
      clearInterval(state.etaTimer);
      state.etaTimer = setInterval(pollEta, POLL_MS);
    }
  }

  function parseEta(company, raw) {
    if (company === "MTR") {
      // Response shape: data["{LINE}-{STATION}"] = { UP: [...], DOWN: [...] }
      // Each entry has time (ISO with timezone), dest (3-letter station code),
      // plat (platform), ttnt (minutes), valid ("Y"/"N").
      const data = raw.data || {};
      const out = [];
      for (const v of Object.values(data)) {
        if (!v || typeof v !== "object") continue;
        for (const dirKey of ["UP", "DOWN"]) {
          for (const e of (v[dirKey] || [])) {
            if (!e || e.valid === "N") continue;
            // MTR returns local HKT without TZ; pin it explicitly so
            // browsers in other zones don't misinterpret.
            const iso = e.time ? e.time.replace(" ", "T") + "+08:00" : null;
            out.push({
              eta: iso,
              dir: dirKey === "UP" ? "U" : "D",
              dest: e.dest,
              plat: e.plat,
              scheduled: false,
            });
          }
        }
      }
      return out;
    }
    if (company === "KMB" || company === "CTB") {
      return (raw.data || []).map((e) => ({
        eta: e.eta,
        dir: e.dir,
        route: e.route,
        seq: e.seq != null ? Number(e.seq) : null,
        st:  e.service_type != null ? Number(e.service_type) : null,
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
        seq: null,
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

  function filterEta(route, direction, stop, etas) {
    if (route.co === "MTR") {
      // MTR direction codes: U = up, D = down. Outbound (1) maps to U.
      const wanted = direction === 1 ? "U" : "D";
      return etas.filter((e) => !e.dir || e.dir === wanted);
    }
    if (route.co === "KMB" || route.co === "CTB") {
      const wantedDir = direction === 1 ? "O" : "I";
      const wantedSeq = stop?.sequence ?? null;
      const wantedSt = route.st ?? null;
      return etas.filter((e) => {
        if (e.dir && e.dir !== wantedDir) return false;
        if (e.route && e.route !== route.id) return false;
        // Service-type filter: when an entry carries service_type, only keep
        // the one matching the variant the user picked.
        if (wantedSt != null && e.st != null && e.st !== wantedSt) return false;
        // Seq filter: disambiguates circular-route terminus where the same
        // stop_id serves seq=1 (departing) AND seq=N (arriving). Without this
        // the ETA list mixes both semantics.
        if (wantedSeq != null && e.seq != null && e.seq !== wantedSeq) return false;
        return true;
      });
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
      const op = (state.selectedRoute.partners && state.selectedRoute.partners.length > 1 && e._co)
        ? `<span class="yuu-eta-op">${escapeHtml(COMPANY_LABEL[e._co] || e._co)}</span>`
        : "";
      return `<li class="yuu-eta-item">
        <span class="yuu-eta-time ${cls}" title="${kind}">${badge} ${escapeHtml(etaText(e.eta))}</span>
        <span class="yuu-eta-dest">${op}${escapeHtml(displayEn(e.dest) || "")}</span>
      </li>`;
    }).join("");

    // Mirror the top entries into the map marker's popup so users tapping
    // a stop on the map see the live ETA right there.
    updateMarkerPopup(valid);
  }

  function updateMarkerPopup(etas) {
    if (!state.selectedStopLayer) return;
    const popup = state.selectedStopLayer.getPopup();
    if (!popup) return;
    const root = popup.getElement();
    if (!root) return;
    const ol = root.querySelector(".yuu-map-popup-eta");
    if (!ol) return;
    if (!etas || etas.length === 0) {
      ol.innerHTML = `<li class="yuu-eta-empty">No upcoming buses</li>`;
      return;
    }
    ol.innerHTML = etas.slice(0, 3).map((e) => {
      const mins = etaMinutes(e.eta);
      const arriving = mins !== null && mins <= 0;
      const cls = arriving ? "yuu-arriving" : (e.scheduled ? "yuu-scheduled" : "yuu-live");
      const badge = e.scheduled ? "⏱" : "⚡";
      return `<li><span class="yuu-eta-time ${cls}">${badge} ${escapeHtml(etaText(e.eta))}</span></li>`;
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
      // Re-place the ETA card so mobile↔desktop transitions land it
      // either inline next to the selected stop or back in the side column.
      if (state.selectedStop) {
        const row = document.querySelector(
          `.yuu-stop-item[data-stop-id="${CSS.escape(state.selectedStop.stop_id)}"][data-seq="${state.selectedStop.sequence}"]`
        );
        placeEtaForRow(row);
      }
    };
    window.addEventListener("resize", resync);
    window.addEventListener("orientationchange", () => setTimeout(resync, 120));
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
