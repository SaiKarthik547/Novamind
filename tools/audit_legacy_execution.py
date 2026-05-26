import os
import sys
import ast

def audit_directory(directory: str):
    """
    P14G-1: Audits the codebase to ensure NO new agents or adapters are
    circumventing the Kernel Execution Facade by using subprocess directly
    or claiming UNSAFE_RUNTIME authority.
    """
    violations = []
    
    for root, _, files in os.walk(directory):
        if "venv" in root or ".git" in root or "tests" in root:
            continue
            
        for file in files:
            if not file.endswith(".py"):
                continue
                
            filepath = os.path.join(root, file)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                
            # Direct usage of subprocess outside of the specific allowed adapter
            if "subprocess" in content and not any(allowed in filepath for allowed in ["core\\execution", "core/execution", "core\\legacy", "core/legacy", "tools", "core\\adapters", "core/adapters"]):
                violations.append((filepath, "Imports 'subprocess'. All subprocess execution MUST route through KernelExecutionFacade via 'shell.execute'."))
                
            # Hardcoded usage of UNSAFE_RUNTIME authority
            if "UNSAFE_RUNTIME" in content and not ("capability_registry.py" in filepath or "kernel_facade.py" in filepath or "test_" in filepath):
                violations.append((filepath, "Claims 'UNSAFE_RUNTIME' authority. This authority level is strictly quarantined."))

    return violations

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=str, help="Path to baseline file containing known violations")
    parser.add_argument("--generate-baseline", type=str, help="Generate a new baseline file")
    args = parser.parse_args()

    print("Running Legacy Execution Audit...")
    
    core_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core"))
    
    if not os.path.exists(core_dir):
        print(f"Error: Core directory not found at {core_dir}")
        sys.exit(1)
        
    violations = audit_directory(core_dir)
    
    if args.generate_baseline:
        with open(args.generate_baseline, "w") as f:
            for filepath, reason in violations:
                # Strip the absolute path prefix for stable baselines
                rel_path = os.path.relpath(filepath, core_dir).replace("\\", "/")
                f.write(f"{rel_path}:{reason}\n")
        print(f"Baseline generated at {args.generate_baseline} with {len(violations)} violations.")
        sys.exit(0)
        
    new_violations = list(violations)
    if args.baseline and os.path.exists(args.baseline):
        with open(args.baseline, "r") as f:
            baseline_lines = [line.strip() for line in f.readlines()]
            
        filtered = []
        for filepath, reason in violations:
            rel_path = os.path.relpath(filepath, core_dir).replace("\\", "/")
            sig = f"{rel_path}:{reason}"
            if sig not in baseline_lines:
                filtered.append((filepath, reason))
        new_violations = filtered

    if new_violations:
        print("\n[!] NEW LEGACY EXECUTION ESCAPE DETECTED [!]", file=sys.stderr)
        print("The following files circumvent the KernelExecutionFacade or claim quarantined authority:\n", file=sys.stderr)
        for filepath, reason in new_violations:
            print(f"  - {filepath}: {reason}", file=sys.stderr)
        print("\nFix these violations to pass Phase 14 Certification.", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Legacy Execution Audit: PASS ({len(violations)} legacy exceptions grandfathered)")
        sys.exit(0)

if __name__ == "__main__":
    main()
