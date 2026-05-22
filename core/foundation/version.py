# core/version.py

# NovaMind Granular Runtime Versions
# This file tracks independent versions for various runtime schemas to ensure replay compatibility.

RUNTIME_SCHEMA_VERSION = "1.0.0"     # Orchestration compatibility
WAL_SCHEMA_VERSION = "1.0.0"         # Replay log compatibility
SNAPSHOT_SCHEMA_VERSION = "1.0.0"    # Recovery integrity
IPC_PROTOCOL_VERSION = "1.0.0"       # Cross-process communication version
WORKER_PROTOCOL_VERSION = "1.0.0"    # Worker handshake validation
