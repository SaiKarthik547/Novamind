import os
import sys
import libcst as cst
from libcst.metadata import PositionProvider
from pathlib import Path

class LegacyExecutionAnnotator(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self):
        super().__init__()
        self.modifications_made = 0

    def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.CSTNode:
        # Detect subprocess.run, subprocess.Popen, os.system, pyautogui.*, socket.*
        func_node = updated_node.func
        
        is_legacy = False
        if isinstance(func_node, cst.Attribute) and isinstance(func_node.value, cst.Name):
            module_name = func_node.value.value
            method_name = func_node.attr.value
            
            if module_name == "subprocess" and method_name in ("run", "Popen", "call", "check_call", "check_output"):
                is_legacy = True
            elif module_name == "os" and method_name in ("system", "popen", "spawnl", "spawnv"):
                is_legacy = True
            elif module_name == "pyautogui":
                is_legacy = True
            elif module_name == "socket":
                is_legacy = True
                
        if is_legacy:
            self.modifications_made += 1
            # We wrap the node in a simple statement line so we can attach a comment above it
            # But leave_Call only replaces the Call node itself.
            # To add a comment above, we actually need to transform SimpleStatementLine.
            pass
            
        return updated_node

class LegacyStatementAnnotator(cst.CSTTransformer):
    """
    Transforms entire statement lines to inject comments directly above legacy calls.
    """
    def __init__(self):
        super().__init__()
        self.modifications = 0

    def _is_legacy_call(self, node: cst.CSTNode) -> bool:
        if isinstance(node, cst.Call):
            if isinstance(node.func, cst.Attribute) and isinstance(node.func.value, cst.Name):
                mod = node.func.value.value
                meth = node.func.attr.value
                if mod == "subprocess" and meth in ("run", "Popen", "call", "check_output"): return True
                if mod == "os" and meth in ("system", "popen"): return True
                if mod == "pyautogui": return True
                if mod == "socket": return True
        return False

    def leave_SimpleStatementLine(self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine) -> cst.CSTNode:
        # Check if any part of this statement is a legacy call
        has_legacy = False
        
        # A quick visitor to check for legacy calls inside the statement
        class CallVisitor(cst.CSTVisitor):
            def __init__(self, checker):
                self.found = False
                self.checker = checker
            def visit_Call(self, node: cst.Call):
                if self.checker(node):
                    self.found = True
                    
        visitor = CallVisitor(self._is_legacy_call)
        original_node.visit(visitor)
        
        if visitor.found:
            # Check if it already has the annotation
            existing_comments = [c.comment.value for c in updated_node.leading_lines if isinstance(c, cst.EmptyLine) and c.comment]
            if not any("LEGACY_EXECUTION_PATH" in c for c in existing_comments):
                self.modifications += 1
                new_leading = list(updated_node.leading_lines)
                new_leading.append(cst.EmptyLine(comment=cst.Comment("# LEGACY_EXECUTION_PATH: Needs Intent Dispatcher Migration")))
                return updated_node.with_changes(leading_lines=tuple(new_leading))
                
        return updated_node

def migrate_file(filepath: Path):
    with open(filepath, "r", encoding="utf-8") as f:
        source_code = f.read()

    tree = cst.parse_module(source_code)
    transformer = LegacyStatementAnnotator()
    modified_tree = tree.visit(transformer)

    if transformer.modifications > 0:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(modified_tree.code)
        print(f"Annotated {transformer.modifications} legacy paths in {filepath}")
    else:
        print(f"No legacy paths found or already annotated in {filepath}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ast_migration_tool.py <target_directory_or_file>")
        sys.exit(1)
        
    target = Path(sys.argv[1])
    if target.is_file() and target.suffix == ".py":
        migrate_file(target)
    elif target.is_dir():
        for root, _, files in os.walk(target):
            for file in files:
                if file.endswith(".py"):
                    migrate_file(Path(root) / file)
