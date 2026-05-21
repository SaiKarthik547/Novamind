#!/usr/bin/env python3
import json
import importlib.util
import os
import sys

sys.path.insert(0, os.getcwd())
spec = importlib.util.spec_from_file_location("main", os.path.join(os.getcwd(), "main.py"))
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)

print(json.dumps(main.check_dependencies(), indent=2))
