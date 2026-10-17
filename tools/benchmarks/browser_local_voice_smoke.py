"""Browser E2E smoke: real Next UI, fake microphone WAV, Silero, Qwen and VieNeu.

Uses Chrome's fake audio-capture device so tests can exercise getUserMedia
without a physical microphone. Gemini is called for a real interview question.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import numpy as np
import soundfile as sf
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
REPORT = ROOT / "docs" / "benchmarks" / "browser_local_voice_smoke_20261016.json"


def redact(value: str) -> str:
    try:
        from dotenv import dotenv_values
        for name, secret in dotenv_values(BACKEND / ".env").items():
            if any(word in name.upper() for word in ("KEY", "TOKEN", "PASSWORD", "SECRET")) and secret and len(secret) > 8:
                value = value.replace(secret, "[REDACTED]")
    except Exception:
        pass
    return value


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_http(url: str, process: subprocess.Popen, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited {process.returncode} before {url}")
        try:
            if httpx.get(url, timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"server not ready: {url}")


def choose_pair(options: dict) -> tuple[str, str]:
    candidates = options.get("candidates") or []
    jobs = options.get("jobs") or []
    for candidate in candidates:
        if candidate.get("candidate_id") != "CV_FE_001":
            continue
        for job in jobs:
            if (job.get("resolved_framework_id") == candidate.get("resolved_framework_id")
                    and candidate.get("resolved_framework_id")
                    and candidate.get("experience_level") in (job.get("levels") or [])):
                return candidate["candidate_id"], job["job_id"]
    for candidate in candidates:
        for job in jobs:
            if (job.get("resolved_framework_id") == candidate.get("resolved_framework_id")
                    and candidate.get("resolved_framework_id")
                    and candidate.get("experience_level") in (job.get("levels") or [])):
                return candidate["candidate_id"], job["job_id"]
    raise RuntimeError("No CV/JD pair sharing a mapped framework and hiring level")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-vad-fallback", action="store_true",
                        help="Block Silero model download to verify automatic local energy VAD.")
    parser.add_argument("--silent-mic", action="store_true",
                        help="Use silence to verify that no answer is fabricated and no manual click is needed.")
    parser.add_argument("--unclear-mic", action="store_true",
                        help="Use clipped speech to exercise automatic spoken repeat without a click.")
    parser.add_argument("--mild-noise", action="store_true", help="Add reproducible low-level microphone noise.")
    parser.add_argument("--quiet-mic", action="store_true", help="Speak at lower amplitude but above VAD threshold.")
    parser.add_argument("--ambiguous-term", action="store_true",
                        help="Simulate an evidenced phonetic technical-term candidate at the WS boundary.")
    args = parser.parse_args()
    report = (ROOT / "docs" / "benchmarks" / "browser_local_voice_ambiguous_term_20261017.json") if args.ambiguous_term else (
        ROOT / "docs" / "benchmarks" / "browser_local_voice_quiet_20261017.json") if args.quiet_mic else (
        ROOT / "docs" / "benchmarks" / "browser_local_voice_mild_noise_20261017.json") if args.mild_noise else (
        ROOT / "docs" / "benchmarks" / "browser_local_voice_unclear_20261016.json") if args.unclear_mic else (
        ROOT / "docs" / "benchmarks" / "browser_local_voice_silence_20261016.json") if args.silent_mic else (
        ROOT / "docs" / "benchmarks" / "browser_local_voice_fallback_20261016.json") if args.force_vad_fallback else REPORT
    result: dict = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "status": "PARTIAL",
                    "forced_vad_fallback": args.force_vad_fallback, "silent_mic": args.silent_mic,
                    "unclear_mic": args.unclear_mic, "mild_noise": args.mild_noise,
                    "quiet_mic": args.quiet_mic, "ambiguous_term": args.ambiguous_term}
    backend_process = frontend_process = browser = None
    step = "startup"
    logs = []
    with tempfile.TemporaryDirectory(prefix="coc-browser-e2e-") as tmp_name:
        tmp = Path(tmp_name)
        backend_log = (tmp / "backend.log").open("w", encoding="utf-8")
        frontend_log = (tmp / "frontend.log").open("w", encoding="utf-8")
        try:
            backend_port, frontend_port = port(), port()
            api = f"http://127.0.0.1:{backend_port}"
            site = f"http://127.0.0.1:{frontend_port}"
            backend_env = os.environ.copy()
            backend_env.update({"PYTHONPATH": str(BACKEND), "HF_HUB_OFFLINE": "1",
                                "APP_ENV": "development", "APP_DEBUG": "true",
                                "UPSTASH_REDIS_URL": "", "UPSTASH_REDIS_TOKEN": "",
                                "SUPABASE_URL": "", "SUPABASE_ANON_KEY": "", "SUPABASE_SERVICE_ROLE_KEY": "",
                                "PYTHONIOENCODING": "utf-8"})
            backend_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                 "--port", str(backend_port), "--log-level", "warning"],
                cwd=BACKEND, env=backend_env, stdout=backend_log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            wait_http(api + "/health", backend_process, 120)
            health = httpx.get(api + "/health", timeout=10).json()
            result["models"] = {k: health.get(k) for k in (
                "laya_model_loaded", "laya_backend", "laya_device", "tts_model",
                "tts_device", "stt_model", "stt_device", "question_model")}
            print("BACKEND_READY", result["models"], flush=True)

            # Chrome reads the WAV as the microphone stream after getUserMedia.
            spoken = ("Em dùng ri ác để làm giao diện trong dự án. Em muốn học cách xây sản phẩm và phối hợp review code với đội ngũ."
                      if args.ambiguous_term else
                      "Em định hướng phát triển giao diện bằng React. Em muốn thực tập để học cách xây sản phẩm và phối hợp review code với đội ngũ.")
            speech = httpx.get(api + "/api/v1/tts/synthesize", params={"text": spoken}, timeout=None)
            if speech.status_code != 200:
                raise RuntimeError(f"fake microphone TTS HTTP {speech.status_code}: {speech.text[:250]}")
            import io
            data, sample_rate = sf.read(io.BytesIO(speech.content), dtype="float32")
            if data.ndim == 2:
                data = data.mean(axis=1)
            gain = 15.0 if args.unclear_mic else 0.42 if args.quiet_mic else 1.3
            voice = np.clip(data * gain, -1, 1)
            if args.mild_noise:
                voice = np.clip(voice + np.random.default_rng(17).normal(0, 0.006, len(voice)), -1, 1)
            microphone = (np.zeros(int(sample_rate * 13), dtype=np.float32) if args.silent_mic else
                          np.concatenate([np.zeros(int(sample_rate * 0.6), dtype=np.float32),
                                          voice,
                                          np.zeros(int(sample_rate * (2.5 if args.unclear_mic else 5)), dtype=np.float32)]))
            result["fake_microphone_clipped_fraction"] = round(float(np.mean(np.abs(microphone) >= 0.985)), 4)
            microphone_path = tmp / "fake_microphone.wav"
            sf.write(microphone_path, microphone, sample_rate, subtype="PCM_16")
            result["fake_audio_seconds"] = round(len(microphone) / sample_rate, 2)

            # Warm both local speech models before timing the browser path.
            # Cold-start latency is recorded separately by preflight_local_models.py.
            warm_started = time.perf_counter()
            warm = httpx.post(api + "/api/v1/stt/transcribe?language=vi",
                              files={"file": ("warmup.wav", speech.content, "audio/wav")}, timeout=None)
            if warm.status_code != 200 or not warm.json().get("text"):
                raise RuntimeError(f"Qwen warmup HTTP {warm.status_code}")
            result["qwen_warmup_sec"] = round(time.perf_counter() - warm_started, 2)

            node = shutil.which("node")
            if not node:
                raise RuntimeError("node not installed")
            frontend_env = os.environ.copy()
            frontend_env["NEXT_PUBLIC_API_URL"] = api
            frontend_process = subprocess.Popen(
                [node, str(FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"),
                 "dev", "-H", "127.0.0.1", "-p", str(frontend_port)],
                cwd=FRONTEND, env=frontend_env, stdout=frontend_log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            wait_http(site + "/interview", frontend_process, 120)
            options_response = httpx.get(api + "/api/v1/cv/interview-options", timeout=30)
            options_response.raise_for_status()
            candidate_id, job_id = choose_pair(options_response.json())
            result["selection"] = {"candidate_id": candidate_id, "job_id": job_id}

            chrome = Options()
            for flag in ("--headless=new", "--window-size=1440,900", "--disable-gpu", "--no-sandbox", "--use-fake-ui-for-media-stream",
                         "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required",
                         "--use-file-for-fake-audio-capture=" + str(microphone_path)):
                chrome.add_argument(flag)
            chrome.set_capability("goog:loggingPrefs", {"browser": "ALL", "performance": "ALL"})
            browser = webdriver.Chrome(options=chrome)
            browser.execute_cdp_cmd("Network.enable", {})
            if args.unclear_mic or args.ambiguous_term:
                # Browser AGC can de-clip even a saturated fake input. Force
                # exactly one poor-capture flag at the WS boundary to exercise
                # the actual browser → ASR gate → Gemini → VieNeu → mic path.
                browser.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": """
                    (() => {
                      const original = WebSocket.prototype.send;
                      let forced = false;
                      WebSocket.prototype.send = function(data) {
                        try {
                          const message = JSON.parse(data);
                          if (!forced && message.type === 'final_transcript') {
                            forced = true;
                            if (UNCLEAR_MODE) {
                              message.payload.asr_evidence = {
                                ...(message.payload.asr_evidence || {}),
                                source: 'qwen_microphone', audio_quality_ok: false
                              };
                            } else {
                              message.payload.term_candidates = [{
                                raw: 'ri ác', recovered: 'React',
                                source: 'phonetic_lexicon', domain: 'frontend'
                              }];
                            }
                            data = JSON.stringify(message);
                          }
                        } catch (_) {}
                        return original.call(this, data);
                      };
                    })();
                """.replace("UNCLEAR_MODE", "true" if args.unclear_mic else "false")})
                result["forced_unclear_evidence_once"] = args.unclear_mic
                result["forced_term_candidate_once"] = args.ambiguous_term
            step = "open_setup"
            browser.set_page_load_timeout(60)
            browser.get(site + "/interview")
            step = "wait_cv_options"
            WebDriverWait(browser, 30).until(lambda d: len(Select(d.find_element(By.ID, "cv-choice")).options) > 1)
            step = "select_cv_job"
            Select(browser.find_element(By.ID, "cv-choice")).select_by_value(candidate_id)
            Select(browser.find_element(By.ID, "jd-choice")).select_by_value(job_id)
            step = "wait_demo_button"
            button = WebDriverWait(browser, 20).until(lambda d: d.find_element(By.XPATH, "//button[contains(.,'Chạy demo với lựa chọn này') and not(@disabled)]"))
            browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
            time.sleep(0.3)
            button.click()
            step = "wait_interview_navigation"
            WebDriverWait(browser, 45).until(lambda d: "/interview/" in d.current_url and d.current_url.rstrip("/") != site + "/interview")
            if args.force_vad_fallback:
                browser.get(browser.current_url.split("?", 1)[0] + "?forceEnergyVad=1")
            session_id = urlparse(browser.current_url).path.split("/")[-1]
            result["session_id"] = session_id
            print("BROWSER_SESSION", session_id, flush=True)
            step = "wait_first_spoken_answer"

            started = time.monotonic()
            manual_finish_used = False
            vad_ready_observed = False
            deadline = started + (45 if args.silent_mic else 200)
            while time.monotonic() < deadline:
                page_text = browser.find_element(By.TAG_NAME, "body").text
                if "Micro vẫn nghe qua nhịp dừng" in page_text:
                    vad_ready_observed = True
                state_resp = httpx.get(api + f"/api/v1/sessions/{session_id}/state", timeout=10)
                state = state_resp.json() if state_resp.status_code == 200 else {}
                answers = state.get("committed_answers") or []
                if answers:
                    result["first_answer"] = {"question": answers[0].get("question"),
                                              "transcript": answers[0].get("candidate_answer")}
                    result["first_answer_elapsed_sec"] = round(time.monotonic() - started, 2)
                    break
                time.sleep(1)
            result["manual_finish_used"] = manual_finish_used
            result["confirmation_used"] = False
            result["vad_ready_observed"] = vad_ready_observed
            result["pending_confirmation"] = bool((state or {}).get("pending_answer_transcript"))
            result["confirmation_button_count"] = len(browser.find_elements(By.XPATH, "//button[contains(.,'Xác nhận nội dung đúng')]"))
            result["candidate_bubble_count"] = len(browser.find_elements(By.XPATH, "//*[text()='Bạn']"))
            result["candidate_bubble_ids"] = [el.get_attribute("data-message-id") for el in browser.find_elements(By.CSS_SELECTOR, "[data-message-id^='cand_']")]
            result["page_text_excerpt"] = redact(browser.find_element(By.TAG_NAME, "body").text[-1500:])
            result["vad_error_banner"] = "Silero VAD lỗi:" in result["page_text_excerpt"]
            resources = browser.execute_script("return performance.getEntriesByType('resource').map(x => x.name)") or []
            result["silero_asset_requested"] = any("silero_vad.onnx" in url for url in resources)
            try:
                performance_entries = browser.execute_script("return performance.getEntriesByType('resource').map(x => x.name)") or []
                result["resource_paths"] = [urlparse(x).path for x in performance_entries if "/models/" in x][-15:]
            except Exception:
                pass
            result["silero_worker_present"] = vad_ready_observed
            result["automatic_endpoint_observed"] = vad_ready_observed
            result["effective_vad_mode"] = browser.find_element(By.CSS_SELECTOR, "[data-vad-mode]").get_attribute("data-vad-mode")
            result["browser_url"] = browser.current_url
            result["browser_console_errors"] = [redact(entry.get("message", "")[:250]) for entry in browser.get_log("browser")
                                                if entry.get("level") == "SEVERE"][:15]
            try:
                traffic = httpx.get(api + "/api/v1/debug/traffic", params={"limit": 500}, timeout=10).json()
                result["websocket_events"] = [
                    {"name": item.get("name"), "message_type": item.get("message_type"),
                     "payload_keys": item.get("payload_keys")}
                    for item in traffic.get("events", [])
                    if item.get("kind") == "websocket" and item.get("session_id") == session_id
                ][-35:]
            except Exception:
                pass
            try:
                failures = []
                for entry in browser.get_log("performance"):
                    message = json.loads(entry["message"]).get("message") or {}
                    if message.get("method") == "Network.loadingFailed":
                        failures.append({k: message.get("params", {}).get(k) for k in ("errorText", "blockedReason", "canceled")})
                result["network_failures"] = failures[-12:]
            except Exception:
                pass
            activity = httpx.get(api + "/api/v1/sessions/live-logs",
                                 params={"session_id": session_id, "limit": 500}, timeout=15)
            logs = activity.json().get("logs", []) if activity.status_code == 200 else []
            result["stages"] = sorted({row.get("stage") for row in logs if row.get("stage")})
            result["local_stt_timings"] = [
                {"kind": (row.get("details") or {}).get("kind"),
                 "latency_ms": (row.get("details") or {}).get("latency_ms"),
                 "audio_duration_sec": (row.get("details") or {}).get("audio_duration_sec"),
                 "text_length": (row.get("details") or {}).get("text_length")}
                for row in logs if row.get("stage") == "LOCAL_STT"
            ]
            result["client_voice_timings"] = [
                {"phase": (row.get("details") or {}).get("phase"),
                 "latency_ms": (row.get("details") or {}).get("latency_ms")}
                for row in logs if row.get("stage") in {"VOICE_ASR_TIMING", "VOICE_TURN_LATENCY", "VOICE_CLIENT_TIMING"}
            ]
            first_input_index = next((index for index, row in enumerate(logs)
                                      if row.get("stage") == "CANDIDATE_INPUT"), len(logs))
            result["opening_generation_count"] = sum(
                row.get("stage") == "QUESTION_ENGINE" for row in logs[:first_input_index]
            )
            result["unsafe_asr_gates"] = sum(
                row.get("stage") == "ASR_GATE" and (row.get("details") or {}).get("transcript_safe") is False
                for row in logs
            )
            result["automatic_spoken_reprompts"] = sum(row.get("stage") == "ASR_AUTO_REPROMPT" for row in logs)
            result["reprompt_generation_failures"] = sum(row.get("stage") == "ASR_REPROMPT_UNAVAILABLE" for row in logs)
            result["spoken_reprompt_ws_sent"] = any(
                event.get("name") == "WS send: stream_interruption" for event in result.get("websocket_events", [])
            )
            result["spoken_repeat_visible"] = bool(
                result["spoken_reprompt_ws_sent"] and result["automatic_spoken_reprompts"] > 0
                and result["page_text_excerpt"].count("Phỏng vấn viên AI") >= 2
            )
            passed = (
                result.get("first_answer") and result["automatic_endpoint_observed"]
                and "LOCAL_STT" in result["stages"] and "ASR_GATE" in result["stages"]
                and "LIVE_ORCHESTRATION" in result["stages"]
                and not manual_finish_used and result["confirmation_button_count"] == 0
                and not result["vad_error_banner"]
                and result["opening_generation_count"] == 1
                and (result["unsafe_asr_gates"] == 0 or
                     (result["automatic_spoken_reprompts"] > 0 and result["spoken_reprompt_ws_sent"]
                      and result["reprompt_generation_failures"] == 0
                      and result["spoken_repeat_visible"]))
            )
            if args.silent_mic:
                passed = not result.get("first_answer") and result["confirmation_button_count"] == 0
            if args.unclear_mic:
                passed = (
                    result["fake_microphone_clipped_fraction"] >= 0.12
                    and result["automatic_spoken_reprompts"] > 0
                    and result["spoken_reprompt_ws_sent"]
                    and result["confirmation_button_count"] == 0
                    and not manual_finish_used
                )
            if args.ambiguous_term:
                passed = (result["automatic_spoken_reprompts"] > 0
                          and result["spoken_reprompt_ws_sent"]
                          and result["confirmation_button_count"] == 0
                          and not manual_finish_used)
            if args.force_vad_fallback:
                passed = passed and result["effective_vad_mode"] == "energy"
            result["status"] = "PASS" if passed else "PARTIAL"
            print("BROWSER_RESULT", json.dumps({k: result.get(k) for k in
                   ("status", "first_answer_elapsed_sec", "manual_finish_used", "confirmation_used",
                    "silero_asset_requested", "stages")}, ensure_ascii=False), flush=True)
        except Exception as exc:
            result["failed_step"] = step
            result["error"] = f"{type(exc).__name__}: {exc}"[:500]
            if browser:
                try:
                    result["failure_url"] = browser.current_url
                    result["failure_page_text"] = redact(browser.find_element(By.TAG_NAME, "body").text[-1600:])
                    result["failure_browser_console"] = [redact(entry.get("message", "")[:300]) for entry in browser.get_log("browser")][-12:]
                except Exception:
                    pass
            print("BROWSER_ERROR", result["error"], flush=True)
        finally:
            if browser:
                try:
                    browser.quit()
                except Exception:
                    pass
            for process in (frontend_process, backend_process):
                if process and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
            backend_log.close()
            frontend_log.close()
            result["backend_log_tail"] = redact((tmp / "backend.log").read_text(encoding="utf-8", errors="replace")[-1800:])
            result["frontend_log_tail"] = redact((tmp / "frontend.log").read_text(encoding="utf-8", errors="replace")[-1800:])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("BROWSER_REPORT", report, flush=True)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
