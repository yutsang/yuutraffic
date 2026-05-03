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
    KMB:  "KMB / LWB",
    CTB:  "Citybus",
    GMB:  "Green Minibus",
    MTRB: "MTR Bus",
    RMB:  "Red Minibus",
    MTR:  "MTR Rail",
    MOB:  "Macau Bus",
    LRT:  "Macau LRT",
    MOSC: "Casino Shuttle",
  };

  // Top-level tabs map to the set of company codes that show up in search.
  // The Bus tab also accepts a sub-filter via the operator <select>.
  const TAB_COMPANIES = {
    bus:     new Set(["KMB", "CTB", "GMB", "MTRB", "RMB"]),
    mtr:     new Set(["MTR"]),
    mobus:   new Set(["MOB"]),
    lrt:     new Set(["LRT"]),
    shuttle: new Set(["MOSC"]),
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
    lastEtaUpdateAt: 0,     // ms timestamp of most recent successful ETA poll
    freshTickTimer: null,   // updates the "n seconds ago" label
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
  // (English) and "麗港城總站 (LT970)" (Chinese). User wants TC clean on row 1
  // and the stop-id code attached to the EN row 2 — so strip from TC, keep
  // on EN when both halves carry the same code.
  function splitStopLabels(stop) {
    let tc = stop.stop_name_tc || "";
    const en = displayEn(stop.stop_name || stop.stop_id || "");
    const codeRe = /\s*\(([A-Z0-9-]{3,})\)\s*$/i;
    const tcCode = tc.match(codeRe);
    const enCode = en.match(codeRe);
    if (tcCode && enCode && tcCode[1].toUpperCase() === enCode[1].toUpperCase()) {
      tc = tc.replace(codeRe, "").trim();
    }
    return { tc, en };
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

  // ============================================================ Shuttle view
  // 財車 hub-first flow. The user picks a transit hub (Border Gate, OHFT,
  // TFT, Airport, HZMB) and we list every casino shuttle that touches it
  // — sorted by next departure. Picking a row drills into the standard
  // route view (state.selectedRoute = …) so the user sees the polyline +
  // schedule chips on the main map.

  let shuttleWired = false;
  let activeShuttleHub = null;
  let shuttleMap = null;
  let shuttleMapLayer = null;
  function ensureShuttleViewWired() {
    if (shuttleWired) return;
    shuttleWired = true;
    document.querySelectorAll(".yuu-hub-btn").forEach((btn) => {
      btn.addEventListener("click", () => selectShuttleHub(btn.dataset.hub, btn.dataset.stop));
    });
  }

  function ensureShuttleMapRendered() {
    if (shuttleMap) {
      setTimeout(() => shuttleMap.invalidateSize(), 0);
      return;
    }
    const el = document.getElementById("yuu-shuttle-map");
    if (!el) return;
    // Skip on mobile — CSS hides the container so Leaflet would init
    // into a 0×0 div, which spams console warnings.
    if (el.offsetWidth === 0 || el.offsetHeight === 0) return;
    shuttleMap = L.map("yuu-shuttle-map", {
      zoomControl: true,
      maxBounds: MO_TIGHT_BOUNDS,
      maxBoundsViscosity: 0.85,
      minZoom: 11,
    }).fitBounds(MO_TIGHT_BOUNDS);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; OSM &copy; CARTO',
      subdomains: "abcd",
      maxZoom: 19,
      minZoom: 11,
      bounds: MO_TIGHT_BOUNDS,
    }).addTo(shuttleMap);
  }

  // Plot the hub + every casino reachable from it, with the shuttle
  // polyline (road-routed) drawn between them. Called whenever the user
  // picks a hub button.
  async function renderShuttleHubMap(hubCode, hubStopId, routes) {
    ensureShuttleMapRendered();
    if (!shuttleMap) return;
    if (shuttleMapLayer) shuttleMapLayer.clearLayers();
    else shuttleMapLayer = L.layerGroup().addTo(shuttleMap);

    const stops = await ensureStopsLoaded();
    const hubStop = stops[hubStopId];
    if (!hubStop) return;

    // Hub marker — bigger, dark, distinct from casino dots.
    const hub = L.marker([hubStop.la, hubStop.lg], {
      title: hubStop.nt || hubStop.ne,
    }).bindTooltip(`${hubStop.nt || ""} · ${hubStop.ne || ""}`, { permanent: false });
    hub.addTo(shuttleMapLayer);

    const points = [[hubStop.la, hubStop.lg]];

    // Each shuttle: load the prebuilt polyline, draw it in the casino's
    // brand colour, plus a marker at the casino end.
    await Promise.all(routes.map(async (r) => {
      try {
        const geo = await fetchJson(`${DATA_BASE}/geometry/${r.rk}_1.json`);
        const coords = (geo.coords || []).filter((p) => Array.isArray(p) && typeof p[0] === "number");
        if (coords.length >= 2) {
          L.polyline(coords, {
            color: r.color || "#a89060",
            weight: 4, opacity: 0.85,
            dashArray: "6 4",
          }).bindTooltip(`${r.casino || ""} ↔ ${hubStop.nt || hubStop.ne}`, { sticky: true })
            .addTo(shuttleMapLayer);
          coords.forEach((p) => points.push(p));
        }
        // Casino marker = whichever stop on the route ISN'T the hub.
        const otherStopId = (geo.stops || [])
          .map((s) => s.stop_id)
          .find((sid) => sid !== hubStopId);
        const otherStop = otherStopId && stops[otherStopId];
        if (otherStop) {
          L.circleMarker([otherStop.la, otherStop.lg], {
            radius: 7,
            color: r.color || "#a89060",
            fillColor: r.color || "#a89060",
            weight: 2,
            fillOpacity: 0.9,
          }).bindTooltip(`${r.casino || ""} · ${otherStop.nt || otherStop.ne}`)
            .on("click", () => selectRoute(r))
            .addTo(shuttleMapLayer);
          points.push([otherStop.la, otherStop.lg]);
        }
      } catch { /* missing geometry → skip */ }
    }));

    if (points.length > 1) {
      shuttleMap.fitBounds(points, { padding: [40, 40], maxZoom: 14 });
    }
  }

  function selectShuttleHub(hubCode, stopId) {
    activeShuttleHub = hubCode;
    document.querySelectorAll(".yuu-hub-btn").forEach((b) =>
      b.classList.toggle("active", b.dataset.hub === hubCode)
    );
    const host = $("yuu-shuttle-routes");
    if (!host) return;

    // Routes that touch the hub: from === stopId OR to === stopId. We
    // don't have raw from/to ids on the route record, so match by stop
    // name (oe / de == hub name) — every shuttle has the hub on one end.
    const HUB_NAMES = {
      OHFT: ["Outer Harbour Ferry Terminal", "外港客運碼頭"],
      TFT:  ["Taipa Ferry Terminal", "氹仔客運碼頭"],
      BG:   ["Border Gate (Portas Do Cerco)", "關閘"],
      AIR:  ["Macau International Airport", "澳門國際機場"],
      HZMB: ["HZMB Macau Port", "港珠澳大橋澳門口岸"],
    };
    const [hubEn, hubTc] = HUB_NAMES[hubCode] || [];
    const matches = (state.routes || []).filter((r) => {
      if (r.co !== "MOSC") return false;
      return r.oe === hubEn || r.de === hubEn || r.ot === hubTc || r.dt === hubTc;
    });

    if (matches.length === 0) {
      host.innerHTML = `<div class="yuu-shuttle-empty">No casino runs a shuttle to ${escapeHtml(hubEn)} in our data.</div>`;
      return;
    }

    // Sort: open routes first (by next-departure asc), closed last.
    const enriched = matches.map((r) => ({
      r,
      next:  nextDepartureEstimate(r),
      clock: nextDepartureClockTimes(r, 3),
    }));
    enriched.sort((a, b) => {
      const ao = a.next?.kind === "running" ? a.next.nextMin : 9999;
      const bo = b.next?.kind === "running" ? b.next.nextMin : 9999;
      if (ao !== bo) return ao - bo;
      return (a.r.casino || "").localeCompare(b.r.casino || "");
    });

    host.innerHTML =
      `<div class="yuu-shuttle-section-title">${matches.length} shuttles · ${escapeHtml(hubTc)} · ${escapeHtml(hubEn)}</div>` +
      enriched.map(({ r, next, clock }) => {
        const c = r.color || "#a89060";
        // The casino is whichever end ISN'T the hub.
        const otherEn = r.oe === hubEn ? r.de : r.oe;
        const otherTc = r.ot === hubTc ? r.dt : r.ot;
        let meta;
        if (next?.kind === "running" && clock?.length) {
          meta = `<span class="yuu-shuttle-row-next">⏱ ${escapeHtml(clock.slice(0,2).join(" · "))}</span><span>last ${next.lastHHMM}</span>`;
        } else if (next?.kind === "running") {
          meta = `<span class="yuu-shuttle-row-next">⏱ Next ~${next.nextMin} min</span><span>last ${next.lastHHMM}</span>`;
        } else if (next?.kind === "closed") {
          meta = `<span class="yuu-shuttle-row-closed">Closed</span><span>service ${next.firstHHMM}–${next.lastHHMM}</span>`;
        } else {
          meta = `<span>${escapeHtml(r.frequency || "")}</span><span>${escapeHtml(r.hours || "")}</span>`;
        }
        return `<div class="yuu-shuttle-row" data-rk="${escapeHtml(r.rk)}">
          <span class="yuu-badge MOSC" style="background:${c};color:#fff">${escapeHtml(r.casino || "Shuttle")}</span>
          <div class="yuu-shuttle-row-direction">
            <div>${escapeHtml(otherEn || "")}</div>
            <div class="yuu-shuttle-row-tc">${escapeHtml(otherTc || "")}</div>
          </div>
          <div class="yuu-shuttle-row-meta">${meta}</div>
        </div>`;
      }).join("");

    host.querySelectorAll(".yuu-shuttle-row").forEach((row) => {
      row.addEventListener("click", () => {
        const rk = row.dataset.rk;
        const r = (state.routes || []).find((x) => x.rk === rk);
        if (r) selectRoute(r);
      });
    });

    // Plot all the matched routes on the desktop-only side map.
    renderShuttleHubMap(hubCode, stopId, matches).catch((e) => console.warn(e));
  }

  // Synthesised concrete next-departure timetable for Macau routes. Each
  // casino publishes a fixed daily timetable but we don't have it; given
  // a route's `frequency: "Every 15 min"` + `hours: "07:00–23:30"` we
  // generate the next N HH:MM slots starting from now (rounded up to the
  // next interval). Returns an array of strings or [] if outside service.
  function nextDepartureClockTimes(route, count) {
    if (!route?.hours) return null;
    const m = route.hours.match(/(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})/);
    if (!m) return null;
    let lastH = +m[3];
    const startMin = (+m[1]) * 60 + (+m[2]);
    if (lastH < +m[1]) lastH += 24;             // wraps past midnight
    const endMin = lastH * 60 + (+m[4]);
    const fm = (route.frequency || "").match(/(\d+)(?:\s*[–-]\s*(\d+))?/);
    const freqMin = fm ? (+fm[1]) : 15;          // pick the lower bound
    const now = new Date();
    let curMin = now.getHours() * 60 + now.getMinutes();
    // Wrap into post-midnight slots if we're before the start window AND
    // the service is currently in its post-midnight tail (e.g. it's 00:15
    // and last bus is 00:30).
    if (curMin < startMin && curMin + 24 * 60 <= endMin) curMin += 24 * 60;
    let nextMin = curMin <= startMin
      ? startMin
      : Math.ceil((curMin - startMin) / freqMin) * freqMin + startMin;
    if (nextMin > endMin) return [];
    const out = [];
    const want = count || 3;
    while (out.length < want && nextMin <= endMin) {
      const h = Math.floor(nextMin / 60) % 24;
      const mm = nextMin % 60;
      out.push(`${h.toString().padStart(2,"0")}:${mm.toString().padStart(2,"0")}`);
      nextMin += freqMin;
    }
    return out;
  }

  // For Macau routes (no live ETA available — DSAT API CORS-closed) derive
  // a "next bus" estimate from the static schedule chips on the route. The
  // route carries:
  //   - hours:     "06:00–00:30"      (operating window; 24:xx allowed past midnight)
  //   - frequency: "Every 8 min" / "Every 8–10 min"
  // Returns one of:
  //   { kind: "running", nextMin, freqMin, lastHHMM }
  //   { kind: "closed",  firstHHMM, lastHHMM }
  //   null  (no schedule data → caller skips)
  function nextDepartureEstimate(route) {
    if (!route || !route.hours) return null;
    const m = (route.hours.match(/(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})/));
    if (!m) return null;
    let firstH = +m[1], firstM = +m[2], lastH = +m[3], lastM = +m[4];
    // Macau schedules wrap past midnight as "00:30" or "01:00" — treat
    // those as next-day so the comparison below still works.
    if (lastH < firstH) lastH += 24;
    const now = new Date();
    const cur = now.getHours() + now.getMinutes() / 60;
    const start = firstH + firstM / 60;
    const end   = lastH   + lastM   / 60;
    const lastHHMM = `${(lastH % 24).toString().padStart(2,"0")}:${m[4].padStart(2,"0")}`;
    const firstHHMM = `${m[1].padStart(2,"0")}:${m[2].padStart(2,"0")}`;
    const inWindow = (cur >= start && cur <= end) ||
                     (cur + 24 >= start && cur + 24 <= end);
    if (!inWindow) {
      return { kind: "closed", firstHHMM, lastHHMM };
    }
    // Frequency: pick the upper bound from "Every N min" / "Every A–B min".
    const fm = (route.frequency || "").match(/(\d+)(?:\s*[–-]\s*(\d+))?\s*min/);
    const freqMin = fm ? (+fm[2] || +fm[1]) : 15;
    // Without per-vehicle GPS the actual wait is uniform on [0, freqMin],
    // so the EXPECTED wait is freqMin / 2. Round to nearest minute.
    const nextMin = Math.max(1, Math.round(freqMin / 2));
    return { kind: "running", nextMin, freqMin, lastHHMM };
  }

  // Rough fare estimator per operator. The HK gov APIs do publish
  // per-route per-stop fares (KMB/CTB) but we don't bake them into the
  // static bundle yet — for now show typical-range strings so every
  // route card carries a price hint. Casino shuttles are free.
  // hops is optional: if provided, narrows the range proportionally.
  function fareEstimate(route, hops) {
    if (!route) return null;
    const co = route.co;
    if (co === "MOSC") return { str: "Free 免費", currency: "" };
    // Per-operator typical ranges (HK$ unless noted). Numbers approximate
    // 2026 tariffs; long-haul / cross-harbour routes are above the upper
    // bound shown here.
    const RANGE = {
      KMB:  [4.5, 24.5,  "HK$"],
      CTB:  [4.5, 24.5,  "HK$"],
      GMB:  [3.0, 15.0,  "HK$"],
      MTRB: [4.5, 16.5,  "HK$"],
      RMB:  [8.0, 40.0,  "HK$"],
      MTR:  [5.0, 47.0,  "HK$"],
      MOB:  [6.0, 6.0,   "MOP$"],   // DSAT flat 6 patacas peninsula or Cotai
      LRT:  [6.0, 6.0,   "MOP$"],   // MLM flat 6 patacas / 1-3 zones
    };
    const r = RANGE[co];
    if (!r) return null;
    const [low, high, currency] = r;
    if (low === high) return { str: `${currency}${low.toFixed(0)}`, currency, amount: low };
    if (typeof hops === "number" && hops >= 0) {
      // Linearly interpolate based on hops. ~30 hops = full route end-to-
      // end → upper bound. Short rides land near the lower bound.
      const t = Math.max(0, Math.min(1, hops / 30));
      const est = low + (high - low) * t;
      const rounded = Math.round(est * 2) / 2;  // nearest 0.5
      return { str: `~${currency}${rounded.toFixed(rounded % 1 ? 1 : 0)}`, currency, amount: rounded };
    }
    return {
      str: `${currency}${low.toFixed(0)}–${high.toFixed(0)}`,
      currency,
      amount: (low + high) / 2,
    };
  }

  // Rough taxi-fare estimator. Both HK and Macau publish flag-fall + per-
  // distance tariffs; we model just the trunk amount (no surcharges) since
  // the user wants a sanity number, not a billing system. Road distance is
  // approximated as straight-line × 1.35.
  //
  // HK urban taxi (2026 tariff):
  //   First 2 km HK$29; thereafter HK$2.10 per 200 m up to HK$102.50,
  //   then HK$1.40 per 200 m. We linearise to ~HK$10.50/km after the flag.
  // Macau taxi:
  //   Flag-fall MOP$21 covering 1.6 km, then MOP$2 per 240 m
  //   (~MOP$8.30/km). All-Macau approximation; airport / cross-border
  //   surcharges (MOP$5–10) not modelled.
  //
  // Returns {region, currency, amount, str, walkMin}. region is "hk" or
  // "mo" inferred from the from-coordinate; currency is "HK$" or "MOP$".
  function estimateTaxi(fromLat, fromLng, toLat, toLng) {
    const region = (fromLng < 113.65 && fromLat < 22.25) ? "mo" : "hk";
    const straightM = distanceM(fromLat, fromLng, toLat, toLng);
    const roadKm = Math.max(0.4, straightM * 1.35 / 1000);
    let amount;
    if (region === "hk") {
      amount = 29 + Math.max(0, roadKm - 2) * 10.5;
    } else {
      amount = 21 + Math.max(0, roadKm - 1.6) * 8.3;
    }
    amount = Math.round(amount);
    const currency = region === "hk" ? "HK$" : "MOP$";
    // Avg taxi speed across HK / Macau urban roads ≈ 22 km/h with traffic.
    const minutes = Math.max(2, Math.round(roadKm / 22 * 60));
    return {
      region, currency, amount,
      str: `${currency}${amount}`,
      minutes,
      roadKm: Math.round(roadKm * 10) / 10,
    };
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
    initMtrToggle();
    initTripPlanner();
    $("yuu-meta").textContent = "Loading routes…";

    try {
      const [routes, meta] = await Promise.all([
        fetchJson(`${DATA_BASE}/routes.json`),
        fetchJson(`${DATA_BASE}/meta.json`),
      ]);
      state.routes = routes;
      state.meta = meta;
      renderMeta();
      // Warm caches so the MTR map and Plan map don't pay first-open
      // latency. Both run as fire-and-forget background fetches.
      warmMtrGeometries();
      ensureStopRoutesLoaded().catch(() => {});
      ensureStopsLoaded().catch(() => {});
      // Initialise the Plan-tab map immediately (it's hidden under the
      // Bus tab by default, but tiles load anyway and render on first
      // tab switch via invalidateSize).
      try { ensurePlanMapRendered(); } catch (e) { /* leaflet init quirk; retried later */ }
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

  // Tab → region map. The region switch (HK | Macau) hides tabs whose
  // data-region doesn't match the active region; "any" tabs (Plan) are
  // visible in both regions.
  const TAB_REGION = {
    bus: "hk", mtr: "hk",
    mobus: "mo", lrt: "mo", shuttle: "mo",
    plan: "any",
  };
  const REGION_DEFAULT_TAB = { hk: "bus", mo: "mobus" };

  function initModeTabs() {
    document.querySelectorAll(".yuu-tab").forEach((btn) => {
      btn.addEventListener("click", () => activateTab(btn.dataset.tab));
    });
    document.querySelectorAll(".yuu-region").forEach((btn) => {
      btn.addEventListener("click", () => activateRegion(btn.dataset.region));
    });
    activateRegion("hk");
  }

  function activateRegion(region) {
    state.activeRegion = region;
    document.querySelectorAll(".yuu-region").forEach((b) => {
      const on = b.dataset.region === region;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.querySelectorAll(".yuu-tab").forEach((b) => {
      const r = b.dataset.region;
      b.hidden = !(r === region || r === "any");
    });
    const cur = state.activeTab;
    if (!cur || (TAB_REGION[cur] !== region && TAB_REGION[cur] !== "any")) {
      activateTab(REGION_DEFAULT_TAB[region]);
    }
  }

  function activateTab(tab) {
    // Tab switch ⇒ wipe per-route state. Otherwise the previous selection
    // (selected route, sticky search query, ETA timer) bleeds into the new
    // tab and the user sees stale stops / a stale route panel.
    const prev = state.activeTab;
    if (prev && prev !== tab) {
      state.selectedRoute = null;
      state.selectedStop = null;
      stopEtaPolling();
      const search = $("yuu-search-input");
      if (search) { search.value = ""; delete search.dataset.stopId; }
      const results = $("yuu-search-results");
      if (results) { results.hidden = true; results.innerHTML = ""; }
      const eta = $("yuu-eta");
      if (eta) eta.hidden = true;
      const yuu = $("yuu");
      if (yuu) {
        yuu.dataset.company = "";
        yuu.dataset.joint = "false";
        yuu.style.removeProperty("--yuu-route-color");
        yuu.style.removeProperty("--yuu-route-color-soft");
        yuu.style.removeProperty("--yuu-route-text");
      }
    }
    state.activeTab = tab;
    document.querySelectorAll(".yuu-tab").forEach((b) => {
      const on = b.dataset.tab === tab;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });

    // Tighten / loosen the main map's bounds depending on which region the
    // active tab belongs to so the user can't pan across the whole HK + MO
    // span unintentionally.
    applyMapBoundsForTab(tab);

    const explore = $("yuu-explore-controls");
    const planSec = $("yuu-plan");
    const welcome = $("yuu-welcome");
    const route   = $("yuu-route");
    const sel     = $("yuu-mode-select");

    const mtrView = $("yuu-mtr-view");
    const map     = $("yuu-map");

    if (tab === "plan") {
      if (explore)   explore.hidden   = true;
      if (welcome)   welcome.hidden   = true;
      if (route)     route.hidden     = true;
      if (mtrView)   mtrView.hidden   = true;
      if (planSec)   planSec.hidden   = false;
      if (map)       map.hidden       = true;
      ensurePlanMapRendered();
      setTimeout(() => planMap?.invalidateSize(), 0);
      $("yuu-plan-from")?.focus();
      return;
    }

    if (planSec) planSec.hidden = true;

    if (tab === "mtr") {
      // Dedicated MTR view: from/to diagram form + map sub-mode.
      if (explore)   explore.hidden   = true;
      if (welcome)   welcome.hidden   = true;
      if (route)     route.hidden     = true;
      if (map)       map.hidden       = true;
      if (mtrView)   mtrView.hidden   = false;
      const shuttleV = $("yuu-shuttle-view"); if (shuttleV) shuttleV.hidden = true;
      ensureMtrTopologyLoaded().catch(() => {});
      return;
    }

    if (tab === "shuttle") {
      // Hub-first view: pick a transit hub, then see which casinos run a
      // shuttle to / from it. From → To search lives in the Plan tab; this
      // tab is for when you're already at a hub and want to know your
      // options. Falls through to the standard route view once a route is
      // picked.
      const r = state.selectedRoute;
      const isMosc = r && r.co === "MOSC";
      if (isMosc) {
        if (mtrView) mtrView.hidden = true;
        const shuttleV = $("yuu-shuttle-view"); if (shuttleV) shuttleV.hidden = true;
        if (map)     map.hidden     = false;
        if (explore) explore.hidden = false;
        if (welcome) welcome.hidden = true;
        if (route)   route.hidden   = false;
        if (sel)     sel.style.display = "none";
        return;
      }
      if (explore) explore.hidden = true;
      if (welcome) welcome.hidden = true;
      if (route)   route.hidden   = true;
      if (map)     map.hidden     = true;
      if (mtrView) mtrView.hidden = true;
      const shuttleV = $("yuu-shuttle-view"); if (shuttleV) shuttleV.hidden = false;
      ensureShuttleViewWired();
      return;
    }

    // Bus tab + MO per-mode tabs (mobus / lrt) share the same UX: search
    // box at top, route list / nearby below, main map sticky on the side.
    // TAB_COMPANIES filters search / nearby suggestions to that mode's
    // operators.
    if (mtrView) mtrView.hidden = true;
    // BUG FIX: previous round left the shuttle view visible when the
    // user switched from 財車 → MOBus / LRT. Always hide it unless the
    // shuttle branch above explicitly shows it.
    const shuttleV = $("yuu-shuttle-view"); if (shuttleV) shuttleV.hidden = true;
    if (map)     map.hidden     = false;
    if (explore) explore.hidden = false;
    if (sel)     sel.style.display = (tab === "bus") ? "" : "none";

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


  // ============================================================ MTR View
  // Two presentations:
  //   - Diagram: From / To search → planned route with leg ETAs.
  //   - Map:     full Leaflet map of the network, click any station for
  //              ETAs across all lines that serve it + Set as From/To.

  let mtrMap = null;
  let mtrPolylineLayer = null;     // Leaflet layer group for the chosen
                                    // journey overlay (cleared between plans).
  const mtrStationMarkers = new Map(); // mtr_code → Leaflet marker
  const mtrStationLines   = new Map(); // mtr_code → Set<line_id>
  const mtrStationsByLine = new Map(); // line_id → ordered array of codes
  const mtrJourney = { from: null, to: null }; // each is {code, name}
  // Region bounds: covers HK + Macau + the HZMB bridge between them so the
  // map pans freely between the two SARs without snapping back. Macau is
  // ~22.10–22.22°N / 113.52–113.62°E; HK is ~22.13–22.62°N / 113.78–114.50°E.
  const HK_BOUNDS = [[22.05, 113.50], [22.62, 114.50]];
  // Tighter region bounds applied to the main map per-tab so the user
  // doesn't pan to the wrong SAR by accident.
  const HK_TIGHT_BOUNDS = [[22.13, 113.78], [22.62, 114.50]];
  const MO_TIGHT_BOUNDS = [[22.10, 113.50], [22.22, 113.62]];

  function applyMapBoundsForTab(tab) {
    const map = state.map;
    if (!map) return;
    const region = TAB_REGION[tab];
    let b;
    if (region === "mo")      b = MO_TIGHT_BOUNDS;
    else if (region === "hk") b = HK_TIGHT_BOUNDS;
    else                      b = HK_BOUNDS;
    map.setMaxBounds(b);
    // Re-centre only when no route is selected; otherwise the route polyline
    // owns the viewport.
    if (!state.selectedRoute && !state.routeLayer) {
      map.fitBounds(b, { animate: false });
    }
  }

  function initMtrToggle() {
    document.querySelectorAll(".yuu-mtr-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchMtrMode(btn.dataset.mtrMode));
    });
    $("yuu-mtr-clear")?.addEventListener("click", () => {
      mtrJourney.from = null;
      mtrJourney.to = null;
      const fi = $("yuu-mtr-from-input"); if (fi) fi.value = "";
      const ti = $("yuu-mtr-to-input");   if (ti) ti.value = "";
      renderMtrJourneyForm();
      $("yuu-mtr-journey-result").innerHTML = "";
      if (mtrPolylineLayer) mtrPolylineLayer.clearLayers();
    });
    $("yuu-mtr-swap")?.addEventListener("click", () => {
      const t = mtrJourney.from; mtrJourney.from = mtrJourney.to; mtrJourney.to = t;
      const fi = $("yuu-mtr-from-input");
      const ti = $("yuu-mtr-to-input");
      if (fi && ti) { const v = fi.value; fi.value = ti.value; ti.value = v; }
      renderMtrJourneyForm();
      maybePlanMtrJourney();
    });

    // Diagram-mode From / To autocomplete: searches MTR stations only.
    setupMtrStationAutocomplete($("yuu-mtr-from-input"), $("yuu-mtr-from-suggest"), "from");
    setupMtrStationAutocomplete($("yuu-mtr-to-input"),   $("yuu-mtr-to-suggest"),   "to");
  }

  // Station autocomplete restricted to the 97 MTR stations. The mtrStationLines
  // map is populated when ensureMtrMapRendered runs, but for the diagram
  // form we want it populated even before the map opens — kick it off
  // lazily on first input focus.
  function setupMtrStationAutocomplete(input, suggest, which) {
    if (!input || !suggest) return;
    let timer = null;
    const run = (q) => {
      const stops = state.stops || {};
      const query = (q || "").trim();
      if (query.length < 1) { suggest.hidden = true; return; }
      const lower = query.toLowerCase();
      const matches = [];
      for (const [id, s] of Object.entries(stops)) {
        if (!id.startsWith("MTR_")) continue;
        if (matches.length >= 12) break;
        const code = id.slice(4);
        const ne = (s.ne || "").toLowerCase();
        const nt = s.nt || "";
        if (code.toLowerCase().includes(lower) || ne.includes(lower) || nt.includes(query)) {
          matches.push({ code, ...s });
        }
      }
      if (matches.length === 0) {
        suggest.innerHTML = `<div class="yuu-plan-suggest-empty">No matching stations</div>`;
        suggest.hidden = false;
        return;
      }
      suggest.innerHTML = matches.map((m) => `
        <div class="yuu-plan-suggest-item" data-code="${escapeHtml(m.code)}"
             data-display="${escapeHtml(m.nt || m.ne || m.code)}">
          <span class="yuu-plan-suggest-tc">${escapeHtml(m.nt || m.ne || m.code)}</span>
          <span class="yuu-plan-suggest-en">${escapeHtml(m.ne)} · ${escapeHtml(m.code)}</span>
        </div>`).join("");
      suggest.hidden = false;
      suggest.querySelectorAll(".yuu-plan-suggest-item").forEach((el) => {
        el.addEventListener("click", () => {
          input.value = el.dataset.display;
          mtrJourney[which] = { code: el.dataset.code, name: el.dataset.display };
          suggest.hidden = true;
          renderMtrJourneyForm();
          maybePlanMtrJourney();
        });
      });
    };
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => run(input.value), 100);
    });
    input.addEventListener("focus", () => {
      ensureStopsLoaded().then(() => { if (input.value.trim()) run(input.value); });
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".yuu-plan-input-wrap")) suggest.hidden = true;
    });
  }

  function renderMtrJourneyForm() {
    const journeyHost = $("yuu-mtr-journey");
    const fromVal = $("yuu-mtr-from-val");
    const toVal   = $("yuu-mtr-to-val");
    if (!journeyHost) return;
    const showForm = !!(mtrJourney.from || mtrJourney.to);
    journeyHost.hidden = !showForm;
    if (fromVal) fromVal.textContent = mtrJourney.from ? `${mtrJourney.from.name} (${mtrJourney.from.code})` : "—";
    if (toVal)   toVal.textContent   = mtrJourney.to   ? `${mtrJourney.to.name} (${mtrJourney.to.code})`   : "—";
  }

  function maybePlanMtrJourney() {
    if (!mtrJourney.from || !mtrJourney.to) return;
    if (mtrJourney.from.code === mtrJourney.to.code) {
      $("yuu-mtr-journey-result").innerHTML =
        `<div class="yuu-plan-empty">From and to are the same station.</div>`;
      return;
    }
    const path = mtrShortestPath(mtrJourney.from.code, mtrJourney.to.code);
    if (!path) {
      $("yuu-mtr-journey-result").innerHTML =
        `<div class="yuu-plan-empty">No route found between these stations.</div>`;
      return;
    }
    renderMtrJourneyResult(path);
    drawMtrJourneyOnMap(path);
  }

  // Build a station-line graph and Dijkstra over it. Nodes are
  // "CODE|LINE"; edges are consecutive stations on the same line (cost 1
  // station-hop ≈ 2 min) and same-station interchanges (cost 4 min).
  function mtrShortestPath(fromCode, toCode) {
    if (!mtrStationsByLine.size || !mtrStationLines.size) return null;
    const HOP = 2;       // minutes per station hop
    const TRANSFER = 4;  // minutes per interchange

    // Build adjacency once, lazily.
    if (!mtrShortestPath._adj) {
      const adj = new Map();
      const ensure = (n) => { if (!adj.has(n)) adj.set(n, []); };
      // Same-line consecutive stations
      mtrStationsByLine.forEach((codes, line) => {
        for (let i = 0; i < codes.length - 1; i++) {
          const a = `${codes[i]}|${line}`;
          const b = `${codes[i+1]}|${line}`;
          ensure(a); ensure(b);
          adj.get(a).push({ n: b, w: HOP });
          adj.get(b).push({ n: a, w: HOP });
        }
      });
      // Interchanges
      mtrStationLines.forEach((lineSet, code) => {
        const lns = [...lineSet];
        for (let i = 0; i < lns.length; i++)
          for (let j = i + 1; j < lns.length; j++) {
            const a = `${code}|${lns[i]}`, b = `${code}|${lns[j]}`;
            ensure(a); ensure(b);
            adj.get(a).push({ n: b, w: TRANSFER });
            adj.get(b).push({ n: a, w: TRANSFER });
          }
      });
      mtrShortestPath._adj = adj;
    }
    const adj = mtrShortestPath._adj;

    const startNodes = [...(mtrStationLines.get(fromCode) || [])].map((l) => `${fromCode}|${l}`);
    const targets   = new Set([...(mtrStationLines.get(toCode) || [])].map((l) => `${toCode}|${l}`));
    if (!startNodes.length || !targets.size) return null;

    const dist = new Map();
    const prev = new Map();
    const queue = [];
    startNodes.forEach((n) => { dist.set(n, 0); queue.push([0, n]); });

    while (queue.length) {
      queue.sort((a, b) => a[0] - b[0]);
      const [d, u] = queue.shift();
      if (d > (dist.get(u) ?? Infinity)) continue;
      if (targets.has(u)) {
        const path = [u];
        let cur = u;
        while (prev.has(cur)) { cur = prev.get(cur); path.unshift(cur); }
        return { path, totalMin: d };
      }
      for (const { n: v, w } of adj.get(u) || []) {
        const newD = d + w;
        if (newD < (dist.get(v) ?? Infinity)) {
          dist.set(v, newD);
          prev.set(v, u);
          queue.push([newD, v]);
        }
      }
    }
    return null;
  }

  // Estimated walking-transfer minutes between two MTR lines at the same
  // station. Hong Kong's biggest interchanges (Admiralty, Mong Kok, Nam
  // Cheong, Tsim Sha Tsui ↔ East Tsim Sha Tsui) are slower than typical.
  const MTR_TRANSFER_OVERRIDES = {
    ADM: 4, NAC: 4, MOK: 5, KOT: 4, PRE: 4, HOK: 4, CEN: 4,
    TST: 5, ETS: 5, HUH: 4, SHT: 3, TIK: 3, YAT: 3,
  };

  function renderMtrJourneyResult(result) {
    const legs = [];
    let cur = null;
    for (const node of result.path) {
      const [code, line] = node.split("|");
      if (!cur || cur.line !== line) {
        if (cur) cur.toCode = code;
        cur = { line, fromCode: code, toCode: code, hops: 0 };
        legs.push(cur);
      } else {
        cur.toCode = code;
        cur.hops++;
      }
    }
    while (legs.length > 1 && legs[legs.length - 1].hops === 0) legs.pop();

    const stops = state.stops || {};
    const stationName = (code) => {
      const s = stops[`MTR_${code}`];
      return s ? (s.nt || s.ne) : code;
    };

    // Build the leg / transfer interleaved item list. Transfers are inserted
    // BETWEEN consecutive legs whose .fromCode (current leg) === previous
    // leg's .toCode (interchange at the same station).
    const items = [];
    for (let i = 0; i < legs.length; i++) {
      items.push({ kind: "leg", leg: legs[i] });
      if (i < legs.length - 1) {
        const transferAt = legs[i].toCode;
        items.push({
          kind: "transfer",
          atCode: transferAt,
          minutes: MTR_TRANSFER_OVERRIDES[transferAt] ?? 4,
        });
      }
    }

    // Render head + leg list. First leg gets an ETA placeholder that we
    // populate asynchronously.
    const head = `<div class="yuu-mtr-journey-summary">
      <strong>${Math.round(result.totalMin)} min</strong>
      <span> · ${legs.length} ${legs.length === 1 ? "leg" : "legs"}</span>
    </div>`;

    const body = items.map((it, idx) => {
      if (it.kind === "leg") {
        const leg = it.leg;
        const c = MTR_LINE_COLOR[leg.line] || "#1d3557";
        const isFirst = idx === 0;
        const etaSpan = isFirst
          ? `<div class="yuu-mtr-leg-eta" id="yuu-mtr-leg-eta-0">Loading next train…</div>`
          : "";
        return `<li class="yuu-mtr-leg" style="--c:${c}">
          <span class="yuu-mtr-leg-line" style="background:${c}">${escapeHtml(leg.line)}</span>
          <div class="yuu-mtr-leg-body">
            <div class="yuu-mtr-leg-label">${escapeHtml(stationName(leg.fromCode))} → ${escapeHtml(stationName(leg.toCode))}</div>
            <div class="yuu-mtr-leg-hops">${leg.hops} station${leg.hops === 1 ? "" : "s"} · ~${leg.hops * 2} min</div>
            ${etaSpan}
          </div>
        </li>`;
      }
      // transfer
      return `<li class="yuu-mtr-transfer">
        <span class="yuu-mtr-transfer-icon">⇅</span>
        <span>Transfer at <strong>${escapeHtml(stationName(it.atCode))}</strong> · ~${it.minutes} min</span>
      </li>`;
    }).join("");

    $("yuu-mtr-journey-result").innerHTML = head + `<ol class="yuu-mtr-legs">${body}</ol>`;
    // Async-load first-leg ETA so the user sees "next train" specifically
    // for the boarding station + line + direction they're about to take.
    populateFirstLegEta(legs[0]).catch((e) => console.warn(e));
  }

  // Determine which platform direction the leg is going (UP or DOWN) by
  // checking the relative ordering of from/to in the line's station array,
  // then call the MTR schedule API and surface the next 2 trains.
  async function populateFirstLegEta(leg) {
    if (!leg) return;
    const ordered = mtrStationsByLine.get(leg.line) || [];
    const fIdx = ordered.indexOf(leg.fromCode);
    const tIdx = ordered.indexOf(leg.toCode);
    let want;
    if (fIdx < 0 || tIdx < 0) want = null;
    else want = (tIdx > fIdx) ? "DOWN" : "UP";  // CSV defines UP as the
                                                  // direction toward sequence 1
    try {
      const raw = await fetchJson(
        `https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php?line=${encodeURIComponent(leg.line)}&sta=${encodeURIComponent(leg.fromCode)}`,
        { cache: "no-store" }
      );
      const v = (raw.data && raw.data[`${leg.line}-${leg.fromCode}`]) || {};
      const trains = ((want && v[want]) || v.UP || v.DOWN || [])
        .filter((e) => e.valid !== "N").slice(0, 2);
      const stops = state.stops || {};
      const fmt = (e) => {
        const iso = e.time ? e.time.replace(" ", "T") + "+08:00" : null;
        const m = iso ? Math.round((new Date(iso).getTime() - Date.now()) / 60_000) : null;
        const label = m == null ? "—" : m <= 0 ? "Now" : (m === 1 ? "1 min" : `${m} min`);
        const dest = e.dest && stops["MTR_" + e.dest]
          ? (stops["MTR_" + e.dest].nt || stops["MTR_" + e.dest].ne)
          : (e.dest || "");
        const plat = e.plat ? `P${e.plat}` : "";
        return `<span class="yuu-mtr-eta-pill">${escapeHtml(label)} ${escapeHtml(plat)}<small>→ ${escapeHtml(dest)}</small></span>`;
      };
      const target = $("yuu-mtr-leg-eta-0");
      if (target) {
        target.innerHTML = trains.length
          ? `<span class="yuu-mtr-leg-eta-label">Next train</span>${trains.map(fmt).join("")}`
          : `<span class="yuu-mtr-leg-eta-empty">No upcoming trains</span>`;
      }
    } catch {
      const target = $("yuu-mtr-leg-eta-0");
      if (target) target.innerHTML = `<span class="yuu-mtr-leg-eta-empty">ETA unavailable</span>`;
    }
  }

  function drawMtrJourneyOnMap(result) {
    if (!mtrMap) return;
    if (!mtrPolylineLayer) {
      mtrPolylineLayer = L.layerGroup().addTo(mtrMap);
    } else {
      mtrPolylineLayer.clearLayers();
    }
    const stops = state.stops || {};
    const points = result.path
      .map((n) => stops[`MTR_${n.split("|")[0]}`])
      .filter(Boolean)
      .map((s) => [s.la, s.lg]);
    if (points.length > 1) {
      L.polyline(points, { color: "#0f172a", weight: 6, opacity: 0.6, dashArray: "4 6" })
        .addTo(mtrPolylineLayer);
      mtrMap.fitBounds(points, { padding: [40, 40], maxZoom: 14 });
    }
  }

  function switchMtrMode(mode) {
    document.querySelectorAll(".yuu-mtr-toggle-btn").forEach((b) =>
      b.classList.toggle("active", b.dataset.mtrMode === mode)
    );
    const showMap = mode === "map";
    $("yuu-mtr-diagram").hidden = showMap;
    $("yuu-mtr-map").hidden     = !showMap;
    if (showMap) {
      ensureMtrMapRendered();
    }
    renderMtrJourneyForm();
  }

  // Loads the full MTR topology (per-line station ordering + each station's
  // line memberships) so the diagram-mode shortest-path planner can run
  // even when the user never opens the Map sub-tab. Cached and idempotent.
  let mtrTopologyPromise = null;
  function ensureMtrTopologyLoaded() {
    if (mtrTopologyPromise) return mtrTopologyPromise;
    mtrTopologyPromise = (async () => {
      const lines = state.routes.filter((r) => r.co === "MTR");
      const geos = await Promise.all(lines.map((line) =>
        fetchJson(`${DATA_BASE}/geometry/${line.rk}_1.json`).catch(() => null)
      ));
      geos.forEach((geo, i) => {
        const line = lines[i];
        if (!geo) return;
        const ordered = [];
        for (const s of (geo.stops || [])) {
          const code = s.mtr_code;
          if (!code) continue;
          if (!mtrStationLines.has(code)) mtrStationLines.set(code, new Set());
          mtrStationLines.get(code).add(line.id);
          ordered.push(code);
        }
        mtrStationsByLine.set(line.id, ordered);
      });
      // Cache the geometries so the map render avoids a second round-trip.
      mtrTopologyPromise._geos = geos;
      mtrTopologyPromise._lines = lines;
    })();
    return mtrTopologyPromise;
  }

  async function ensureMtrMapRendered() {
    if (mtrMap) {
      setTimeout(() => mtrMap.invalidateSize(), 0);
      return;
    }
    mtrMap = L.map("yuu-mtr-map", {
      zoomControl: true,
      maxBounds: HK_BOUNDS,
      maxBoundsViscosity: 0.8,
      minZoom: 10,
    }).fitBounds(HK_BOUNDS);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; OSM &copy; CARTO',
      subdomains: "abcd",
      maxZoom: 19,
      minZoom: 10,
      bounds: HK_BOUNDS,
    }).addTo(mtrMap);

    const [stops] = await Promise.all([
      ensureStopsLoaded(),
      ensureMtrTopologyLoaded(),
    ]);
    const lines = mtrTopologyPromise._lines || state.routes.filter((r) => r.co === "MTR");
    const geos  = mtrTopologyPromise._geos  || [];

    geos.forEach((geo, i) => {
      const line = lines[i];
      if (!geo) return;
      const c = MTR_LINE_COLOR[line.id] || "#1d3557";
      const coords = (geo.coords || []).filter(
        (p) => Array.isArray(p) && typeof p[0] === "number"
      );
      if (coords.length > 1) {
        L.polyline(coords, { color: c, weight: 4, opacity: 0.85 }).addTo(mtrMap);
      }
    });

    mtrStationLines.forEach((lineSet, code) => {
      const stop = stops[`MTR_${code}`];
      if (!stop) return;
      const lns = [...lineSet];
      const isInterchange = lns.length > 1;
      const primary = MTR_LINE_COLOR[lns[0]] || "#1d3557";
      const marker = L.circleMarker([stop.la, stop.lg], {
        radius: isInterchange ? 7 : 5,
        fillColor: isInterchange ? "#ffffff" : primary,
        color: primary,
        weight: isInterchange ? 3 : 2,
        fillOpacity: 1,
      }).addTo(mtrMap);
      marker.bindTooltip(`${stop.nt || stop.ne} (${code})`);
      marker.on("click", () => openMtrStationPopup(code, stop, lns));
      mtrStationMarkers.set(code, marker);
    });
  }

  // Pre-fetch all 10 line geometries on page load so the first MTR map
  // open is instant. Fire-and-forget; subsequent ensureMtrMapRendered
  // reuses the warmed HTTP cache.
  function warmMtrGeometries() {
    const lines = state.routes.filter((r) => r.co === "MTR");
    lines.forEach((line) => {
      fetch(`${DATA_BASE}/geometry/${line.rk}_1.json`).catch(() => {});
    });
  }

  // Custom popup that shows: station name, lines served, next train per
  // line per direction, and Set-as-From / Set-as-To buttons that pre-fill
  // the trip planner.
  async function openMtrStationPopup(code, stop, lns) {
    const marker = mtrStationMarkers.get(code);
    if (!marker) return;
    const tcName = stop.nt || stop.ne;
    const enName = stop.ne || code;
    const linesHtml = lns.map((l) =>
      `<span class="yuu-mtr-popup-line" style="background:${MTR_LINE_COLOR[l] || "#1d3557"}">${escapeHtml(l)}</span>`
    ).join("");
    const popupId = `yuu-mtr-popup-${code}`;
    marker.bindPopup(
      `<div class="yuu-mtr-popup" id="${popupId}">
        <strong>${escapeHtml(tcName)}</strong>
        <div class="yuu-mtr-popup-en">${escapeHtml(enName)} · ${escapeHtml(code)}</div>
        <div class="yuu-mtr-popup-lines">${linesHtml}</div>
        <div class="yuu-mtr-popup-eta">Loading next trains…</div>
        <div class="yuu-mtr-popup-actions">
          <button type="button" class="yuu-mtr-popup-btn" data-action="from"
                  data-stop-id="MTR_${escapeHtml(code)}"
                  data-display="${escapeHtml(tcName)}">Set as From</button>
          <button type="button" class="yuu-mtr-popup-btn" data-action="to"
                  data-stop-id="MTR_${escapeHtml(code)}"
                  data-display="${escapeHtml(tcName)}">Set as To</button>
        </div>
      </div>`,
      { maxWidth: 280, className: "yuu-popup-wrap" }
    ).openPopup();

    // Wire from/to buttons after popup mounts (next tick).
    setTimeout(() => {
      const root = document.getElementById(popupId);
      if (!root) return;
      root.querySelectorAll(".yuu-mtr-popup-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const which = btn.dataset.action; // "from" | "to"
          // Set the MTR view's OWN journey endpoints (separate from the
          // global Plan trip tab). Then plan and render the rail journey.
          mtrJourney[which] = { code: code, name: tcName };
          renderMtrJourneyForm();
          maybePlanMtrJourney();
          marker.closePopup();
        });
      });
    }, 50);

    // Fetch the schedule for each line in parallel and render summarised
    // next-train rows into the popup.
    try {
      const fetches = lns.map((line) =>
        fetchJson(`https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php?line=${encodeURIComponent(line)}&sta=${encodeURIComponent(code)}`,
          { cache: "no-store" })
          .then((raw) => ({ line, data: raw.data?.[`${line}-${code}`] || {} }))
          .catch(() => ({ line, data: {} }))
      );
      const all = await Promise.all(fetches);
      const formatTime = (e) => {
        if (!e || !e.time) return null;
        const iso = e.time.replace(" ", "T") + "+08:00";
        const m = Math.round((new Date(iso).getTime() - Date.now()) / 60_000);
        return m <= 0 ? "Now" : (m === 1 ? "1 min" : `${m} min`);
      };
      const rows = all.map(({ line, data }) => {
        const c = MTR_LINE_COLOR[line] || "#1d3557";
        const ups = (data.UP   || []).filter((e) => e.valid !== "N");
        const dns = (data.DOWN || []).filter((e) => e.valid !== "N");
        const upOnly = ups[0] ? `↑ ${formatTime(ups[0])}` : "";
        const dnOnly = dns[0] ? `↓ ${formatTime(dns[0])}` : "";
        if (!upOnly && !dnOnly) return "";
        return `<div class="yuu-mtr-popup-line-row">
          <span class="yuu-mtr-popup-line" style="background:${c}">${escapeHtml(line)}</span>
          <span>${upOnly}</span><span>${dnOnly}</span>
        </div>`;
      }).join("");
      const root = document.getElementById(popupId);
      if (root) {
        const etaBox = root.querySelector(".yuu-mtr-popup-eta");
        if (etaBox) etaBox.innerHTML = rows || "No upcoming trains";
      }
    } catch (e) {
      const root = document.getElementById(popupId);
      if (root) root.querySelector(".yuu-mtr-popup-eta").textContent = "ETA unavailable";
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

  // ============================================================ Plan map

  let planMap = null;
  let planMapLayer = null;

  function ensurePlanMapRendered() {
    if (planMap) {
      setTimeout(() => planMap.invalidateSize(), 0);
      return;
    }
    if (!document.getElementById("yuu-plan-map")) return;
    planMap = L.map("yuu-plan-map", {
      zoomControl: true,
      maxBounds: HK_BOUNDS,
      maxBoundsViscosity: 0.8,
      minZoom: 10,
    }).fitBounds(HK_BOUNDS);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; OSM &copy; CARTO',
      subdomains: "abcd",
      maxZoom: 19,
      bounds: HK_BOUNDS,
    }).addTo(planMap);
  }

  // Drop origin/destination pins + selected route polyline on the plan map.
  function drawPlanOnMap(option, fromEnd, toEnd) {
    if (!planMap) return;
    if (!planMapLayer) planMapLayer = L.layerGroup().addTo(planMap);
    planMapLayer.clearLayers();

    const stops = state.stops || {};
    const fromS = (fromEnd.kind === "stop") ? stops[fromEnd.stopId]
                  : { la: fromEnd.lat, lg: fromEnd.lng };
    const toS   = (toEnd.kind === "stop")   ? stops[toEnd.stopId]
                  : { la: toEnd.lat,   lg: toEnd.lng   };

    const points = [];
    if (fromS) {
      L.marker([fromS.la, fromS.lg], { title: "Origin" })
        .bindTooltip(fromEnd.label || "From", { permanent: false })
        .addTo(planMapLayer);
      points.push([fromS.la, fromS.lg]);
    }
    if (toS) {
      L.marker([toS.la, toS.lg], { title: "Destination" })
        .bindTooltip(toEnd.label || "To", { permanent: false })
        .addTo(planMapLayer);
      points.push([toS.la, toS.lg]);
    }

    // Try to draw the selected route's polyline if available.
    const drawSegment = async (rk, dir, fromId, toId) => {
      try {
        const geo = await fetchJson(`${DATA_BASE}/geometry/${rk}_${dir}.json`);
        const segStops = geo.stops || [];
        const fIdx = segStops.findIndex((s) => s.stop_id === fromId);
        const tIdx = segStops.findIndex((s) => s.stop_id === toId);
        if (fIdx < 0 || tIdx <= fIdx) return;
        // Use only the segment points falling between board and alight
        // stops if we have stop coords, otherwise use the whole polyline.
        const allCoords = geo.coords || [];
        const route = state.routes.find((r) => r.rk === rk);
        const c = routeColor(route);
        if (allCoords.length > 1) {
          L.polyline(allCoords, { color: c, weight: 5, opacity: 0.85 }).addTo(planMapLayer);
          allCoords.forEach((p) => points.push(p));
        }
      } catch {}
    };
    if (option) {
      if (option.type === "interchange") {
        drawSegment(option.legA.rk, option.legA.dir, option.legA.boardId, option.legA.alightId);
        drawSegment(option.legB.rk, option.legB.dir, option.legB.boardId, option.legB.alightId);
      } else {
        drawSegment(option.route.rk, option.dir, option.board.id, option.alight.id);
      }
    }
    if (points.length >= 2) {
      planMap.fitBounds(points, { padding: [40, 40], maxZoom: 15 });
    }
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
      $("yuu-plan-results").innerHTML = `<div class="yuu-plan-loading">Searching…</div>`;
      // Auto-geocode any input the user typed without picking a
      // suggestion: hit OSM Nominatim, take the top hit, treat it as an
      // address endpoint. Matches the user expectation that a typed
      // address should "just work" without forcing a dropdown click.
      const fromEnd = await resolveEndpointInput(from);
      const toEnd   = await resolveEndpointInput(to);
      if (!fromEnd || !toEnd) {
        $("yuu-plan-results").innerHTML =
          `<div class="yuu-plan-empty">Couldn't find one of the locations. Try a more specific name or pick a suggestion.</div>`;
        return;
      }
      try {
        const trips = await planTripMulti(fromEnd, toEnd);
        renderPlanResults(trips, fromEnd, toEnd);
      } catch (err) {
        console.error(err);
        $("yuu-plan-results").innerHTML =
          `<div class="yuu-plan-empty">Could not search routes. Try again.</div>`;
      }
    });
  }

  // First check if the input has a picked stop/address; if not, run a
  // Nominatim lookup on whatever raw text is in the box and use the top
  // hit as an address endpoint.
  async function resolveEndpointInput(input) {
    const picked = endpointFrom(input);
    if (picked) return picked;
    const q = (input?.value || "").trim();
    if (!q) return null;
    try {
      const hits = await geocodeAddress(q);
      const top = hits?.[0];
      if (!top) return null;
      // Persist on the input so subsequent clicks don't re-geocode.
      input.dataset.lat = top.lat;
      input.dataset.lng = top.lon;
      delete input.dataset.stopId;
      return {
        kind: "addr",
        lat: parseFloat(top.lat),
        lng: parseFloat(top.lon),
        label: top.display_name || q,
      };
    } catch {
      return null;
    }
  }

  function endpointFrom(input) {
    if (!input) return null;
    const lat = parseFloat(input.dataset.lat || "");
    const lng = parseFloat(input.dataset.lng || "");
    if (input.dataset.stopId) {
      return {
        kind: "stop",
        stopId: input.dataset.stopId,
        label: input.value,
        lat: Number.isFinite(lat) ? lat : null,
        lng: Number.isFinite(lng) ? lng : null,
      };
    }
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      return { kind: "addr", lat, lng, label: input.value };
    }
    return null;
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
      if (matches.length >= 8) break;
      const ne = (s.ne || "").toLowerCase();
      const nt = s.nt || "";
      if (ne.includes(lower) || nt.includes(query)) {
        matches.push({ id, ...s });
      }
    }

    // Always offer Nominatim address suggestions as a complement to stop
    // matches — addresses geocode to (lat, lng) which the planner uses to
    // find walking-distance stops near each end.
    let addresses = [];
    try {
      addresses = await geocodeAddress(query);
    } catch (e) { /* network blip → fall through */ }

    const stopHtml = matches.map((m) => {
      const tcRow = m.nt ? `<span class="yuu-plan-suggest-tc">${escapeHtml(m.nt)}</span>` : "";
      const en = displayEn(m.ne || "");
      return `<div class="yuu-plan-suggest-item" data-mode="stop"
                   data-stop-id="${escapeHtml(m.id)}"
                   data-lat="${m.la ?? ""}" data-lng="${m.lg ?? ""}"
                   data-display="${escapeHtml(m.nt || en)}">
        ${tcRow}
        <span class="yuu-plan-suggest-en">${escapeHtml(en)}</span>
        <span class="yuu-plan-suggest-co">${escapeHtml(m.co || "")}</span>
      </div>`;
    }).join("");

    const addrHtml = addresses.slice(0, 5).map((a) => `
      <div class="yuu-plan-suggest-item" data-mode="addr"
           data-lat="${a.lat}" data-lng="${a.lon}"
           data-display="${escapeHtml(a.display_name)}">
        <span class="yuu-plan-suggest-tc">${escapeHtml(a.display_name)}</span>
        <span class="yuu-plan-suggest-co">📍 Address</span>
      </div>`).join("");

    if (!stopHtml && !addrHtml) {
      suggest.innerHTML = `<div class="yuu-plan-suggest-empty">No matches</div>`;
      suggest.hidden = false;
      return;
    }

    // Address (place / Nominatim) suggestions first — the user's intent
    // is usually "I'm at this place", not "I'm at this specific kerb".
    // The planner picks nearest stops within 600 m of whichever entry
    // gets clicked, so an address pick gives more flexibility than a
    // stop pick.
    const addrHeader  = addrHtml ? `<div class="yuu-plan-suggest-section">📍 Places (OSM)</div>` : "";
    const stopHeader  = stopHtml ? `<div class="yuu-plan-suggest-section">Direct stops</div>` : "";
    suggest.innerHTML = addrHeader + addrHtml + stopHeader + stopHtml;
    suggest.hidden = false;
    suggest.querySelectorAll(".yuu-plan-suggest-item").forEach((el) => {
      el.addEventListener("click", () => {
        input.value = el.dataset.display || "";
        if (el.dataset.mode === "stop") {
          input.dataset.stopId = el.dataset.stopId;
          // Stop picks now also carry their lat/lng so the planner can
          // radiate out to neighbouring stops within walking distance —
          // matches user expectation that "永利澳門" finds bus stops near
          // Wynn Macau, not just the casino's own shuttle kerb.
          input.dataset.lat = el.dataset.lat || "";
          input.dataset.lng = el.dataset.lng || "";
        } else {
          input.dataset.lat = el.dataset.lat;
          input.dataset.lng = el.dataset.lng;
          delete input.dataset.stopId;
        }
        suggest.hidden = true;
      });
    });
  }

  // Nominatim geocoding — limited to HK, English/Chinese names, max 5
  // results. Free public service; respect their 1 req/sec etiquette.
  let _geocodeCache = new Map(), _geocodeInflight = null;
  async function geocodeAddress(query) {
    const key = query.toLowerCase();
    if (_geocodeCache.has(key)) return _geocodeCache.get(key);
    if (_geocodeInflight) await _geocodeInflight.catch(() => {});
    _geocodeInflight = (async () => {
      const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query + " Hong Kong")}&format=json&limit=5&accept-language=en,zh-HK&countrycodes=hk&addressdetails=0`;
      const resp = await fetch(url, { headers: { "Accept": "application/json" } });
      if (!resp.ok) return [];
      const data = await resp.json();
      _geocodeCache.set(key, data);
      return data;
    })();
    try { return await _geocodeInflight; }
    finally { _geocodeInflight = null; }
  }

  // For an arbitrary point, find the N nearest bus/MTR stops within radius.
  function nearestStopsTo(lat, lng, radiusM = 600, maxN = 8) {
    const stops = state.stops || {};
    const out = [];
    for (const [id, s] of Object.entries(stops)) {
      const d = distanceM(lat, lng, s.la, s.lg);
      if (d <= radiusM) out.push({ id, distance: d, ...s });
    }
    out.sort((a, b) => a.distance - b.distance);
    return out.slice(0, maxN);
  }

  // Resolve an endpoint to a list of candidate boarding/alighting stops
  // with walking distance attached.
  //
  // Behaviour change (2026-05): even when the user explicitly picked a
  // specific stop from the dropdown, the planner now treats that pick as
  // a *location* and radiates out to nearby transit stops within walking
  // range. This matches Google Maps / Citymapper behaviour: typing
  // "永利澳門" should find any nearby bus stop or shuttle pickup, not just
  // the exact MOSC_WMC kerb the user happened to highlight. Address /
  // Nominatim picks already worked this way; stop picks did not.
  async function endpointToStops(end) {
    await ensureStopsLoaded();
    if (end.lat == null || end.lng == null) return [];
    return nearestStopsTo(end.lat, end.lng, 600, 8);
  }

  // Multi-stop search: for every pair (oStop, dStop) in the cross-product of
  // walking-range stops at each endpoint, look for direct routes. Sort by
  // total wall-time = walk + transit (rough estimate).
  async function planTripMulti(fromEnd, toEnd) {
    const sr = await ensureStopRoutesLoaded();
    const fromStops = await endpointToStops(fromEnd);
    const toStops   = await endpointToStops(toEnd);
    if (!fromStops.length || !toStops.length) return { direct: [] };

    // Track best (fewest-hops) result per route_key so we don't list the
    // same route 6 times boarding from 6 nearby stops.
    const byRoute = new Map();
    // Macau modes have only direction-1 geometry on file but the underlying
    // service runs both ways (LRT trains, casino shuttles, DSAT buses
    // travelling the same route number). Treat them as bidirectional in
    // the planner so a request from "stop later in the sequence" → "stop
    // earlier" still finds the route. HK bus / MTR direction is enforced
    // because those have separate _2.json geometry per direction.
    const isBidir = (co) => co === "MOSC" || co === "LRT" || co === "MOB";
    // Build pairs of (origin route → dest route) candidates only when they
    // actually share a route key.
    for (const oStop of fromStops) {
      const oRoutes = new Set(sr[oStop.id] || []);
      for (const dStop of toStops) {
        const dRoutes = new Set(sr[dStop.id] || []);
        for (const rk of oRoutes) {
          if (!dRoutes.has(rk)) continue;
          const route = state.routes.find((r) => r.rk === rk);
          if (!route) continue;
          for (const d of (route.dirs && route.dirs.length ? route.dirs : [1])) {
            try {
              const geo = await fetchJson(`${DATA_BASE}/geometry/${rk}_${d}.json`);
              const stops = geo.stops || [];
              const fIdx = stops.findIndex((s) => s.stop_id === oStop.id);
              const tIdx = stops.findIndex((s) => s.stop_id === dStop.id);
              if (fIdx < 0 || tIdx < 0 || tIdx === fIdx) continue;
              if (!isBidir(route.co) && tIdx < fIdx) continue;
              const hops = Math.abs(tIdx - fIdx);
              // Rough total-time estimate: walking ~5 km/h (12 m/min), each
              // bus stop ~1.5 min, MTR station ~2 min.
              const transitPerStop = route.co === "MTR" ? 2 : 1.5;
              const walkMin = (oStop.distance + dStop.distance) / 80;
              const total = walkMin + hops * transitPerStop;
              const key = `${rk}_${d}`;
              const candidate = {
                route, dir: d,
                board: { id: oStop.id, name: stops[fIdx].stop_name_tc || stops[fIdx].stop_name, distance: oStop.distance },
                alight: { id: dStop.id, name: stops[tIdx].stop_name_tc || stops[tIdx].stop_name, distance: dStop.distance },
                hops, walkMin, totalMin: total,
              };
              if (!byRoute.has(key) || byRoute.get(key).totalMin > total) {
                byRoute.set(key, candidate);
              }
            } catch (e) { /* missing geometry: skip */ }
          }
        }
      }
    }

    const direct = [...byRoute.values()].sort((a, b) =>
      a.totalMin - b.totalMin || compareRouteIds(a.route.id, b.route.id)
    );

    // 1-interchange: route_A from origin-area → shared stop → route_B to
    // dest-area. Only attempted when no direct option exists or when the
    // best direct is slow (so cheap interchanges can outperform).
    let interchange = [];
    if (!direct.length || direct[0].totalMin > 25) {
      interchange = await planOneInterchange(fromStops, toStops, sr);
    }

    return { direct, interchange };
  }

  async function planOneInterchange(fromStops, toStops, sr) {
    const out = [];
    // For each origin-area stop, the routes that serve it
    const fromRouteCands = new Map();
    for (const oStop of fromStops) {
      for (const rk of (sr[oStop.id] || [])) {
        if (!fromRouteCands.has(rk)) fromRouteCands.set(rk, []);
        fromRouteCands.get(rk).push(oStop);
      }
    }
    const toRouteCands = new Map();
    for (const dStop of toStops) {
      for (const rk of (sr[dStop.id] || [])) {
        if (!toRouteCands.has(rk)) toRouteCands.set(rk, []);
        toRouteCands.get(rk).push(dStop);
      }
    }

    // Cap how many candidate first-leg routes we explore so the
    // cross-product stays manageable.
    const fromKeys = [...fromRouteCands.keys()].slice(0, 8);
    const toKeys   = new Set(toRouteCands.keys());

    for (const rkA of fromKeys) {
      const routeA = state.routes.find((r) => r.rk === rkA);
      if (!routeA) continue;
      for (const dirA of (routeA.dirs && routeA.dirs.length ? routeA.dirs : [1])) {
        let geoA;
        try { geoA = await fetchJson(`${DATA_BASE}/geometry/${rkA}_${dirA}.json`); }
        catch { continue; }
        const aStops = geoA.stops || [];
        // Build a fast lookup: stop_id → index on route A
        const aIdx = new Map();
        aStops.forEach((s, i) => aIdx.set(s.stop_id, i));

        for (const oStop of fromRouteCands.get(rkA) || []) {
          const oIdx = aIdx.get(oStop.id);
          if (oIdx == null) continue;
          // For each subsequent stop on A (after oIdx), check whether that
          // stop is served by any route that also reaches dest area.
          for (let j = oIdx + 1; j < aStops.length; j++) {
            const interStopId = aStops[j].stop_id;
            const interRoutes = sr[interStopId] || [];
            for (const rkB of interRoutes) {
              if (rkB === rkA) continue;
              if (!toKeys.has(rkB)) continue;
              const routeB = state.routes.find((r) => r.rk === rkB);
              if (!routeB) continue;
              for (const dirB of (routeB.dirs && routeB.dirs.length ? routeB.dirs : [1])) {
                let geoB;
                try { geoB = await fetchJson(`${DATA_BASE}/geometry/${rkB}_${dirB}.json`); }
                catch { continue; }
                const bStops = geoB.stops || [];
                const bIdx = bStops.findIndex((s) => s.stop_id === interStopId);
                if (bIdx < 0) continue;
                for (const dStop of toRouteCands.get(rkB) || []) {
                  const tIdx = bStops.findIndex((s) => s.stop_id === dStop.id);
                  if (tIdx <= bIdx) continue;
                  const hopsA = j - oIdx;
                  const hopsB = tIdx - bIdx;
                  const transitMin = (routeA.co === "MTR" ? 2 : 1.5) * hopsA
                                   + (routeB.co === "MTR" ? 2 : 1.5) * hopsB
                                   + 4;  // transfer penalty
                  const walkMin = (oStop.distance + dStop.distance) / 80;
                  const total = walkMin + transitMin;
                  out.push({
                    type: "interchange",
                    totalMin: total,
                    walkMin,
                    legA: {
                      route: routeA, rk: rkA, dir: dirA,
                      boardId: oStop.id, alightId: interStopId,
                      boardName: aStops[oIdx].stop_name_tc || aStops[oIdx].stop_name,
                      alightName: aStops[j].stop_name_tc || aStops[j].stop_name,
                      hops: hopsA,
                    },
                    legB: {
                      route: routeB, rk: rkB, dir: dirB,
                      boardId: interStopId, alightId: dStop.id,
                      boardName: bStops[bIdx].stop_name_tc || bStops[bIdx].stop_name,
                      alightName: bStops[tIdx].stop_name_tc || bStops[tIdx].stop_name,
                      hops: hopsB,
                    },
                    board:  { id: oStop.id, distance: oStop.distance },
                    alight: { id: dStop.id, distance: dStop.distance },
                  });
                  // Cap results per (rkA, rkB) at 1 to avoid cross-product
                  // explosion.
                  break;
                }
                break;
              }
            }
            // Cap interchange depth per origin-leg.
            if (out.length > 30) break;
          }
        }
      }
      if (out.length > 30) break;
    }
    out.sort((a, b) => a.totalMin - b.totalMin);
    return out.slice(0, 6);
  }

  function renderPlanResults(trips, fromEnd, toEnd) {
    const el = $("yuu-plan-results");
    const direct = trips.direct || [];
    const inter  = trips.interchange || [];

    // Taxi is always offered as a fallback row — even when transit options
    // exist, the user wants to compare against a "what would a cab cost?"
    // baseline. Coordinates come from the plan endpoints (geocoded address
    // or stop), so this is independent of whether a transit route was
    // found.
    const taxi = (fromEnd?.lat != null && toEnd?.lat != null)
      ? estimateTaxi(fromEnd.lat, fromEnd.lng, toEnd.lat, toEnd.lng)
      : null;
    const taxiCard = taxi ? `<div class="yuu-plan-card yuu-plan-card-taxi">
      <div class="yuu-plan-card-head" style="--card-color:#444">
        <span class="yuu-badge" style="background:#444;color:#fff">Taxi</span>
        <div class="yuu-plan-card-meta">
          <span class="yuu-plan-card-co">${taxi.region === "hk" ? "Hong Kong urban" : "Macau"} · ~${taxi.roadKm} km</span>
          <span class="yuu-plan-card-direction">≈ ${taxi.minutes} min</span>
        </div>
        <span class="yuu-plan-card-fare">${escapeHtml(taxi.str)}</span>
      </div>
      <div class="yuu-plan-card-body">
        <span class="yuu-plan-card-leg">Estimate only — flag-fall + per-km tariff, no surcharges.</span>
      </div>
    </div>` : "";

    if (!direct.length && !inter.length) {
      el.innerHTML = taxiCard
        ? `<div class="yuu-plan-empty">No transit route found between these endpoints.</div>` +
          `<div class="yuu-plan-section-title yuu-plan-taxi-title">Taxi instead</div>${taxiCard}`
        : `<div class="yuu-plan-empty">No route found between these endpoints.</div>`;
      return;
    }

    const interHtml = inter.map((t) => {
      const a = t.legA, b = t.legB;
      const ca = routeColor(a.route), cb = routeColor(b.route);
      const fareA = fareEstimate(a.route, a.hops);
      const fareB = fareEstimate(b.route, b.hops);
      const fareLine = (fareA || fareB)
        ? `<span class="yuu-plan-card-fare-pair">${fareA?.str || ""}${fareA && fareB ? " + " : ""}${fareB?.str || ""}</span>`
        : "";
      return `<div class="yuu-plan-card yuu-plan-card-inter">
        <div class="yuu-plan-card-head" style="--card-color:${ca}">
          <span class="yuu-plan-card-stack">
            <span class="yuu-badge ${a.route.co}" style="background:${ca};color:#fff">${escapeHtml(a.route.id)}</span>
            <span class="yuu-plan-card-arrow">→</span>
            <span class="yuu-badge ${b.route.co}" style="background:${cb};color:#fff">${escapeHtml(b.route.id)}</span>
          </span>
          <div class="yuu-plan-card-meta">
            <span class="yuu-plan-card-co">1 transfer ${fareLine}</span>
            <span class="yuu-plan-card-direction">→ ${escapeHtml(displayEn(b.alightName || ""))}</span>
          </div>
          <span class="yuu-plan-card-hops">${Math.round(t.totalMin)} min</span>
        </div>
        <div class="yuu-plan-card-body yuu-plan-card-legs">
          <div>① ${escapeHtml(a.route.id)} · ${escapeHtml(a.boardName)} → ${escapeHtml(a.alightName)} (${a.hops})</div>
          <div>② ${escapeHtml(b.route.id)} · ${escapeHtml(b.boardName)} → ${escapeHtml(b.alightName)} (${b.hops})</div>
        </div>
      </div>`;
    }).join("");

    // Transit options first (sorted by time), taxi at the bottom as a
    // baseline-compare card.
    const summary = `<div class="yuu-plan-section-title">${direct.length + inter.length} transit option${(direct.length + inter.length) === 1 ? "" : "s"} · sorted by total time</div>`;
    const transitHtml = direct.slice(0, 6).map((t) => {
      const rc = routeColor(t.route);
      const opName = COMPANY_LABEL[t.route.co] || t.route.co;
      const dirLabel = (t.dir === 1 ? t.route.de : t.route.oe) || "";
      const totalTxt = `${Math.round(t.totalMin)} min`;
      const walkParts = [];
      if (t.board.distance > 50)  walkParts.push(`Walk ${Math.round(t.board.distance)} m to board`);
      if (t.alight.distance > 50) walkParts.push(`walk ${Math.round(t.alight.distance)} m at end`);
      const walkLine = walkParts.length ? `<div class="yuu-plan-card-walk">🚶 ${walkParts.join(" · ")}</div>` : "";
      const fare = fareEstimate(t.route, t.hops);
      return `<div class="yuu-plan-card">
        <div class="yuu-plan-card-head" style="--card-color:${rc}">
          <span class="yuu-badge ${t.route.co}" style="background:${rc};color:#fff">${escapeHtml(t.route.id)}</span>
          <div class="yuu-plan-card-meta">
            <span class="yuu-plan-card-co">${escapeHtml(opName)}</span>
            <span class="yuu-plan-card-direction">→ ${escapeHtml(displayEn(dirLabel))}</span>
          </div>
          ${fare ? `<span class="yuu-plan-card-fare">${escapeHtml(fare.str)}</span>` : ""}
          <span class="yuu-plan-card-hops">${escapeHtml(totalTxt)}</span>
        </div>
        <div class="yuu-plan-card-body">
          <span class="yuu-plan-card-leg">${escapeHtml(t.board.name || "")} → ${escapeHtml(t.alight.name || "")} · ${t.hops} stop${t.hops === 1 ? "" : "s"}</span>
          <button type="button" class="yuu-plan-open" data-rk="${escapeHtml(t.route.rk)}" data-dir="${t.dir}">View →</button>
        </div>
        ${walkLine}
      </div>`;
    }).join("") + interHtml;

    const taxiSection = taxiCard
      ? `<div class="yuu-plan-section-title yuu-plan-taxi-title">Or take a taxi</div>${taxiCard}`
      : "";

    el.innerHTML = summary + transitHtml + taxiSection;

    el.querySelectorAll(".yuu-plan-open").forEach((btn) => {
      btn.addEventListener("click", () => {
        const route = state.routes.find((r) => r.rk === btn.dataset.rk);
        if (!route) return;
        activateTab(route.co === "MTR" ? "mtr" : "bus");
        state.selectedDirection = Number(btn.dataset.dir) || 1;
        selectRoute(route);
      });
    });

    // Draw the top option (cheapest) on the Plan map.
    ensurePlanMapRendered();
    const top = direct[0] || inter[0];
    if (top) drawPlanOnMap(top, fromEnd, toEnd);
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
    state.selectedRoute = route;
    state.selectedStop = null;
    // Auto-switch to the matching tab + region so picking a Macau route
    // from a HK tab's search box flips the user to the right context.
    const desiredTab = (() => {
      for (const [tab, set] of Object.entries(TAB_COMPANIES)) {
        if (set.has(route.co)) return tab;
        if (route.partners && route.partners.some((p) => set.has(p.co))) return tab;
      }
      return "bus";
    })();
    const desiredRegion = TAB_REGION[desiredTab] || "hk";
    if (state.activeRegion !== desiredRegion && desiredRegion !== "any") {
      activateRegion(desiredRegion);
    }
    if (state.activeTab !== desiredTab) activateTab(desiredTab);

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
    } else if (route.color) {
      // LRT lines and casino shuttles carry per-route brand colour.
      yuu.dataset.joint = "false";
      yuu.style.setProperty("--yuu-route-color", route.color);
      yuu.style.setProperty("--yuu-route-color-soft", withAlpha(route.color, 0.18));
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

    const parts = [];
    parts.push(`<span class="yuu-op-text">${escapeHtml(opNames)}</span>`);
    badges.forEach((b) => {
      parts.push(`<span class="yuu-schedule-chip">${escapeHtml(b.en)} · ${escapeHtml(b.tc)}</span>`);
    });
    // Macau modes (MOB / LRT / MOSC) carry static frequency / operating-hours
    // strings from the curated JSON since no live ETA API exists for them.
    // Surface a "next bus ~Xmin" estimate when within service window so the
    // user gets a one-glance answer without doing the math.
    const nextDep = nextDepartureEstimate(route);
    const clock   = nextDepartureClockTimes(route, 3);
    if (nextDep) {
      if (nextDep.kind === "running" && clock?.length) {
        parts.push(`<span class="yuu-schedule-chip yuu-next-chip" title="Synthesised from frequency + hours — actual times may shift slightly">⏱ ${escapeHtml(clock.join(" · "))}</span>`);
        parts.push(`<span class="yuu-schedule-chip">last ${nextDep.lastHHMM}</span>`);
      } else if (nextDep.kind === "running") {
        parts.push(`<span class="yuu-schedule-chip yuu-next-chip">⏱ Next ~${nextDep.nextMin} min · last ${nextDep.lastHHMM}</span>`);
      } else {
        parts.push(`<span class="yuu-schedule-chip yuu-next-chip yuu-next-closed">Closed · service ${nextDep.firstHHMM}–${nextDep.lastHHMM}</span>`);
      }
    }
    if (route.frequency && !nextDep) {
      parts.push(`<span class="yuu-schedule-chip">${escapeHtml(route.frequency)}</span>`);
    }
    if (route.hours && !nextDep) {
      parts.push(`<span class="yuu-schedule-chip">${escapeHtml(route.hours)}</span>`);
    }
    if (route.casino) {
      parts.push(`<span class="yuu-schedule-chip" style="background:${route.color || '#a89060'};color:#fff;border-color:transparent">${escapeHtml(route.casino)}</span>`);
    }
    const fare = fareEstimate(route);
    if (fare) {
      parts.push(`<span class="yuu-schedule-chip yuu-fare-chip" title="Approximate fare">${escapeHtml(fare.str)}</span>`);
    }
    if (allApprox) {
      parts.push(`<span class="yuu-schedule-chip yuu-approx-chip" title="Coordinates are best-effort">Approximate · 路線僅供參考</span>`);
    }
    // The right side of the toolbar carries: ⇆ swap-direction (when route
    // has both directions), then the relative-time freshness label, then
    // the ↻ refresh button. They sit on the same row as the operator name
    // and schedule chips so we don't waste a separate row.
    parts.push(`<span class="yuu-route-actions">`);
    if (dirs.length > 1) {
      parts.push(
        `<button type="button" class="yuu-dir-toggle" title="Swap direction" aria-label="Swap direction">⇆</button>`
      );
    }
    parts.push(
      `<span class="yuu-eta-fresh" id="yuu-eta-fresh"></span>` +
      `<button type="button" id="yuu-eta-refresh" class="yuu-refresh-btn" title="Refresh now" aria-label="Refresh ETA">↻</button>`
    );
    parts.push(`</span>`);
    host.innerHTML = parts.join("");

    // Freshness + refresh are only relevant when a stop is selected.
    const actions = host.querySelector(".yuu-route-actions");
    if (actions) actions.dataset.hasStop = state.selectedStop ? "true" : "false";
    tickFreshness();

    const swap = host.querySelector(".yuu-dir-toggle");
    if (swap) {
      swap.addEventListener("click", () => {
        bumpActivity();
        if (!state.selectedRoute || dirs.length < 2) return;
        const next = state.selectedDirection === 1 ? 2 : 1;
        if (!dirs.includes(next)) return;
        state.selectedDirection = next;
        state.selectedStop = null;
        $("yuu-eta").hidden = true;
        stopEtaPolling();
        renderRouteChips(state.selectedRoute);
        updateRouteTitle();
        loadDirection({ autoFlip: false });
      });
    }

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
    if (row) {
      // Always insert ETA inline after the selected stop row (desktop + mobile).
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
    state.map = L.map("yuu-map", {
      zoomControl: true,
      maxBoundsViscosity: 0.85,
    }).setView([22.3193, 114.1694], 11);
    // Voyager: colourful CARTO basemap — faster than osm.org and friendlier
    // on the eye than light_all (which was grayscale).
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: "abcd",
      maxZoom: 20,
    }).addTo(state.map);
    state.map.setMaxBounds(HK_TIGHT_BOUNDS);
  }

  function companyColor(co) {
    return ({
      KMB: "#e63946",
      CTB: "#f5b800",  // slightly darker yellow for better legibility on maps
      GMB: "#2a9d8f",
      MTRB: "#1d3557",
      RMB: "#d62828",
      MTR:  "#1d3557",  // generic; per-line override below
      MOB:  "#0e7c66",  // TCM/Transmac green
      LRT:  "#00a651",  // MLM Taipa Line green
      MOSC: "#a89060",  // gold-ish for casino shuttles (per-route override)
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
    // LRT lines and casino shuttles carry their own brand colour from the
    // export — see data/01_raw/macau_lrt.json and macau_shuttles.json.
    if (route.color) return route.color;
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
    if (!sameStop) {
      $("yuu-eta-list").innerHTML = '<li class="yuu-eta-empty">Loading…</li>';
      const f = $("yuu-eta-fresh");
      if (f) f.textContent = "";
    }
    // Mark the chip toolbar so refresh + freshness become visible.
    const actions = document.querySelector(".yuu-route-actions");
    if (actions) actions.dataset.hasStop = "true";

    if (state.selectedStopLayer) state.map.removeLayer(state.selectedStopLayer);
    const color = routeColor(state.selectedRoute);
    if (typeof stop.lat === "number" && typeof stop.lng === "number") {
      state.selectedStopLayer = L.circleMarker([stop.lat, stop.lng], {
        radius: 10, fillColor: color,
        color: "#ffffff", weight: 4, fillOpacity: 1,
      }).addTo(state.map);
      // Skip the map-marker popup on mobile — the ETA is already shown
      // inline under the stop row, so the popup just steals viewport.
      if (!window.matchMedia("(max-width: 768px)").matches) {
        const labels = splitStopLabels(stop);
        state.selectedStopLayer
          .bindPopup(
            `<div class="yuu-map-popup">` +
            `<strong><span class="yuu-map-popup-seq">${stop.sequence}</span> ${escapeHtml(labels.tc || labels.en)}</strong>` +
            (labels.tc ? `<div class="yuu-map-popup-en">${escapeHtml(labels.en)}</div>` : "") +
            `<ol class="yuu-map-popup-eta"><li class="yuu-eta-empty">Loading…</li></ol></div>`,
            { maxWidth: 260, className: "yuu-popup-wrap" }
          )
          .openPopup();
      }
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
    // Refresh button is rendered inside the chip toolbar by renderRouteChips
    // and is therefore replaced on every direction switch / route change.
    // Use event delegation so the click handler always works.
    document.addEventListener("click", (e) => {
      const btn = e.target.closest("#yuu-eta-refresh");
      if (!btn) return;
      bumpActivity();
      if (!state.selectedStop) return;
      btn.classList.add("spinning");
      pollEta().finally(() => {
        setTimeout(() => btn.classList.remove("spinning"), 400);
      });
    });
    // Re-render the "X seconds ago" label every few seconds so freshness
    // is always accurate without re-rendering the whole ETA list.
    state.freshTickTimer = setInterval(tickFreshness, 5000);
  }

  function tickFreshness() {
    const fresh = $("yuu-eta-fresh");
    if (!fresh) return;
    const t = state.lastEtaUpdateAt;
    if (!t) { fresh.textContent = ""; return; }
    const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (sec < 5)        fresh.textContent = "Just now";
    else if (sec < 60)  fresh.textContent = `${sec} sec ago`;
    else if (sec < 3600) {
      const m = Math.floor(sec / 60);
      fresh.textContent = `${m} min${m === 1 ? "" : "s"} ago`;
    } else {
      const h = Math.floor(sec / 3600);
      fresh.textContent = `${h} hr${h === 1 ? "" : "s"} ago`;
    }
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
    if (!errorMsg) {
      state.lastEtaUpdateAt = Date.now();
      tickFreshness();
    } else {
      $("yuu-eta-fresh").textContent = "";
    }

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
    // Time pills only — the route header above already shows the
    // origin → destination pair, so per-row destination text was redundant.
    // Operator tag is preserved for joint routes so users can tell which
    // operator's bus is arriving when KMB and Citybus run the same route.
    const isJoint = state.selectedRoute.partners && state.selectedRoute.partners.length > 1;
    list.innerHTML = valid.slice(0, 6).map((e) => {
      const mins = etaMinutes(e.eta);
      const arriving = mins !== null && mins <= 0;
      const cls = arriving ? "yuu-arriving" : (e.scheduled ? "yuu-scheduled" : "yuu-live");
      const badge = e.scheduled ? "⏱" : "⚡";
      const kind = e.scheduled ? "Scheduled" : "Live";
      const op = (isJoint && e._co)
        ? `<span class="yuu-eta-op">${escapeHtml(e._co)}</span>`
        : "";
      return `<li class="yuu-eta-item">
        <span class="yuu-eta-time ${cls}" title="${kind}">${op}${badge} ${escapeHtml(etaText(e.eta))}</span>
      </li>`;
    }).join("");

    // Mirror the top entries into the map marker's popup so users tapping
    // a stop on the map see the live ETA right there.
    updateMarkerPopup(valid);
  }

  function updateMarkerPopup(etas) {
    if (!state.selectedStopLayer) return;
    // Mobile suppresses the popup entirely; nothing to update.
    if (window.matchMedia("(max-width: 768px)").matches) return;
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
