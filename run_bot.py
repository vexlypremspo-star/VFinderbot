import os
import signal
import subprocess
import sys
import time

CHILDREN = ["bot.py", "monitor.py"]
processes = {}


def start(name):
    print(f"[launcher] Starting {name}...", flush=True)
    return subprocess.Popen([sys.executable, name], env=os.environ.copy())


def stop_all():
    for name, proc in list(processes.items()):
        if proc.poll() is None:
            print(f"[launcher] Stopping {name}...", flush=True)
            try:
                proc.terminate()
            except Exception:
                pass

    deadline = time.time() + 10
    while time.time() < deadline:
        if all(proc.poll() is not None for proc in processes.values()):
            return
        time.sleep(0.2)

    for proc in processes.values():
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass


def handle_signal(signum, frame):
    print(f"[launcher] Received signal {signum}.", flush=True)
    stop_all()
    raise SystemExit(0)


signal.signal(signal.SIGINT, handle_signal)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, handle_signal)

for name in CHILDREN:
    processes[name] = start(name)

while True:
    time.sleep(2)

    for name, proc in list(processes.items()):
        code = proc.poll()
        if code is not None:
            print(
                f"[launcher] {name} stopped with exit code {code}. "
                "Stopping the other process so the worker can restart cleanly.",
                flush=True,
            )
            stop_all()
            raise SystemExit(1)
