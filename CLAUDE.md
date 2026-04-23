# CLAUDE.md — YuuTraffic

Guidance for Claude Code working in this repo. For user-facing project docs see `README.md`.

## Project at a glance

- Streamlit app (`app.py`) for Hong Kong public transport: KMB, Citybus, GMB, MTR Bus, MTR rail, Light Rail, red minibus. This Python app is the **local reference implementation**.
- Public site is a **pure-static JavaScript port** served by GitHub Pages at `yutsang.github.io/yuutraffic/`. It shares the same data pipeline but rewrites the UI in JS because Python doesn't run in the browser.
- Metadata lives in SQLite (`data/01_raw/kmb_data.db`, ~6 MB). Route geometry is precomputed JSON under `data/02_intermediate/route_geometry/`. Live ETA is fetched from HK gov APIs — from the Streamlit backend locally, from the browser on the static site.
- Python ≥3.10. Package installed with `pip install -e .`.

## Local dev (Streamlit app)

```bash
pip install -e .
yuutraffic --update    # first run only
yuutraffic             # starts Streamlit on :8508
```

## Deployment — GitHub Pages (pure static, $0 forever, locally driven)

### Architecture

```
Local Mac (the user)
  └─ ./scripts/publish.sh (weekly, manual)
     ├─ yuutraffic --update      (refreshes SQLite + geometry from HK gov APIs)
     ├─ scripts/export_static.py (SQLite → JSON bundles in web/data/)
     ├─ rsync web/ → gh-pages worktree, git push origin gh-pages
     └─ if YUU_PERSONAL_SITE_PATH is set: rsync web/ → that folder too

GitHub Pages
  └─ yutsang.github.io/yuutraffic/
      ├─ index.html, app.js, style.css
      └─ data/ (routes.json, stops.json, geometry/*.json)

User's browser
  ├─ loads UI + static data from GH Pages (cached after first load)
  └─ fetches LIVE ETA directly from:
       data.etabus.gov.hk      (KMB)
       rt.data.gov.hk          (MTR rail, LR, MTR Bus, Citybus)
       data.etagmb.gov.hk      (GMB)
     All confirmed CORS-open (access-control-allow-origin: *).
```

No backend, no Docker, no cloud spend, no cron on anything but the user's Mac. Frontend-only edits (HTML/CSS/JS) can also deploy via GH Actions on push to main — those don't need data refresh.

### Why not GitHub Actions for the full refresh?

We tried; it times out. `yuutraffic --update` takes 2+ hours on US GitHub runners because KMB's bulk `/stop` endpoint returns 403 to non-HK IPs, forcing per-stop fallback (~80 stops/min for 6649 stops). From HK (user's Mac) the same update finishes in 10–20 minutes.

### Cost

**$0 forever.** GitHub Pages serves unlimited bandwidth for static content; Actions on public repos has unlimited minutes (but we only use it for frontend-only redeploys).

### Files in this layout

- `scripts/publish.sh` — **the weekly command.** One-shot: update → export → push gh-pages → optional mirror.
- `scripts/export_static.py` — converts SQLite → lean JSON for the browser.
- `.github/workflows/deploy-demo.yml` — frontend-only redeploys on push to main touching `web/*.html|css|js`. Pulls existing data from gh-pages, overlays new frontend code, republishes. No `--update`.
- `web/` — static frontend (index.html, app.js, style.css).
- `web/data/` — generated locally by `publish.sh`; gitignored. Only exists on gh-pages.
- `.gh-pages-worktree/` — auto-managed git worktree used by `publish.sh`; gitignored.

### Manual route overrides

Some routes need manual corrections (especially MTR Bus stop labels). Existing pattern:
- `data/01_raw/mtr_bus_stop_overrides.json` — per-stop name overrides.
- Future: any per-route geometry adjustments → similar JSON files under `data/01_raw/`.

Workflow for manual edits:
1. Edit the override JSON.
2. Run `./scripts/publish.sh` — `yuutraffic --update` respects overrides when it regenerates the DB.
3. Verify on `yutsang.github.io/yuutraffic/` after push.

### Mirror to personal site

The publish script optionally rsyncs the built `web/` tree into a folder on the user's personal site repo. Set once in shell rc:

```bash
export YUU_PERSONAL_SITE_PATH=~/Desktop/Github/yutsang.github.io/projects/yuutraffic
```

Then `publish.sh` copies there automatically. User commits + pushes the personal site separately (script doesn't touch that repo's git state to avoid surprises).

### Rollback

```bash
git log --oneline origin/gh-pages -n 10
git push origin <good-sha>:gh-pages --force   # only if the user authorises
```

## Conventions

- Streamlit app entry is `app.py` at root; multi-page files live in `pages/`.
- Config is YAML under `conf/base/parameters.yml`, loaded via `yuutraffic.config.load_config()`.
- Tests use pytest; run with `pytest tests/`.
- CI formatting/linting: Black, isort, Ruff. Enforced by `.github/workflows/ci-cd.yml`.
- Web frontend is **vanilla JS + Leaflet** (no build step, no npm, no framework) — keeps GH Pages publishing trivial and matches the "zero tooling" goal.
