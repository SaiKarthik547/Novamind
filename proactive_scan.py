import os
import re
import io

def scan_files():
    findings = []
    root_dir = r"c:\Users\karth\OneDrive\Desktop\novamind"
    
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if not file.endswith(".py"):
                continue
            path = os.path.join(root, file)
            rel_path = os.path.relpath(path, root_dir)
            
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
            except:
                continue

            # SCAN 3: Unicode in logs
            for i, line in enumerate(lines):
                if "logger." in line:
                    unicode_chars = re.findall(r"[^\x00-\x7F]", line)
                    if unicode_chars:
                        findings.append(f"SCAN 3 (Unicode in Log): {rel_path}:{i+1} - {line.strip()}")

            # SCAN 5: getattr without defaults
            for i, line in enumerate(lines):
                if "getattr(" in line:
                    # Simple regex to find getattr with exactly 2 args
                    # This is naive but helpful
                    m = re.search(r"getattr\([^,]+,\s*[^,]+\)", line)
                    if m:
                        findings.append(f"SCAN 5 (getattr no default): {rel_path}:{i+1} - {line.strip()}")

            # SCAN 6: subprocess without timeout
            for i, line in enumerate(lines):
                if (("subprocess.run" in line or "subprocess.check_output" in line) and "timeout=" not in line):
                    findings.append(f"SCAN 6 (subprocess no timeout): {rel_path}:{i+1} - {line.strip()}")
                if ".communicate(" in line and "timeout=" not in line:
                    findings.append(f"SCAN 6 (communicate no timeout): {rel_path}:{i+1} - {line.strip()}")

            # SCAN 7: SQLite without context manager
            for i, line in enumerate(lines):
                if "sqlite3.connect(" in line and "with " not in line:
                    findings.append(f"SCAN 7 (SQLite no with): {rel_path}:{i+1} - {line.strip()}")

            # SCAN 4: Missing dict keys (hard access)
            # Look for dict["key"] where dict is likely a result or parameters
            for i, line in enumerate(lines):
                if re.search(r'\["[a-zA-Z0-9_]+"\]', line) and " = " not in line and "def " not in line:
                    # Check if it's inside a try/except
                    # (This is hard with regex, but we'll flag it for review)
                    if ".get(" not in line:
                        findings.append(f"SCAN 4 (Dict hard access): {rel_path}:{i+1} - {line.strip()}")

    return findings

if __name__ == "__main__":
    results = scan_files()
    with open("scan_results.txt", "w", encoding="utf-8") as f:
        for r in results:
            f.write(r + "\n")
