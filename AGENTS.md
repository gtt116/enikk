# AGENTS.md

Guidance for AI coding agents working in the Enikk repository. This file covers repository-level knowledge; machine-specific notes (local file locks, local-only files) live outside the repo.

## Development commands

Windows repository. Use the repo `.venv` (Python 3.12 locally; CI also checks 3.11):

```powershell
.venv\Scripts\python.exe -m ruff check .      # lint — CI blocks on this
.venv\Scripts\python.exe -m mypy enikk        # type check — CI blocks on this
.venv\Scripts\python.exe -m pytest tests\ -q  # full suite, ~75 s (loads ONNX/OCR models)
.\build.bat                                   # dev build: exe + installer + zip, ~5 min
```

Run ruff + mypy + pytest locally before pushing; CI repeats all of them on Python 3.11 and 3.12.

## Branches, PRs, CI

- `main` is protected (3 required status checks: CI 3.11, CI 3.12, Build). All changes go through pull requests, typically from `codex/`-prefixed branches.
- Push an explicit branch (`git push -u origin <branch>`); a bare `git push` uses matching refs and may try to push unrelated stale branches.
- Every push/PR runs two workflows: **CI** (lint + type check + tests) and **Build** (PyInstaller + Inno Setup installer + smoke test; artifacts land in the Actions run, not Releases).
- Typical CI failures: ruff unused imports in new test files; mypy narrowing errors in `controller.py`.

## Versioning

Versions derive from git tags — never hand-bump a version constant. `enikk/version.py` resolves in order:

1. Frozen build: `BUILD_VERSION` stamped in `enikk/_build_version.py` by `scripts/build_version.ps1` before PyInstaller runs (only read when `sys.frozen`).
2. Source checkout: live `git describe --tags --long` from the repo root.
3. Fallback: `_FALLBACK_VERSION` (installs without git metadata).

Format: `0.11.1+36.g8da3119` (nearest tag + commits since it + short hash; a PEP 440 local version, so update checks compare correctly). An exact tag match builds as the bare tag, e.g. `0.12.0`.

- Dev builds: version computed automatically from HEAD.
- Release: `git tag v0.12.0 && git push origin v0.12.0` — CI runs `build.bat --release`, which refuses unless HEAD is exactly on a tag, and publishes the GitHub Release with the zip and installer.

## Frontend (Tailwind)

Runtime serves the committed compiled stylesheet `enikk/static/vendor/tailwind.css`; there is no npm dependency at runtime. Build sources live in `frontend/`. After changing Tailwind classes or theme config: `cd frontend; npm install; npm run build`, then commit the regenerated `tailwind.css`. New utility classes do not exist until the stylesheet is rebuilt.

Dark mode: `document.documentElement.classList` toggle persisted in `localStorage['enikk-dark']`.

## Commit conventions

- Conventional-commit prefixes: `feat:`, `fix:`, `refactor:`, `chore:`, `style:`, `test:`.
- Do not add AI attribution, `Co-Authored-By`, or "generated with" lines to commit messages.
