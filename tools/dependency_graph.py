import ast
import os
import sys
from collections import defaultdict

def get_imports(filepath):
    imports = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=filepath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
    except Exception as e:
        import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
        pass
    return imports

def find_cycles(graph):
    cycles = []
    visited = set()
    path = []
    
    def dfs(node):
        if node in path:
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return
        if node in visited:
            return
        
        visited.add(node)
        path.append(node)
        for neighbor in graph.get(node, []):
            dfs(neighbor)
        path.pop()

    for node in graph.keys():
        dfs(node)
    
    # Deduplicate cycles (shifting them)
    unique_cycles = []
    seen = set()
    for cycle in cycles:
        c_tuple = tuple(sorted(cycle))
        if c_tuple not in seen:
            seen.add(c_tuple)
            unique_cycles.append(cycle)
    return unique_cycles

def main():
    root_dirs = ['core', 'agents', 'ui', 'vision', 'workers']
    graph = defaultdict(list)
    module_to_file = {}
    
    # Discover all modules
    for root_dir in root_dirs:
        for dirpath, _, filenames in os.walk(root_dir):
            for f in filenames:
                if f.endswith('.py'):
                    filepath = os.path.join(dirpath, f)
                    # Convert to module name: core/brain.py -> core.brain
                    mod_name = os.path.splitext(filepath)[0].replace(os.sep, '.')
                    if mod_name.endswith('.__init__'):
                        mod_name = mod_name[:-9]
                    module_to_file[mod_name] = filepath
                    
    # Build graph
    for mod_name, filepath in module_to_file.items():
        imports = get_imports(filepath)
        for imp in imports:
            # Only care about internal imports
            if any(imp.startswith(prefix) for prefix in ['core', 'agents', 'ui', 'vision', 'workers']):
                graph[mod_name].append(imp)

    cycles = find_cycles(graph)
    print(f"Found {len(cycles)} cycles.")
    for c in cycles:
        print(" -> ".join(c))

if __name__ == '__main__':
    main()