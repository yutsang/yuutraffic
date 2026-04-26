#!/usr/bin/env bash
# YuuTraffic — one-command publish flow.
#
# Refreshes SQLite + route geometry from HK gov APIs, exports JSON bundles
# for the browser widget, pushes web/ to the gh-pages branch (so
# yutsang.github.io/yuutraffic/ is updated), and optionally mirrors the
# built site into a folder on your personal site repo.
#
# USAGE:
#     ./scripts/publish.sh                # full refresh + publish
#     ./scripts/publish.sh --skip-update  # reuse existing data (frontend-only)
#     ./scripts/publish.sh --no-mirror    # skip the personal-site mirror
#
# OPTIONAL ENV VARS:
#     YUU_PERSONAL_SITE_PATH
#       Absolute path to a folder inside your personal site repo.
#       If set and the folder exists (or its parent does), the built web/
#       directory is rsynced there. You still commit + push that repo
#       separately.
#       Example: YUU_PERSONAL_SITE_PATH=~/Desktop/Github/yutsang.github.io/projects/yuutraffic

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PAGES_WORKTREE="${REPO_ROOT}/.gh-pages-worktree"

SKIP_UPDATE=false
DO_MIRROR=true

for arg in "$@"; do
  case "$arg" in
    --skip-update) SKIP_UPDATE=true ;;
    --no-mirror)   DO_MIRROR=false ;;
    -h|--help)
      sed -n '1,30p' "${BASH_SOURCE[0]}" | sed -n 's/^# \{0,1\}//p'
      exit 0 ;;
    *)
      echo "Unknown flag: $arg" >&2; exit 2 ;;
  esac
done

cd "$REPO_ROOT"

log()  { printf '\033[1;34m▶\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m⚠\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }

# ---- 1. Sanity checks ---------------------------------------------------

if ! command -v git >/dev/null; then
  echo "git is required." >&2; exit 1
fi
if ! command -v rsync >/dev/null; then
  echo "rsync is required (install with: brew install rsync)." >&2; exit 1
fi
if ! command -v yuutraffic >/dev/null; then
  echo "yuutraffic CLI not found. Did you \`pip install -e .\`?" >&2; exit 1
fi

# ---- 2. Refresh transport data ------------------------------------------

if [[ "$SKIP_UPDATE" == "true" ]]; then
  warn "Skipping yuutraffic --update (reusing existing data)."
else
  log "Refreshing transport data (yuutraffic --update) — 10–20 min from HK…"
  time yuutraffic --update
  ok   "Transport data refreshed."
fi

# ---- 3. Export JSON bundles ---------------------------------------------

log "Exporting static bundles for the browser…"
python scripts/export_static.py
ok   "Bundles written to web/data/."

# ---- 4. Prepare gh-pages worktree ---------------------------------------

log "Syncing to gh-pages branch…"
git fetch origin --quiet

if git ls-remote --heads origin gh-pages | grep -q gh-pages; then
  if [[ -d "$PAGES_WORKTREE/.git" ]] || [[ -f "$PAGES_WORKTREE/.git" ]]; then
    git -C "$PAGES_WORKTREE" fetch origin gh-pages --quiet
    git -C "$PAGES_WORKTREE" reset --hard origin/gh-pages --quiet
  else
    rm -rf "$PAGES_WORKTREE"
    git worktree add "$PAGES_WORKTREE" gh-pages >/dev/null
  fi
else
  # First-ever publish → create the orphan branch.
  rm -rf "$PAGES_WORKTREE"
  git worktree add --orphan -B gh-pages "$PAGES_WORKTREE" >/dev/null
  (cd "$PAGES_WORKTREE" && touch .nojekyll && git add .nojekyll && \
    git commit --quiet -m "init gh-pages" && \
    git push -u origin gh-pages --quiet)
fi

# Mirror web/ → worktree (preserves .nojekyll and any manual files in the worktree)
rsync -a --delete \
  --exclude='.git' --exclude='.nojekyll' \
  "$REPO_ROOT/web/" "$PAGES_WORKTREE/"
# Always keep a .nojekyll so GitHub Pages serves files starting with _
touch "$PAGES_WORKTREE/.nojekyll"

# Cache-bust the asset URLs in index.html so visitors get fresh JS/CSS even
# when GitHub Pages caches them with max-age=14400.
VER="$(date -u +%Y%m%d%H%M%S)-$(git -C "$REPO_ROOT" rev-parse --short=8 HEAD 2>/dev/null || echo 'local')"
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s/__ASSET_VER__/${VER}/g" "$PAGES_WORKTREE/index.html"
else
  sed -i "s/__ASSET_VER__/${VER}/g" "$PAGES_WORKTREE/index.html"
fi
echo "  asset version: ${VER}"

# ---- 5. Commit + push to gh-pages ---------------------------------------

cd "$PAGES_WORKTREE"
git add -A
if git diff --cached --quiet; then
  ok "Nothing changed on gh-pages — skipping push."
else
  git commit --quiet -m "publish $(date -u +%Y-%m-%dT%H:%MZ)"
  git push --quiet origin gh-pages
  ok "Pushed to gh-pages."
fi
cd "$REPO_ROOT"

# ---- 6. Optional mirror to personal site --------------------------------

if [[ "$DO_MIRROR" == "true" && -n "${YUU_PERSONAL_SITE_PATH:-}" ]]; then
  TARGET="$YUU_PERSONAL_SITE_PATH"
  PARENT="$(dirname "$TARGET")"
  if [[ ! -d "$PARENT" ]]; then
    warn "YUU_PERSONAL_SITE_PATH parent '$PARENT' does not exist — skipping mirror."
  else
    mkdir -p "$TARGET"
    log "Mirroring web/ → $TARGET (excluding index.html so a host-site wrapper is preserved)"
    # Exclude index.html so the personal site can host its own wrapper page
    # with its nav/footer; only assets and data are synced.
    rsync -a --delete \
      --exclude='.git' --exclude='index.html' \
      "$REPO_ROOT/web/" "$TARGET/"
    # Stamp the asset version into the wrapper if one exists.
    if [[ -f "$TARGET/index.html" ]]; then
      if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/__ASSET_VER__/${VER}/g" "$TARGET/index.html"
      else
        sed -i "s/__ASSET_VER__/${VER}/g" "$TARGET/index.html"
      fi
      ok "Updated cache-bust version in wrapper: $TARGET/index.html"
    fi
    ok "Mirror complete. Remember to commit + push in your personal site repo."
  fi
fi

# ---- 7. Done ------------------------------------------------------------

ok "All done. Live at https://yutsang.github.io/yuutraffic/"
ok "If this is the first publish, enable Pages: repo Settings → Pages → branch: gh-pages, folder: /"
