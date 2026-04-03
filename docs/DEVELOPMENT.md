# Development

Technical notes for contributors and local development.

## Architecture

- Backend: Python + FastAPI
- Storage: SQLite
- Frontend: Angular SPA
- Runtime: Docker Compose, single application service

The production image builds the Angular frontend first, then serves the built assets from FastAPI.

## Project Layout

- `app/`: backend application code
- `frontend/`: Angular application
- `tests/`: backend tests
- `docker-compose.yml`: local container runtime
- `Dockerfile`: multi-stage image build
- `.env.example`: runtime configuration template

## Docker Runtime

Main user entrypoint:

```bash
docker compose up --build
```

The compose stack:

- exposes the app on port `8000`
- mounts `${HOST_DATA_ROOT}` read-only into `${DOCKER_DATA_ROOT}`
- stores SQLite data in the `arr_inventory_db` Docker volume
- allows overriding the default scan targets with `DOWNLOADS_PATH`, `MOVIES_PATH`, and `TV_PATH`

## Local Development

### Backend

Install dependencies:

```bash
pip install -r requirements-dev.txt
```

Run the API in reload mode:

```bash
uvicorn app.main:app --reload
```

### Frontend

Install dependencies:

```bash
cd frontend && npm install
```

Start the Angular dev server:

```bash
cd frontend && npm start
```

The Angular dev server proxies `/api` to the FastAPI app on port `8000` using `frontend/proxy.conf.json`.

## Build

Build the Docker image and runtime stack:

```bash
docker compose build
```

Build frontend assets only:

```bash
cd frontend && npm run build
```

Production frontend assets are emitted to `frontend/dist/frontend/browser` during local frontend builds, and copied into the final image during the Docker multi-stage build.

## Test And Lint

Backend tests:

```bash
pytest
```

Single backend test file:

```bash
pytest tests/test_app.py
```

Single test by name:

```bash
pytest -k "test_name"
```

Frontend tests:

```bash
cd frontend && npm test
```

In this environment, frontend tests may require:

```bash
cd frontend && CHROME_BIN=/usr/bin/chromium-browser npm test
```

Lint:

```bash
ruff check .
```

Format:

```bash
ruff format .
```

## Runtime Behavior

An analysis run currently executes these jobs in order:

1. Filesystem scan
2. qBittorrent sync
3. Radarr sync
4. Sonarr sync
5. Consistency check

The frontend dashboard refreshes through Angular polling of `/api/dashboard`, plus immediate refetch after scan and purge actions.

## Notes

- The web UI requires administrator login before dashboard data is exposed.
- The application is currently read-only.
- Cleanup actions are not enabled by default.
