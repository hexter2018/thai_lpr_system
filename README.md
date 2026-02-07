# Thai ALPR (Full-stack) — FastAPI + Celery + React + PostgreSQL

This is a runnable **starter** for a Thai license-plate system with:
- **Backend**: FastAPI (REST API)
- **Worker**: Celery (async processing)
- **DB**: PostgreSQL + Alembic migrations
- **Broker**: Redis
- **Frontend**: Vite + React + Tailwind + Router

It is designed to run **immediately** even if you haven't installed YOLO/TensorRT yet:
- If `ultralytics` (YOLO) is unavailable or `MODEL_PATH` is missing, the worker will fall back to a **mock inference** so the whole stack still runs.
- When you're ready, drop your `best.pt` into `models/best.pt` (or set `MODEL_PATH`) and the worker will auto-use it.

---

## Quick start (Docker)

### 1) Start backend + worker + DB + Redis
```bash
cd thai_lpr_system
docker compose up --build
```

- Backend: http://localhost:8000
- API docs: http://localhost:8000/docs
- Frontend: http://localhost

### Windows (Docker Desktop → Linux containers)
Use the CPU worker and localhost defaults:
```bash
cd thai_lpr_system
docker compose -f docker-compose.windows.yml up --build
```

- Backend: http://localhost:8000
- Frontend: http://localhost

#### Windows + GPU (Docker Desktop + WSL2)
If you have NVIDIA GPU support enabled in Docker Desktop (WSL2 backend), use:
```bash
cd thai_lpr_system
docker compose -f docker-compose.windows.gpu.yml up --build
```

Supported GPUs (example list): GTX 3060, 3060 Ti, 4060, 4060 Ti, 5090, 5090 Ti.
Ensure the NVIDIA driver + WSL2 GPU support + Docker Desktop GPU integration are installed and working before running this compose file.

### 2) Try upload
Open Frontend → **Upload** page and upload 1 or multiple images.

---

## Local dev (optional)
Backend:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Worker:
```bash
cd worker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
celery -A worker.celery_app worker --loglevel=INFO
```

Frontend:
```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 80
```

The Vite dev server proxies `/api/*` to `http://localhost:8000` by default. To point the UI at a different API, set `VITE_API_BASE` in your environment (see `.env.example`).

---

## Where to put your model
- `models/best.pt` (recommended path)
- or set env `MODEL_PATH=/models/best.pt`

---

## API quick checks
List cameras:
```bash
curl http://localhost:8000/api/cameras
```

Start RTSP ingest:
```bash
curl -X POST http://localhost:8000/api/rtsp/start \
  -H "Content-Type: application/json" \
  -d '{"camera_id":"plaza2-lane1","rtsp_url":"rtsp://user:pass@ip/stream","fps":2.0,"reconnect_sec":2.0}'
```

Stop RTSP ingest:
```bash
curl -X POST http://localhost:8000/api/rtsp/stop \
  -H "Content-Type: application/json" \
  -d '{"camera_id":"plaza2-lane1"}'
```

---

## Notes for GPU (GTX3060)
For production-grade GPU YOLO/TensorRT, you typically:
- Install NVIDIA driver + CUDA properly on host
- Use `nvidia-container-toolkit` and run docker with GPU
- Install torch/ultralytics compatible with your CUDA version
- Export YOLO to TensorRT engine and load engine in inference

This starter keeps the pipeline & UI/DB/verification logic ready, and you can swap the inference module to TensorRT later.
