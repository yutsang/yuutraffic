# Demo site deployment (GitHub Pages, pure static, $0 forever)

YuuTraffic's public demo is a **browser-only** widget at `yutsang.github.io/yuutraffic/`. It reuses the Python app's data pipeline but rewrites the UI in vanilla JS so it can run on GitHub Pages without a backend.

## Architecture in one breath

```
Local Mac (weekly, manual)
  └─ ./scripts/publish.sh
     ├─ yuutraffic --update         (refreshes SQLite + geometry in HK, ~10–20 min)
     ├─ scripts/export_static.py     (writes web/data/{routes,stops,meta}.json + geometry/*.json)
     ├─ rsync web/ → gh-pages worktree → git push origin gh-pages
     └─ rsync web/ → $YUU_PERSONAL_SITE_PATH (if set)

GitHub Pages → yutsang.github.io/yuutraffic/
Browser loads UI + static data, fetches live ETA straight from:
  data.etabus.gov.hk (KMB), rt.data.gov.hk (CTB/MTR), data.etagmb.gov.hk (GMB)
```

## Why local, not GitHub Actions?

We tried. `yuutraffic --update` takes 2+ hours on US GitHub runners because KMB's bulk `/stop` endpoint returns 403 to non-HK IPs and the code falls back to per-stop calls (~80 stops/min for 6649 stops). From your Mac in Hong Kong, the same update finishes in **10–20 minutes**.

GitHub Actions is still used, just for **frontend-only** redeploys — see `.github/workflows/deploy-demo.yml`.

## One-time setup

### 1. First publish (seeds the `gh-pages` branch)

From the repo root on your Mac:

```bash
pip install -e .             # if not already
./scripts/publish.sh         # ~15 min total
```

First run handles everything:
- Creates the orphan `gh-pages` branch automatically.
- Runs `yuutraffic --update` (full transport data fetch).
- Exports JSON bundles.
- Pushes to `gh-pages`.

### 2. Enable GitHub Pages

After the first push:

1. `https://github.com/yutsang/yuutraffic/settings/pages`
2. **Source:** Deploy from a branch
3. **Branch:** `gh-pages` · Folder: `/ (root)` · **Save**
4. Wait ~1 min → visit `https://yutsang.github.io/yuutraffic/`

### 3. (Optional) Enable personal-site mirror

Add to `~/.zshrc` (or `~/.bashrc`):

```bash
export YUU_PERSONAL_SITE_PATH=~/Desktop/Github/yutsang.github.io/projects/yuutraffic
```

Reload the shell. Future `publish.sh` runs will rsync `web/` there automatically. You still commit + push in the personal-site repo yourself.

## Weekly workflow

Run this once a week (or whenever you edit override JSONs):

```bash
cd ~/Desktop/Github/yuutraffic
./scripts/publish.sh
```

Flags:
- `--skip-update` — reuse existing local data (frontend-only republish)
- `--no-mirror` — skip the personal-site sync even if env var is set

## Manual route adjustments

1. Edit override JSON under `data/01_raw/` (e.g. `mtr_bus_stop_overrides.json`).
2. `./scripts/publish.sh` — `yuutraffic --update` picks up overrides during the regenerate step.
3. Verify at `yutsang.github.io/yuutraffic/`.

## Embedding on your main site

Once the demo URL is confirmed working, drop this into your project detail page:

```html
<iframe src="https://yutsang.github.io/yuutraffic/"
        style="width:100%; height:85vh; border:0; border-radius:12px;"
        loading="lazy"
        title="YuuTraffic"></iframe>
```

Or, if you've set `YUU_PERSONAL_SITE_PATH` to a folder inside your main site repo and committed it, you can link/embed the in-repo copy instead — then the page is served from your own domain without cross-origin concerns.

## Rollback

```bash
git log --oneline origin/gh-pages -n 10
git push origin <good-sha>:gh-pages --force
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `yuutraffic: command not found` | `pip install -e .` in the repo root. |
| `rsync: command not found` | `brew install rsync`. |
| Push rejected (non-fast-forward) | Another machine pushed since your last pull. Run `git -C .gh-pages-worktree pull --rebase` then retry `publish.sh`. |
| 404 at `yutsang.github.io/yuutraffic/` | Check Settings → Pages → confirm `gh-pages` branch is selected and site is marked "Your site is live at…". |
| Geometry missing for a route | `./scripts/publish.sh` again without `--skip-update`. |
