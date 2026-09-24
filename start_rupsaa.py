#!/usr/bin/env python3

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = os.getenv("API_PORT", "8000")
WEB_PORT = os.getenv("WEB_PORT", "5500")

# Passed down to the web/proxy server (web/dev_server.py) via the environment
# so it knows where to forward /api/* requests. Always loopback: the proxy
# and FastAPI run on the same VM, and only the web server's port needs to be
# forwarded out (e.g. Lightning Studio's forwarded-port URL for WEB_PORT).
os.environ["API_HOST"] = API_HOST
os.environ["API_PORT"] = API_PORT
os.environ["WEB_PORT"] = WEB_PORT
os.environ.setdefault("RUPSAA_BACKEND_URL", f"http://127.0.0.1:{API_PORT}")

processes = []


def banner():
    print("\n" + "=" * 62)
    print("                 🌸 RUPSAA AI 🌸")
    print("=" * 62)
    print("Starting Rupsaa services...\n")


def check_project():
    required = [
        ROOT / "api" / "main.py",
        WEB_DIR,
        WEB_DIR / "dev_server.py",
    ]

    missing = [str(path) for path in required if not path.exists()]

    if missing:
        print("❌ Rupsaa project files are missing:")
        for path in missing:
            print(f"   - {path}")
        sys.exit(1)


def start_process(name, command, cwd):
    print(f"▶ Starting {name}...")

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=os.environ.copy(),
    )

    processes.append((name, process))
    return process


def stop_all(*_):
    print("\n\n🛑 Stopping Rupsaa...")

    for name, process in reversed(processes):
        if process.poll() is None:
            print(f"   Stopping {name}...")
            process.terminate()

    # Give processes a moment to exit cleanly.
    deadline = time.time() + 5

    while time.time() < deadline:
        if all(p.poll() is not None for _, p in processes):
            break
        time.sleep(0.2)

    # Force-kill anything that refused to stop.
    for name, process in processes:
        if process.poll() is None:
            print(f"   Force stopping {name}...")
            process.kill()

    print("\n🌸 Rupsaa stopped.\n")
    sys.exit(0)


def main():
    banner()
    check_project()

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    api = start_process(
        "FastAPI backend",
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.main:app",
            "--host",
            API_HOST,
            "--port",
            str(API_PORT),
        ],
        ROOT,
    )

    # Give FastAPI a moment to initialize.
    time.sleep(2)

    if api.poll() is not None:
        print("\n❌ FastAPI failed to start.")
        stop_all()

    web = start_process(
        "Web interface + API proxy",
        [
            sys.executable,
            str(WEB_DIR / "dev_server.py"),
        ],
        WEB_DIR,
    )

    time.sleep(1)

    if web.poll() is not None:
        print("\n❌ Web server failed to start.")
        stop_all()

    print("\n" + "=" * 62)
    print("✅ RUPSAA IS RUNNING")
    print("=" * 62)

    print(f"""
FastAPI (internal only — do not forward this port):
    http://127.0.0.1:{API_PORT}
    http://127.0.0.1:{API_PORT}/docs
    http://127.0.0.1:{API_PORT}/health

Web UI + API proxy (this is the only port to open):
    http://localhost:{WEB_PORT}
    /api/* on this port is proxied internally to FastAPI on 127.0.0.1:{API_PORT}

On Lightning AI Studio:
    Open/forward ONLY port {WEB_PORT} from the Studio UI, then open that
    forwarded HTTPS URL in your browser. Do NOT forward port {API_PORT} —
    the web server reaches it internally over 127.0.0.1, and the browser
    never needs to know it exists.

NOTE:
    The AI model may load lazily when you send the first message.
    The first response can therefore take longer.

Press Ctrl+C to stop everything.
""")

    # Keep launcher alive and watch both child processes.
    try:
        while True:
            for name, process in processes:
                return_code = process.poll()

                if return_code is not None:
                    print(
                        f"\n❌ {name} exited unexpectedly "
                        f"(code {return_code})."
                    )
                    stop_all()

            time.sleep(1)

    except KeyboardInterrupt:
        stop_all()


if __name__ == "__main__":
    main()