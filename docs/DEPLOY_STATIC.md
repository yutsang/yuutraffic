# Demo site deployment (GitHub Pages, pure static, $0 forever)

YuuTraffic also ships as a **browser-only** widget at `yutsang.github.io/yuutraffic/`. It reuses the same nightly data pipeline as the Streamlit app but rewrites the UI in vanilla JS so it can run on GitHub Pages without a backend.

## Architecture in one breath

```
GitHub Actions (nightly 02:00 HKT)
  ├─ yuutraffic --update             (refreshes SQLite + geometry)
  ├─ scripts/export_static.py         (writes web/data/{routes,stops,meta}.json + geometry/*.json)
  └─ peaceiris/actions-gh-pages       (publishes web/ to gh-pages branch)

GitHub Pages → yutsang.github.io/yuutraffic/
Browser loads UI + static data, fetches live ETA straight from:
  data.etabus.gov.hk (KMB), rt.data.gov.hk (CTB/MTR), data.etagmb.gov.hk (GMB)
```

## Enabling GitHub Pages (one-time)

1. Push `.github/workflows/deploy-demo.yml`, `scripts/export_static.py`, and `web/` to `main`.
2. **Settings → Pages** on the repo:
   - Source: **Deploy from a branch**
   - Branch: **`gh-pages`** (will appear after first successful workflow run)
   - Folder: **`/ (root)`**
3. Manually trigger the first build:
   ```bash
   gh workflow run "Deploy demo site"
   gh run watch
   ```
   First run takes ~15–30 min (the full `yuutraffic --update` against HK gov APIs).
4. Once green, the demo is live at **`https://yutsang.github.io/yuutraffic/`**.

## Triggers

| When | What runs |
|---|---|
| Daily 02:00 HKT (cron) | Full refresh + redeploy. |
| Manual dispatch | Full refresh unless `skip_update=true`. |
| Push to `main` touching `web/**` or `scripts/export_static.py` | Frontend-only redeploy (reuses last published data, no API hammering). |

## Local development

You don't need to push to iterate on the frontend. Run a local static server:

```bash
# one-time: populate data by running the Streamlit app's update at least once
yuutraffic --update
python scripts/export_static.py

# serve web/ directly
cd web && python -m http.server 8080
# open http://localhost:8080
```

## Local data sync from the demo site

Rather than running a full `yuutraffic --update` locally (slow), you can pull the pre-built bundles from gh-pages:

```bash
curl -o web/data/routes.json   https://yutsang.github.io/yuutraffic/data/routes.json
curl -o web/data/stops.json    https://yutsang.github.io/yuutraffic/data/stops.json
curl -o web/data/meta.json     https://yutsang.github.io/yuutraffic/data/meta.json
# geometry/*.json — copy the ones you need, or rsync via git:
git clone --depth 1 --branch gh-pages git@github.com:yutsang/yuutraffic.git /tmp/pages
cp -a /tmp/pages/data/geometry/. web/data/geometry/
```

## Manual route adjustments

The nightly job respects existing override files under `data/01_raw/`, e.g. `mtr_bus_stop_overrides.json`. To fix something:

1. Edit the override JSON locally.
2. `yuutraffic --update` to verify the fix applies to the SQLite + geometry.
3. Commit the override and push. The nightly job picks it up; the demo reflects the change within 24h (or trigger `gh workflow run "Deploy demo site"` for instant rebuild).

> **Note:** `data/**` is gitignored by default. To commit an override file, un-ignore that specific path (e.g. add `!data/01_raw/mtr_bus_stop_overrides.json` to `.gitignore`) or stage it with `git add -f`.

## Embedding on your main site

Once the demo confirms acceptable performance, integrate into `ytsang.com`:

### Option 1 — iframe (zero JS)
```html
<iframe src="https://yutsang.github.io/yuutraffic/"
        style="width:100%; height:800px; border:none;"
        loading="lazy"
        title="YuuTraffic"></iframe>
```

### Option 2 — theme inheritance
The widget exposes CSS variables (see `web/style.css`). Override them from your main site by injecting a stylesheet before `style.css` loads, or by linking the host site's stylesheet via a query param. Future work.

## Rollback

```bash
# list recent gh-pages commits
git log --oneline origin/gh-pages -n 10

# revert to a specific commit
git push origin <good-sha>:gh-pages --force
```

Or re-run the workflow after reverting the source commit on `main`.
