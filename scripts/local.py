"""Start/stop only this workspace's processes; no Docker or Redis required."""

import argparse
import json
import os
import socket
import subprocess
import time
from pathlib import Path

import psutil
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "storage" / "processes.json"
PYTHON = (
    ROOT / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt"
    else ROOT / ".venv" / "bin" / "python"
)


def free(port):
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def owned(process, entry):
    try:
        return (
            abs(process.create_time() - entry["created"]) < 1
            and Path(process.cwd()).resolve() in (ROOT, ROOT / "frontend")
            and all(x in " ".join(process.cmdline()) for x in entry["markers"])
        )
    except (psutil.Error, OSError):
        return False


def stop():
    if not STATE.exists():
        print("No application processes recorded.")
        return
    entries = json.loads(STATE.read_text())
    for name, entry in entries.items():
        try:
            proc = psutil.Process(entry["pid"])
            if not owned(proc, entry):
                print(f"{name}: no matching workspace process; left untouched.")
                continue
            children = proc.children(recursive=True)
            for child in children:
                child.terminate()
            proc.terminate()
            _, alive = psutil.wait_procs(children + [proc], timeout=8)
            for child in alive:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            print(name + ": stopped")
        except psutil.NoSuchProcess:
            pass
    STATE.unlink(missing_ok=True)


def start(dev=False):
    os.chdir(ROOT)
    if not PYTHON.exists():
        raise SystemExit("Run setup-local.cmd first.")
    env_values = dotenv_values(ROOT / ".env")
    api_port = int(env_values.get("API_PORT") or 8010)
    front_port = int(env_values.get("FRONTEND_PORT") or 3000)
    if STATE.exists():
        entries = json.loads(STATE.read_text())
        for entry in entries.values():
            try:
                if owned(psutil.Process(entry["pid"]), entry):
                    raise SystemExit(
                        "ReconcileAI is already running. Use stop-local.cmd before restarting."
                    )
            except psutil.NoSuchProcess:
                pass
    for port in (api_port, front_port):
        if not free(port):
            raise SystemExit(
                f"Port {port} is occupied. Set API_PORT/FRONTEND_PORT in .env; no existing process was stopped."
            )
    subprocess.run([str(PYTHON), "-m", "alembic", "upgrade", "head"], check=True, cwd=ROOT)
    if not (ROOT / "synthetic_data/generated/happy_path/manifest.json").exists():
        subprocess.run(
            [str(PYTHON), "-m", "synthetic_data", "generate", "--all", "--seed", "42"],
            check=True,
            cwd=ROOT,
        )
    node = __import__("shutil").which("node")
    if not node:
        raise SystemExit("Node.js is required.")
    if not dev and not (ROOT / "frontend/.next/BUILD_ID").exists():
        raise SystemExit("Frontend build missing. Run setup-local.cmd or start with --dev.")
    env = os.environ.copy()
    env["RECONCILE_API_ORIGIN"] = f"http://127.0.0.1:{api_port}"
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    for key in ("HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME"):
        env[key] = str(ROOT / "storage/model-cache")
    env["HF_HUB_DISABLE_XET"] = "1"
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    logs = ROOT / "storage/logs"
    logs.mkdir(parents=True, exist_ok=True)
    commands = {
        "api": (
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "backend.app.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            ROOT,
            ["uvicorn", "backend.app.api:app"],
        ),
        "worker": (
            [str(PYTHON), "-m", "backend.app.worker"],
            ROOT,
            ["backend.app.worker"],
        ),
        "frontend": (
            [
                node,
                str(ROOT / "frontend/node_modules/next/dist/bin/next"),
                "dev" if dev else "start",
                "--hostname",
                "127.0.0.1",
                "--port",
                str(front_port),
            ],
            ROOT / "frontend",
            ["next", "dev" if dev else "start"],
        ),
    }
    entries = {}
    try:
        for name, (cmd, cwd, markers) in commands.items():
            out = (logs / f"{name}.log").open("ab")
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            out.close()
            process = psutil.Process(proc.pid)
            entries[name] = {
                "pid": proc.pid,
                "created": process.create_time(),
                "markers": markers,
            }
        STATE.write_text(json.dumps(entries, indent=2))
        import httpx

        for _ in range(60):
            try:
                if httpx.get(
                    f"http://127.0.0.1:{api_port}/health", timeout=1
                ).status_code == 200 and not free(front_port):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("Startup timed out; inspect storage/logs.")
        print(f"ReconcileAI: http://127.0.0.1:{front_port}")
        print(f"API docs: http://127.0.0.1:{api_port}/docs")
        print("Logs: storage/logs | Stop: stop-local.cmd")
    except Exception:
        STATE.write_text(json.dumps(entries))
        stop()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "status"])
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    if args.command == "start":
        start(args.dev)
    elif args.command == "stop":
        stop()
    else:
        print(STATE.read_text() if STATE.exists() else "Not running through the launcher")
