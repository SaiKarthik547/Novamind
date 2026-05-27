import ast
import os
import sys

def check_file_for_illegal_singletons(filepath: str) -> list[str]:
    violations = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content)
    except Exception as e:
        return [f"Failed to parse {filepath}: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                # Check for .get_instance() calls on Authority singletons outside of approved transition files
                if node.func.attr == "get_instance":
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id in ("RuntimeKernel", "KernelSupervisor"):
                            if "kernel_facade.py" not in filepath and "runtime_kernel.py" not in filepath and "test" not in filepath and "agent_context.py" not in filepath:
                                violations.append(f"Illegal singleton usage: {node.func.value.id}.get_instance() at line {node.lineno}")
    return violations

def main():
    print("Running Runtime Topology Static Audit...")
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    core_dir = os.path.join(project_root, "core")
    
    total_violations = []
    
    for root, _, files in os.walk(core_dir):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                violations = check_file_for_illegal_singletons(filepath)
                if violations:
                    total_violations.extend([f"{os.path.relpath(filepath, project_root)}: {v}" for v in violations])
                    
    if total_violations:
        print("STATIC AUDIT FAILED! Topology Violations Found:")
        for v in total_violations:
            print(f"  - {v}")
        sys.exit(1)
    else:
        print("STATIC AUDIT PASSED. Topology boundaries are intact.")
        sys.exit(0)

if __name__ == "__main__":
    main()
