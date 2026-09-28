"""
CÓC ĐI LÀM — Unified Dev Server Runner
Chạy đồng thời cả Backend (FastAPI uvicorn:8000) và Frontend (Next.js:3000)
trong một tiến trình duy nhất.
"""

import subprocess
import sys
import time
import os
import io

# Setup UTF-8 encoding for Windows standard output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

def main():
    print("[DEV_RUNNER] Starting Backend (FastAPI:8000)...")
    backend_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=BACKEND_DIR,
    )

    print("[DEV_RUNNER] Starting Frontend (Next.js:3000)...")
    npm_cmd = "npx.cmd" if os.name == "nt" else "npx"
    frontend_proc = subprocess.Popen(
        [npm_cmd, "next", "dev", "-H", "127.0.0.1", "-p", "3000"],
        cwd=FRONTEND_DIR,
    )

    print(f"[DEV_RUNNER] Servers active! Backend PID={backend_proc.pid}, Frontend PID={frontend_proc.pid}")

    try:
        while True:
            time.sleep(2)
            if backend_proc.poll() is not None:
                print("[DEV_RUNNER] Backend exited, auto-restarting...")
                backend_proc = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
                    cwd=BACKEND_DIR,
                )
            if frontend_proc.poll() is not None:
                print("[DEV_RUNNER] Frontend exited, auto-restarting...")
                frontend_proc = subprocess.Popen(
                    [npm_cmd, "next", "dev", "-H", "127.0.0.1", "-p", "3000"],
                    cwd=FRONTEND_DIR,
                )
    except KeyboardInterrupt:
        print("Shutting down...")
        backend_proc.terminate()
        frontend_proc.terminate()

if __name__ == "__main__":
    main()
