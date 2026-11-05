# Git, ignores, and CI (team reference)

This file is the **committed** source of truth for repository hygiene. Local-only Cursor rules live in `.cursorrules` (ignored by git); keep them aligned with this document when you change policy.

## `.gitignore`

- Keep entries **minimal and accurate**: Python caches, venvs, `.env`, OS junk (`.DS_Store`, `Thumbs.db`), Streamlit secrets (`.streamlit/`), generated paths under `data/**`, logs, and accidental nested repos (e.g. `/rrag/`).
- **Do not** add `.gitattributes` — this project relies on `.gitignore` only for file handling policy.
- **`.cursorrules`** remains **local-only** (listed in `.gitignore`). Do not commit it; document shared expectations here and in `README.md` as needed.

## Line endings

Without `.gitattributes`, editors may normalize line endings differently on Windows. Prefer editor “LF” for this repo.

## GitHub Actions ([`.github/workflows/ci-cd.yml`](../.github/workflows/ci-cd.yml))

- **Tests** must fail the workflow on failure (pytest exit code is not masked).
- **Formatting**: Black and isort on `src/`, `pages/`, and `tests/`.
- **Lint**: Ruff on the same paths; shared relaxations are in [`pyproject.toml`](../pyproject.toml).
- **Build** runs on **`main` and `develop`** so staging jobs can consume artifacts.
- **Production** deploy/release steps still target **`main`** as configured.

## History rewrites

If the branch was rebuilt (e.g. new root commit), updating GitHub requires:

```bash
git push --force-with-lease origin <branch>
```

Coordinate with collaborators; they must reset or re-clone after a force-push.

## Local checks before pushing

```bash
pip install -r requirements.txt
black --check src/ pages/ tests/
isort --check-only src/ pages/ tests/
ruff check src/ pages/ tests/
TESTING=true DATABASE_PATH=data/01_raw/kmb_data.db pytest tests/ -q
```
