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

## Deployment — GitHub Pages (pure static, $0 forever)

### Architecture

```
GitHub Actions (nightly 00:00 HKT)
  └─ yuutraffic --update        (refreshes SQLite + geometry from HK gov APIs)
  └─ scripts/export_static.py   (SQLite → JSON bundles under web/data/)
  └─ commits refreshed data to main
  └─ copies web/ + web/data/ to gh-pages branch

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

No backend, no Docker, no cloud spend. If HK APIs are down → user sees stale ETA with a clear error; static data unaffected.

### Cost

**$0 forever.** GitHub Actions on a public repo has unlimited minutes; GitHub Pages serves unlimited bandwidth for static content.

### Files in this layout

- `.github/workflows/refresh-data.yml` — nightly cron + manual trigger. Runs update, exports JSON, commits data, publishes gh-pages.
- `scripts/export_static.py` — converts SQLite → lean JSON for the browser.
- `web/` — static frontend (index.html, app.js, style.css, vendor libs).
- `web/data/` — generated each night; not hand-edited.

### Manual route overrides

Some routes need manual corrections (especially MTR Bus stop labels). Existing pattern:
- `data/01_raw/mtr_bus_stop_overrides.json` — per-stop name overrides.
- Future: any per-route geometry adjustments → commit to `data/01_raw/` as an overrides JSON.

Workflow for manual edits:
1. `git pull` — pick up latest auto-refreshed data.
2. Edit the override JSON in `data/01_raw/`.
3. `yuutraffic --update` locally to regenerate geometry + DB with the override applied. Verify in Streamlit.
4. Commit and push. Next nightly job picks it up; the browser version updates within 24h.

### Local sync

`git pull` is enough — the nightly job commits updated `data/01_raw/kmb_data.db` and `data/02_intermediate/route_geometry/*.json` to main. Your Streamlit app picks up the new data without running `--update`.

### Rollback

Data regressions roll back by reverting the latest data commit on `main` and re-running the workflow with `skip_update: true` (dispatch input on the workflow).

## Conventions

- Streamlit app entry is `app.py` at root; multi-page files live in `pages/`.
- Config is YAML under `conf/base/parameters.yml`, loaded via `yuutraffic.config.load_config()`.
- Tests use pytest; run with `pytest tests/`.
- CI formatting/linting: Black, isort, Ruff. Enforced by `.github/workflows/ci-cd.yml`.
- Web frontend is **vanilla JS + Leaflet** (no build step, no npm, no framework) — keeps GH Pages publishing trivial and matches the "zero tooling" goal.
