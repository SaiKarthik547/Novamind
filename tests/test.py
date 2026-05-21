# save as quick_status.py and run: py quick_status.py
import subprocess, sys, os

files = [
    "agents/verifier_agent.py",
    "agents/system_agent.py",
    "agents/browser_agent.py",
    "agents/application_agent.py",
    "core/uia_executor.py",
    "core/task_parser.py",
    "game/nova_mindscape.py",
    "main.py",
]

print("=== IMPORT STATUS ===")
for f in files:
    if not os.path.exists(f):
        print(f"MISSING | {f}")
        continue
    r = subprocess.run(
        [sys.executable, "-c", f"import runpy; runpy.run_path('{f}')"],
        capture_output=True, text=True, cwd=os.getcwd()
    )
    status = "OK" if r.returncode == 0 else "ERROR"
    lines = r.stderr.strip().split("\n") if r.stderr.strip() else []
    last = lines[-1] if lines else ""
    print(f"{status} | {f}")
    if r.returncode != 0:
        print(f"       {last}")

print("\n=== LINE COUNTS ===")
for f in files:
    if os.path.exists(f):
        with open(f) as fh:
            n = sum(1 for _ in fh)
        print(f"{n:5d} lines | {f}")