import logging
import logging.handlers
import os
import sys
from datetime import datetime
from typing import Optional

_initialized = False

def setup_structured_logging(log_dir: str = "logs"):
    global _initialized
    if _initialized:
        return
        
    os.makedirs(log_dir, exist_ok=True)
    
    # Base formatter
    formatter = logging.Formatter("%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s")
    
    # stdout handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # We want specific modules to go to specific files
    loggers_config = {
        "ai": ["core.brain", "core.task_manager", "core.state_manager", "agents.code_agent"],
        "bridge": ["core.bridge_server"],
        "godot": ["core.game_bridge"], # Assuming godot logs come through bridge
        "automation": ["agents.system_agent", "agents.application_agent", "agents.browser_agent"]
    }
    
    # Create file handlers
    handlers = {}
    for log_name in loggers_config.keys():
        file_path = os.path.join(log_dir, f"{log_name}.log")
        handler = logging.handlers.RotatingFileHandler(file_path, maxBytes=10*1024*1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(formatter)
        handlers[log_name] = handler
        
    # Catch-all file handler for root
    main_file_path = os.path.join(log_dir, "novamind.log")
    main_handler = logging.handlers.RotatingFileHandler(main_file_path, maxBytes=10*1024*1024, backupCount=3, encoding='utf-8')
    main_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(main_handler)
    
    # Route specific modules
    for log_name, module_names in loggers_config.items():
        handler = handlers[log_name]
        for module in module_names:
            logger = logging.getLogger(module)
            logger.addHandler(handler)
            logger.propagate = True # Also send to root for console/main log
            
    _initialized = True

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
