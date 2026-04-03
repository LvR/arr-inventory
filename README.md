# ARR inventory

Read-only web app to inventory torrents and media files across an ARR stack.

## Scope v1

- filesystem inventory only, no delete/rename/move actions
- hardlink-aware grouping across `/data/downloads`, `/data/media/movies`, `/data/media/tv`, `/data/media/music`
- read-only enrichment from qBittorrent, Radarr, Sonarr, and TMDB
- dashboard with summary counters, background job state, and a grouped table
- qBittorrent sync now runs as a second background job after filesystem scan and enriches groups with torrent metadata
- a third background job runs consistency checks after torrent sync and stores an OK/KO status per group

## Stack

- Backend: Python + FastAPI
- Storage: SQLite
- UI: Angular SPA served by FastAPI
- Runtime: Docker Compose (single app service)

## Quick start

1. Copy `.env.example` to `.env`, set `ADMIN_USERNAME` and `ADMIN_PASSWORD`, then adjust the API settings.
2. Start the stack with `docker compose up --build`.
3. Open `http://localhost:8000`.

## Project layout

- `app/`: application code
- `tests/`: basic app checks
- `docker-compose.yml`: local runtime
- `Dockerfile`: container image
- `.env.example`: configuration template

## Environment variables

- `HOST_DATA_ROOT`: host path mounted read-only into the container at `/data`
- `DATA_ROOT`: container-internal scan root, keep this at `/data`
- `DATABASE_PATH`: SQLite file path inside the container
- `ADMIN_USERNAME`, `ADMIN_PASSWORD`: administrator login used by the web UI
- `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD`
- `TORRENT_MIN_SEED_TIME_DAYS`, `TORRENT_MIN_RATIO`: thresholds used by the download usefulness consistency rule
- `RADARR_URL`, `RADARR_API_KEY`
- `SONARR_URL`, `SONARR_API_KEY`
- `TMDB_API_KEY`

## Commands

- Install: `pip install -r requirements-dev.txt`
- Install frontend: `cd frontend && npm install`
- Run app: `uvicorn app.main:app --reload`
- Run frontend dev server: `cd frontend && npm start`
- Build frontend: `cd frontend && npm run build`
- Test: `pytest`
- Frontend test: `cd frontend && npm test`
- Lint: `ruff check .`

## Frontend development

- `npm start` proxies `/api` to `http://localhost:8000` for local Angular development.
- Production assets are built into `frontend/dist/frontend/browser` and served by FastAPI.
- Live refresh is now handled in Angular with polling against `/api/dashboard`, plus immediate refresh after scan and purge actions.

## Consistency checks

Each analysis run now executes five jobs in order:

1. `Filesystem scan`
2. `qBittorrent sync`
3. `Radarr sync`
4. `Sonarr sync`
5. `Consistency check`

The consistency step evaluates every hardlink group and stores an extensible list of check results. Each check produces:

- a stable `check_key`
- a human label
- a status: `pending`, `ok`, `ko`, or `na`
- a short summary
- optional detail lines shown in the group detail modal

The dashboard exposes the aggregated group status as a new `Check` column:

- `Pending`: the global consistency pass has not run yet for that group
- `OK`: all checks passed for the group
- `KO`: at least one check failed for the group

Rule-level statuses work like this:

- `pending`: reserved for checks that have not been evaluated yet
- `ok`: the rule applied and passed
- `ko`: the rule applied and failed
- `na`: the rule does not apply to this group; the UI renders it greyed out

Current implemented rules:

- `Downloads in torrents`: every file located under `/data/downloads` for a group must be matched to a qBittorrent file
- `Movies single video directory`: within `/data/media/movies`, a single group cannot contain more than one video file in the same subdirectory; one movie directory should map to one video file for that group
- `Movies match Radarr`: video files in `/data/media/movies` must be mirrored by imported Radarr entries, and imported Radarr entries for the group must point to movie files
- `TV match Sonarr`: video files in `/data/media/tv` must be mirrored by imported Sonarr entries, and imported Sonarr entries for the group must point to TV files
- `Download torrent still useful`: if a group only exists in downloads/torrents and all its matched torrents exceed both configured seed time and ratio thresholds, the group is marked `KO`
- `Trackers healthy`: if any active tracker attached to a matched torrent reports an error state or error message, the group is marked `KO`

This check system is intentionally data-driven so more rules can be added later without changing the overall dashboard flow.

## Notes

- The web UI now requires administrator login before any dashboard data is exposed.
- The first version is strictly read-only.
- Cleanup actions will be added later only if explicitly enabled.
