from typing import Dict, Any, List

class RuntimeInspector:
    """
    Diagnostic API for mapping the deterministic runtime topology.
    Does not mutate state. Strictly read-only introspection.
    """
    
    def __init__(self, kernel_supervisor=None):
        self._kernel = kernel_supervisor

    def get_worker_topology(self) -> Dict[str, Any]:
        """Returns a snapshot of all active workers and their FSM states."""
        if not self._kernel:
            return {"error": "Kernel not attached"}
            
        topology = {}
        for worker_id, supervisor in self._kernel.workers.items():
            topology[worker_id] = {
                "state": supervisor.state.value,
                "pid": supervisor.process.pid if supervisor.process else None,
                "sandbox_profile": supervisor.sandbox.profile_name,
                "identity": supervisor.identity.dict()
            }
        return topology

    def get_active_capabilities(self) -> Dict[str, List[str]]:
        """Maps workers to their granted capability leases."""
        # This will query the CapabilityPolicyLayer or Broker once fully integrated
        return {"TODO": ["capability tracking layer"]}

    def get_wal_cursors(self) -> Dict[str, Any]:
        """Gets current logical clock and epoch state for replay lineage."""
        return {
            "logical_clock": "TODO",
            "epoch_id": "TODO",
            "uncommitted_events": "TODO"
        }
