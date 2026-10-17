"""Workspace-scoped local launcher; never stop unrelated apps by port/name."""

import argparse
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import json
import urllib.error
import urllib.request
import webbrowser


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
BACKEND_URL = "http://127.0.0.1:8000/health"
FRONTEND_URL = "http://127.0.0.1:3000/"
STARTUP_TIMEOUT_SEC = 60
CONTROL_DIR = Path(ROOT_DIR) / ".cache" / "dev_runner"
STATE_KIND = "coc-di-lam-dev-runner-v1"


class StopRequested(Exception):
    """A scoped stop request arrived, including during startup."""


def _pid_is_alive(pid: int) -> bool:
    """Read-only liveness check; never authority to kill a stored PID."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 5:
                # Some Windows environments deny OpenProcess for a *missing*
                # PID too. Confirm existence through the process table before
                # treating access denied as a live owner.
                try:
                    import psutil
                    return psutil.pid_exists(pid)
                except ImportError:
                    return True  # Unknown identity: fail closed.
            return False
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True  # Unknown exit status: fail closed.
            return code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _load_state() -> dict | None:
    try:
        state = json.loads((CONTROL_DIR / "state.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise ValueError("Không đọc được state.json; không tự dừng tiến trình nào.") from exc
    if not (
        isinstance(state, dict) and state.get("kind") == STATE_KIND
        and state.get("workspace") == ROOT_DIR
        and type(state.get("runner_pid")) is int and state["runner_pid"] > 0
        and isinstance(state.get("token"), str) and len(state["token"]) == 64
        and all(char in "0123456789abcdef" for char in state["token"])
    ):
        raise ValueError("State không thuộc launcher/workspace này; từ chối thao tác.")
    return state


def _claim_runner() -> dict | None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    previous = _load_state()
    if previous:
        if _pid_is_alive(previous["runner_pid"]):
            return None
        # Preserve stale metadata; never kill its stored PID.
        (CONTROL_DIR / "state.json").rename(CONTROL_DIR / f"stale-{previous['token']}.json")
    state = {"kind": STATE_KIND, "workspace": ROOT_DIR, "runner_pid": os.getpid(), "token": secrets.token_hex(32)}
    try:
        with (CONTROL_DIR / "state.json").open("x", encoding="utf-8") as stream:
            json.dump(state, stream)
    except FileExistsError as exc:
        raise ValueError("Một launcher khác đang khởi động; hãy thử status.") from exc
    return state


def _stop_requested(state: dict) -> bool:
    try:
        request = json.loads((CONTROL_DIR / "stop.json").read_text(encoding="utf-8"))
        return request == {"workspace": ROOT_DIR, "token": state["token"]}
    except (OSError, ValueError):
        return False


def _checkpoint(state: dict) -> None:
    if _stop_requested(state):
        raise StopRequested


def _release_runner(state: dict) -> None:
    # Only our two small control files, not application/Next/session caches.
    if _stop_requested(state):
        (CONTROL_DIR / "stop.json").unlink(missing_ok=True)
    current = _load_state()
    if current and current["token"] == state["token"]:
        (CONTROL_DIR / "state.json").unlink(missing_ok=True)


def stop(timeout: float = 15) -> int:
    state = _load_state()
    if not state or not _pid_is_alive(state["runner_pid"]):
        print("[DEV_RUNNER] Không có launcher đang chạy. Server mở thủ công không bị dừng.")
        return 0
    # Running owner cleans up its Popen objects; this CLI kills nobody.
    request = {"workspace": ROOT_DIR, "token": state["token"]}
    temporary = CONTROL_DIR / f"stop-{secrets.token_hex(8)}.tmp"
    temporary.write_text(json.dumps(request), encoding="utf-8")
    temporary.replace(CONTROL_DIR / "stop.json")
    print("[DEV_RUNNER] Đã gửi yêu cầu dừng tới launcher của project này.", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = _load_state()
        if current is None or current["token"] != state["token"]:
            print("[DEV_RUNNER] Launcher đã hoàn tất dừng các server do nó tạo.")
            return 0
        time.sleep(0.2)
    print("[DEV_RUNNER] Chưa xác nhận dừng xong. Xem cửa sổ launcher; không force-kill theo port/tên.")
    return 1


def status() -> int:
    state = _load_state()
    managed = bool(state and _pid_is_alive(state["runner_pid"]))
    print(f"[DEV_RUNNER] Launcher: {'đang chạy' if managed else 'không chạy'}")
    print(f"[DEV_RUNNER] Backend: {'sẵn sàng' if _existing_backend_is_ours() else 'chưa sẵn sàng'}")
    print(f"[DEV_RUNNER] Frontend: {'sẵn sàng' if _existing_frontend_is_ours() else 'chưa sẵn sàng'}")
    if not managed and (_port_is_open(8000) or _port_is_open(3000)):
        print("[DEV_RUNNER] Có port đang dùng ngoài quyền quản lý launcher; stop.bat không dừng nó.")
    return 0


def _backend_command() -> list[str]:
    return [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"]


def _frontend_command() -> list[str]:
    # Direct node child avoids npm.cmd/cmd shell between runner and Next.
    return [shutil.which("node") or "node", os.path.join(FRONTEND_DIR, "node_modules", "next", "dist", "bin", "next"), "dev", "-H", "127.0.0.1", "-p", "3000"]


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.25)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def _url_is_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _read_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            value = json.loads(response.read().decode("utf-8"))
            return value if isinstance(value, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _existing_backend_is_ours() -> bool:
    health = _read_json(BACKEND_URL)
    debug = _read_json("http://127.0.0.1:8000/api/v1/debug/routes")
    return bool(health and health.get("service") == "coc-di-lam-backend" and debug and debug.get("enabled"))


def _existing_frontend_is_ours() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:3000/debug", timeout=2) as response:
            page = response.read().decode("utf-8", errors="replace")
            return response.status == 200 and "Debug luồng dữ liệu" in page
    except (OSError, urllib.error.URLError):
        return False


def _open_browser() -> None:
    """Browser failure must not bring down healthy API/frontend processes."""
    try:
        if webbrowser.open(FRONTEND_URL):
            return
    except (OSError, webbrowser.Error) as exc:
        print(f"[DEV_RUNNER] Không mở browser tự động được: {exc}", flush=True)
    print(f"[DEV_RUNNER] Hãy mở web thủ công: {FRONTEND_URL}", flush=True)


def _attach_running_app(*, open_browser: bool) -> int:
    """Repeated clicks wait for readiness and reopen UI, without another runner."""
    state = _load_state()
    if not state:
        print("[DEV_RUNNER] Launcher vừa dừng. Chạy start.bat lại.", flush=True)
        return 1
    print("[DEV_RUNNER] Đã có launcher; đang kiểm tra backend và frontend...", flush=True)
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        current = _load_state()
        if not current or current["token"] != state["token"] or not _pid_is_alive(current["runner_pid"]):
            print("[DEV_RUNNER] Launcher cũ đã dừng/thay đổi; chạy start.bat lại.", flush=True)
            return 1
        if _existing_backend_is_ours() and _existing_frontend_is_ours():
            print(f"[DEV_RUNNER] Server đang sẵn sàng: {FRONTEND_URL}", flush=True)
            print("[DEV_RUNNER] Debug: http://127.0.0.1:3000/debug", flush=True)
            print("[DEV_RUNNER] Không tạo server trùng. Muốn restart: stop.bat rồi start.bat.", flush=True)
            if open_browser:
                _open_browser()
            return 0
        time.sleep(0.5)
    print("[DEV_RUNNER] Có launcher nhưng server chưa sẵn sàng. Xem log cửa sổ đang chạy; không báo thành công giả.", flush=True)
    return 1


def _stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        # ONLY the owned Popen tree. Never kill by name or scan port owners.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return

    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def _check_prerequisites() -> bool:
    if not os.path.isfile(os.path.join(FRONTEND_DIR, "node_modules", "next", "dist", "bin", "next")):
        print("[DEV_RUNNER] Chưa cài frontend dependencies. Chạy: cd frontend && npm ci")
        return False

    try:
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "--version"],
            cwd=BACKEND_DIR,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        print("[DEV_RUNNER] Chưa cài backend dependencies. Chạy: cd backend && pip install -r requirements.txt")
        return False

    if not shutil.which("node"):
        print("[DEV_RUNNER] Không tìm thấy node trong PATH.")
        return False
    return True


def _wait_until_ready(backend: subprocess.Popen | None, frontend: subprocess.Popen | None, state: dict) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        _checkpoint(state)
        for name, process in (("Backend", backend), ("Frontend", frontend)):
            if process is None:
                continue
            exit_code = process.poll()
            if exit_code is not None:
                print(f"[DEV_RUNNER] {name} đã thoát trong lúc khởi động (exit={exit_code}); xem log phía trên.")
                return False

        if _existing_backend_is_ours() and _url_is_ready(FRONTEND_URL):
            return True
        time.sleep(0.5)

    print(f"[DEV_RUNNER] Hết {STARTUP_TIMEOUT_SEC}s nhưng một server chưa sẵn sàng.")
    print(f"[DEV_RUNNER] Kiểm tra lần lượt: {BACKEND_URL} và {FRONTEND_URL}")
    return False


def _run_servers(state: dict, *, open_browser: bool, reuse_existing: bool) -> int:
    if not _check_prerequisites():
        return 1

    backend_reused = _port_is_open(8000) and reuse_existing and _existing_backend_is_ours()
    frontend_reused = _port_is_open(3000) and reuse_existing and _existing_frontend_is_ours()
    blocked = []
    if _port_is_open(8000) and not backend_reused:
        blocked.append(8000)
    if _port_is_open(3000) and not frontend_reused:
        blocked.append(3000)
    if blocked:
        print(f"[DEV_RUNNER] Port đang được chương trình khác sử dụng: {', '.join(map(str, blocked))}.")
        print("[DEV_RUNNER] Dừng server cũ tại cửa sổ của nó, hoặc dùng --reuse-existing nếu đúng app này. Không tự kill.")
        return 1

    env = os.environ.copy()
    env.update({"APP_ENV": "development", "APP_DEBUG": "true", "PYTHONIOENCODING": "utf-8"})
    process_options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    backend_proc = None
    frontend_proc = None

    try:
        _checkpoint(state)
        if backend_reused:
            print("[DEV_RUNNER] Dùng lại backend; runner KHÔNG dừng server này.", flush=True)
        else:
            print("[DEV_RUNNER] Starting Backend at http://127.0.0.1:8000 ...", flush=True)
            backend_proc = subprocess.Popen(
                _backend_command(),
                cwd=BACKEND_DIR,
                env=env,
                **process_options,
            )

        _checkpoint(state)
        if frontend_reused:
            print("[DEV_RUNNER] Dùng lại frontend; runner KHÔNG dừng server này.", flush=True)
        else:
            print("[DEV_RUNNER] Starting Frontend at http://127.0.0.1:3000 ...", flush=True)
            frontend_proc = subprocess.Popen(
                _frontend_command(),
                cwd=FRONTEND_DIR,
                env=env,
                **process_options,
            )

        print("[DEV_RUNNER] Waiting for backend health and frontend HTTP readiness...", flush=True)
        if not _wait_until_ready(backend_proc, frontend_proc, state):
            return 1

        _checkpoint(state)
        print("[DEV_RUNNER] Ready:", flush=True)
        print("  App:     http://127.0.0.1:3000", flush=True)
        print("  Debug:   http://127.0.0.1:3000/debug", flush=True)
        print("  API:     http://127.0.0.1:8000/docs", flush=True)
        print("  Health:  http://127.0.0.1:8000/health", flush=True)
        print("[DEV_RUNNER] Giữ cửa sổ này. Ctrl+C hoặc stop.bat chỉ dừng server do runner tạo.", flush=True)
        if open_browser:
            _open_browser()

        while True:
            _checkpoint(state)
            time.sleep(1)
            for name, process in (("Backend", backend_proc), ("Frontend", frontend_proc)):
                if process is None:
                    continue
                exit_code = process.poll()
                if exit_code is not None:
                    print(f"[DEV_RUNNER] {name} exited (exit={exit_code}); stopping the other server.")
                    return 1
    except (KeyboardInterrupt, StopRequested):
        print("\n[DEV_RUNNER] Stopping local servers...", flush=True)
        return 0
    finally:
        try:
            _stop_process(frontend_proc)
        finally:
            _stop_process(backend_proc)


def start(*, open_browser: bool = False, reuse_existing: bool = False) -> int:
    state = _claim_runner()
    if state is None:
        return _attach_running_app(open_browser=open_browser)
    try:
        return _run_servers(state, open_browser=open_browser, reuse_existing=reuse_existing)
    finally:
        _release_runner(state)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("start", "stop", "status"), default="start")
    parser.add_argument("--open-browser", action="store_true", help="Open browser after both servers are ready")
    parser.add_argument("--reuse-existing", action="store_true", help="Reuse recognized servers; stop leaves them running")
    args = parser.parse_args(argv)
    try:
        if args.command == "stop":
            return stop()
        if args.command == "status":
            return status()
        return start(open_browser=args.open_browser, reuse_existing=args.reuse_existing)
    except (OSError, ValueError) as exc:
        print(f"[DEV_RUNNER] Lỗi: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
