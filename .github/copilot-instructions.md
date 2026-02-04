# Copilot / AI Agent Instructions for Thai LPR System 🚗🇹🇭

Purpose
- Short, actionable guidance so an AI coding agent can be immediately productive in this repo.

Architecture (big picture)
- Backend: FastAPI app in `backend/` (entry: `backend/main.py`). Responsibilities: accept image uploads (`/api/recognize`), verification (`/api/verify/{log_id}`), and basic stats/queue endpoints. Uses async SQLAlchemy + Postgres (`backend/db.py`).
- LPR core: `backend/lpr_processor.py` — YOLO (Ultralytics) for plate detection + PaddleOCR for Thai OCR, fuzzy province matching, and post-processing. Prefers TensorRT `.engine` (fast) or falls back to `.pt`.
- Data & storage: images saved via `backend/storage.py` under `storage/YYYY-MM-DD/` with prefixes `orig_` and `crop_`. DB tables defined in `backend/models.py` (ScanLog, MasterData).
- Frontend: Vite + React + Tailwind in `frontend/`. Client API wrappers in `frontend/src/lib/api.ts` and UI for verification in `frontend/src/pages/VerifyQueue.tsx` and `frontend/src/components/VerificationItem.tsx`.

Key files to inspect quickly
- `backend/main.py` — HTTP endpoints and business logic for recognition + verify
- `backend/lpr_processor.py` — detection + OCR + parsing + province fuzzy-match logic
- `backend/models.py` / `backend/schemas.py` — DB + Pydantic schemas
- `backend/active_learning.py` — exporter for MLPR (labels format: `<license>\t<province>`)
- `backend/storage.py` — how images are saved and returned as relative paths
- `frontend/src/lib/api.ts` — client-side expectations for endpoints
- `frontend/src/components/VerificationItem.tsx` — verification UX and keyboard shortcuts (Enter = confirm, Ctrl+Enter = save correction)

Important environment & run commands
- Backend deps: `pip install -r backend/requirements.txt`.
- Run backend (dev):
  - `python -m uvicorn backend.main:app --reload --port 8000`
  - Env vars: `DATABASE_URL` (postgres), `MODEL_DIR` (defaults to `./models`), `STORAGE_BASE` (defaults to `./storage`).
- Frontend:
  - `cd frontend && npm install` (or `pnpm`/`yarn`), then `npm run dev` (Vite) or `npm run build` for production.
  - Note: `frontend/src/lib/api.ts` uses `API_BASE = ""` (same origin). When running frontend on a different port, set `API_BASE = "http://localhost:8000"` or proxy requests.

Runtime expectations & gotchas
- GPU recommended: `LPRProcessor` defaults to `device='cuda:0'` and PaddleOCR is initialized with `use_gpu=True`. Running full pipeline on CPU will require editing `LPRProcessor._load_ocr` and related settings.
- Model loading: `models/` contains `best.engine`, `best.pt`, `best.onnx`. `LPRProcessor` prefers `.engine` (TensorRT) then `.pt`. Ensure correct model files exist in `MODEL_DIR`.
- Static file serving: database stores relative paths like `storage/2026-02-04/crop_xxx.jpg`. The frontend uses `joinStorageUrl` to convert to `/static/<path>`. The backend currently expects static files to be served (either mount `StaticFiles` or expose `storage/` via reverse proxy).
- No migrations detected: There is no Alembic or migration folder. DB schema must be provisioned externally (e.g., create tables from `backend/models.py` or run a one-off script).

API examples (useful for tests and debugging)
- Recognize (multipart file):
  - curl example: `curl -F "image=@/path/to/img.jpg" http://localhost:8000/api/recognize`
  - Returns `RecognizeResponse` including `debug` and `cropped_plate_image_path`.
- Verify (JSON):
  - `POST /api/verify/{log_id}` with body `{ "corrected_license": "1กก 1234", "corrected_province": "กรุงเทพมหานคร", "is_correct": false }`.
- Pending queue: `GET /api/queue/pending?limit=50` returns pending logs used by the frontend queue UI.

Project-specific conventions & patterns
- Async SQLAlchemy pattern: `get_session()` yields `AsyncSession` and endpoints `Depends(get_session)`; queries use `select(...)` and `session.execute(q).scalars().first()`.
- Image paths stored as relative inside DB with `storage/` prefix; do not expect fully qualified URLs.
- Human verification changes: verification either sets `ScanStatus.ALPR` (accepted) or `ScanStatus.MLPR` (corrected by human) and upserts `MasterData`.
- Active learning export format: labels are `.txt` files with `license<TAB>province`, and matching cropped images + metadata JSON.

Where to look for common issues
- OCR quality: see `backend/lpr_processor.py` — text parsing heuristics are implemented here (province candidate selection, category+number parsing). Unit-targeting fixes to province fuzzy-match (threshold, normalization) live here.
- Device/model issues: failures to load `.engine` or `.pt` will be raised in `_load_yolo()`; verify `MODEL_DIR` and file names.
- Missing static files: check storage path and whether static serving is configured.

Tests and CI
- No test suite or CI config found. Add focused unit tests for `LPRProcessor._parse_text`, `active_learning.export_mlpr_hard_examples`, and API contracts when adding tests.

If anything is unclear or you want me to expand a section (examples, more curl commands, dev scripts), tell me which part and I'll iterate. ✅
