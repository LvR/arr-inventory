# AGENTS.md

Repository guidance for agentic coding assistants operating in this repo.

## Repo State

- This repository now hosts a Python/FastAPI + SQLite scaffold for a read-only ARR inventory service.
- The app is Dockerized as a single service with background scans handled in-process.
- A package manifest, test runner, and lint config are present.
- No Cursor rules were found in `.cursor/rules/` or `.cursorrules`.
- No Copilot instructions were found in `.github/copilot-instructions.md`.

## What To Do First

- Inspect the repository root before making assumptions.
- Prefer the simplest change that satisfies the request.
- Keep this file updated as tooling is added.

## Current Commands

- Install dependencies: `pip install -r requirements-dev.txt`
- Install frontend dependencies: `cd frontend && npm install`
- Run the web app: `uvicorn app.main:app --reload`
- Run the frontend dev server: `cd frontend && npm start`
- Build frontend assets: `cd frontend && npm run build`
- Test: `pytest`
- Frontend test: `cd frontend && npm test`
- Lint: `ruff check .`
- Format: `ruff format .`

## Frontend Notes

- Angular dev server uses `frontend/proxy.conf.json` to proxy `/api` to the FastAPI app on port 8000.
- Production frontend build output is served from `frontend/dist/frontend/browser` by FastAPI.
- Dashboard refresh now comes from Angular polling `/api/dashboard` and immediate refetch after scan/purge actions.
- Angular frontend uses standalone components; prefer adding focused components instead of growing `App`.
- Keep HTTP access in Angular services and keep view components presentational when practical.
- Keep filter/sort/persistence logic in dedicated state services rather than inside templates or large components.
- Prefer explicit `input()`/`output()` contracts over passing many bound callbacks from parent components.
- Keep component-specific CSS local to the component; keep only tokens and truly shared UI primitives in global/root styles.
- When refactoring Angular code, add or move tests to the service/component level rather than keeping all behavior in `app.spec.ts`.
- Frontend tests may require `CHROME_BIN=/usr/bin/chromium-browser` in this environment.

## Command Documentation Template

Use this format when scripts appear:

- Build: `docker compose build`
- Lint: `ruff check .`
- Test: `pytest`
- Frontend build: `cd frontend && npm run build`
- Frontend test: `cd frontend && npm test`
- Frontend test with browser binary: `cd frontend && CHROME_BIN=/usr/bin/chromium-browser npm test`
- Single test file: `pytest tests/test_app.py`
- Single test name: `pytest -k "test_name"`
- Watch tests: not configured yet

## Single Test Guidance

- Prefer the narrowest test command available.
- If the runner supports file selection, use that first.
- If the runner supports test-name filtering, use that second.
- If both exist, document both.
- If tests are integration-heavy, note any required env vars or services.

## Code Style Overview

- Match the existing style in nearby files.
- Keep changes small and consistent.
- Do not introduce new abstractions unless they clearly reduce complexity.
- Favor readable code over clever code.

## Imports

- Group imports consistently: external first, then internal, then relative.
- Remove unused imports.
- Prefer explicit imports over wildcard imports.
- Keep import ordering stable and deterministic.
- Use aliases only when the project already does so.

## Formatting

- Use the project's formatter when one exists.
- Do not manually reformat unrelated code.
- Keep line length reasonable and consistent with neighbors.
- Preserve file encoding as ASCII unless a file already uses non-ASCII.
- Avoid trailing whitespace and inconsistent indentation.

## Types And Data Shapes

- Prefer explicit types where they improve clarity.
- Do not over-annotate obvious local values.
- Keep public API shapes stable.
- Model data with the narrowest practical type.
- Avoid `any`-style escape hatches unless there is no safe alternative.

## Naming Conventions

- Use descriptive names that explain intent.
- Prefer project-typical casing and suffixes.
- Keep function names verb-oriented.
- Keep constants uppercase only when the language or repo convention expects it.
- Avoid abbreviations unless they are common in the domain.

## Error Handling

- Fail fast on invalid input.
- Preserve original error context when rethrowing.
- Do not swallow errors silently.
- Return meaningful messages for user-facing failures.
- Add guards at boundaries rather than deep in core logic.

## Comments And Docs

- Add comments only for non-obvious intent.
- Do not restate what the code already says.
- Prefer self-documenting names over explanatory comments.
- Update README or local docs when behavior changes.

## Testing Expectations

- Add or update tests for behavior changes.
- Prefer focused tests over broad snapshot churn.
- Cover regression cases when fixing bugs.
- Keep test names specific to the behavior under test.
- If a test fails, fix the code or the test expectation, not both blindly.

## Workflow For Agents

- Read the relevant files before editing.
- Check for local instructions in sibling docs before changing style.
- Keep changes compatible with the current repo state.
- Do not rewrite unrelated files.
- Verify your changes with the smallest useful check.

## When Adding A Toolchain

- Document the exact package manager and runtime version.
- Add install, build, lint, test, format, and single-test commands.
- Note any required environment variables.
- Add framework-specific conventions here.
- Keep this file synchronized with new scripts.

## Maintenance Notes

- If `.cursor/rules/`, `.cursorrules`, or `.github/copilot-instructions.md` are added later, merge their guidance here.
- If conflicting guidance appears, prefer the most specific repo-local instruction.
- If two instructions conflict, the newer repo-local file should usually win.

## Practical Defaults

- Use ASCII in new files unless existing content requires otherwise.
- Prefer simple markdown for docs and instructions.
- Keep commands copy-pastable.
- Avoid shell pipelines in docs unless they add clear value.
- Document only what agents need to act safely and consistently.

## Status

- Build command: `docker compose build`
- Lint command: `ruff check .`
- Test command: `pytest`
- Frontend build command: `cd frontend && npm run build`
- Frontend test command: `cd frontend && npm test`
- Single-test command: `pytest tests/test_app.py`
- Cursor rules: none found.
- Copilot instructions: none found.
