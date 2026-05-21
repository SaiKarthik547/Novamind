#!/usr/bin/env python3
import sys
import subprocess
import json
import os
import glob

def check_file(path, timeout=30):
    cmd = [sys.executable, "-c", "import runpy,sys,traceback; p=sys.argv[1];\ntry:\n    runpy.run_path(p, run_name='__main__')\n    print('OK')\nexcept SystemExit as e:\n    print('SYS_EXIT', e.code)\n    sys.exit(0)\nexcept Exception:\n    traceback.print_exc(); sys.exit(2)", path]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = res.stdout
        err = res.stderr
        code = res.returncode
    except subprocess.TimeoutExpired as e:
        return {"path": path, "status": "TIMEOUT", "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"path": path, "status": "ERROR", "error": str(e)}
    return {"path": path, "status": ("OK" if code == 0 else "ERROR"), "returncode": code, "stdout": out, "stderr": err}


def main():
    targets = []
    if len(sys.argv) > 1:
        targets = sys.argv[1:]
    else:
        dirs = ["core", "agents", "memory", "security", "vision", "ui", "game"]
        for d in dirs:
            pattern = os.path.join(d, "**", "*.py")
            targets.extend(glob.glob(pattern, recursive=True))
        for f in ["main.py", "config.py", "proactive_scan.py"]:
            if os.path.isfile(f):
                targets.append(f)
    results = []
    targets = sorted(set(targets))
    for path in targets:
        print(f"Checking {path}...")
        r = check_file(path)
        results.append(r)
        print(json.dumps(r))
    outpath = "import_check_results.json"
    with open(outpath, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)
    # exit code non-zero if any errors/timeouts
    if any(r.get("status") not in ("OK","SYS_EXIT") for r in results):
        sys.exit(2)

if __name__ == '__main__':
    main()
