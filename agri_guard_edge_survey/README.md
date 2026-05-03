# AgriGuard Edge Survey CLI

Local batch AI for aerial survey missions: slice → YOLO → GPS projection → DBSCAN clustering. **Original images stay on disk; only crops and optional L2 previews are written under `--output`.**

## Install (from monorepo root)

`agri_guard_core` is a declared dependency. From repository root (`media-ai/`):

```bash
pip install -e ./agri_guard_edge_survey
```

Editable install from inside `agri_guard_edge_survey/` is not supported for the path dependency; stay at repo root or run `pip install -e ../agri_guard_core -e .` from that subdirectory.

## Usage

```bash
survey info
survey process -i /path/to/DCIM -o ~/AgriGuard/run1 -m /path/to/model.pt
survey list -o ~/AgriGuard/run1
survey ping --api-url http://127.0.0.1:8000
survey sync -o ~/AgriGuard/run1 --dry-run
survey sync -o ~/AgriGuard/run1 --api-url http://127.0.0.1:8000 --token "<JWT>"
survey sync -o ~/AgriGuard/run1 --api-url http://127.0.0.1:8000 --token "<JWT>" --target-mission-id 42 --retries 3
```

See `docs/02_architecture/edge_survey_ai_cli.md`. Configure backend URL as `SURVEY_API_BASE_URL` or `AGRI_GUARD_API_BASE_URL`, and JWT as `SURVEY_API_TOKEN` (see `agri_guard_edge_survey/.env.example`).
