from typing import List, Dict, Any

class ReplayVisualizer:
    """
    Deterministic replay timeline generator.
    Produces causal DAGs and event lineages for forensic debugging.
    """
    
    def __init__(self, telemetry_sink_path: str, wal_directory: str):
        self.telemetry_path = telemetry_sink_path
        self.wal_directory = wal_directory

    def generate_timeline(self, start_timestamp_ns: int, end_timestamp_ns: int) -> List[Dict[str, Any]]:
        """
        Extracts ordered events combining WAL checkpoints and FORENSIC telemetry.
        """
        events = []
        try:
            import os
            import json
            
            # Read WAL events
            if os.path.exists(self.wal_directory):
                wal_path = os.path.join(self.wal_directory, "recovery.wal")
                if os.path.exists(wal_path):
                    with open(wal_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            if not line.strip(): continue
                            try:
                                record = json.loads(line)
                                # Basic time-boxing simulation if timestamp existed
                                # Currently RecoveryJournal does not inject a timestamp, we append it directly
                                events.append({
                                    "source": "WAL",
                                    "intent_id": record.get("intent_id"),
                                    "state": record.get("state"),
                                    "payload": record.get("payload")
                                })
                            except json.JSONDecodeError:
                                pass
                                
            # Read telemetry events
            if os.path.exists(self.telemetry_path):
                with open(self.telemetry_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip(): continue
                        try:
                            record = json.loads(line)
                            ts = record.get("timestamp_ns", 0)
                            if start_timestamp_ns <= ts <= end_timestamp_ns:
                                events.append({
                                    "source": "TELEMETRY",
                                    "event_type": record.get("event_type"),
                                    "timestamp_ns": ts,
                                    "data": record.get("data")
                                })
                        except json.JSONDecodeError:
                            pass
                            
            return events
        except Exception as e:
            return [{"error": f"Failed to generate timeline: {e}"}]

    def export_causal_dag_mermaid(self) -> str:
        """
        Exports the current execution transaction graph as a Mermaid.js diagram.
        """
        timeline = self.generate_timeline(0, 2**63 - 1)
        
        mermaid_src = ["graph TD"]
        
        last_node = None
        for idx, event in enumerate(timeline):
            node_id = f"E{idx}"
            if event.get("source") == "WAL":
                label = f"{event.get('state', 'UNKNOWN')} ({event.get('intent_id', 'none')[:6]})"
                mermaid_src.append(f'    {node_id}["{label}"]')
            else:
                label = f"{event.get('event_type', 'TELEMETRY')}"
                mermaid_src.append(f'    {node_id}("{label}")')
                
            if last_node:
                mermaid_src.append(f"    {last_node} --> {node_id}")
            last_node = node_id
            
        if len(mermaid_src) == 1:
            mermaid_src.append("    Empty[No Events Found]")
            
        return "\n".join(mermaid_src)
