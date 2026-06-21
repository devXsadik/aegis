# Ai-SSS Development Guide

## Prerequisites
- **macOS / Linux**
- **Micromamba** (or another Python virtual environment manager)
- **PostgreSQL** (installed via Homebrew)

## Initial Setup

1. **Start PostgreSQL Database**
   ```bash
   brew services start postgresql
   ```

2. **Activate Python Environment**
   ```bash
   # If using micromamba:
   micromamba activate ai-sss
   ```

3. **Install Dependencies & Initialize DB**
   Run the setup script from the root of the project to install all required packages (like `ultralytics`, `easyocr`, `opencv-headless`) and set up the PostgreSQL tables:
   ```bash
   ./setup_phase1.sh
   ```

4. **YOLOv8 Model**
   Ensure the `yolov8x.pt` human model file is downloaded and placed inside the `models/` directory.

---

## Running the System

You will need two separate terminal windows. Make sure your Python environment is activated in both!

### 1. Start the FastAPI Backend
This server handles the database interactions, authentication, WebSockets, and the REST API.
```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```
- **API Documentation (Swagger UI):** http://localhost:8000/docs

### 2. Start the Surveillance Pipeline
This runs the core computer vision pipeline (Detection -> Tracking -> Recognition -> Behavior -> Analytics -> Output).
```bash
python3 main.py
```
To run it on a pre-recorded video instead of your webcam:
```bash
python3 main.py --video path/to/video.mp4
```

---

## Keyboard Shortcuts (Pipeline UI)
- **`S`**: Print performance stats (shows how much time each pipeline stage takes).
- **`T`**: Toggle Thermal Mode camera view.
- **`Q`**: Quit the surveillance window cleanly.
