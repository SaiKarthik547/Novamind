import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class DivergenceAnalyzer:
    """
    Strictly measures semantic divergence between Python authoritative state and Godot client state.
    Does NOT enforce policy (that is the Supervisor's job).
    """
    
    def __init__(self):
        # Weights for divergence calculation
        self.weights = {
            "missing_task": 0.4,
            "ghost_task": 0.4,
            "state_mismatch": 0.2
        }

    def compute_divergence(self, python_state: Dict[str, Any], godot_state: Dict[str, Any]) -> float:
        """
        Returns a health score between 0.0 (completely divergent) and 1.0 (perfectly synchronized).
        """
        py_tasks = set(python_state.get("active_tasks", []))
        gd_tasks = set(godot_state.get("active_tasks", []))
        
        missing = py_tasks - gd_tasks
        ghosts = gd_tasks - py_tasks
        
        divergence = 0.0
        
        # Calculate divergence
        if missing:
            logger.warning(f"[DivergenceAnalyzer] Missing tasks in Godot: {missing}")
            divergence += self.weights["missing_task"] * (len(missing) / max(1, len(py_tasks)))
            
        if ghosts:
            logger.warning(f"[DivergenceAnalyzer] Ghost tasks in Godot (not in Python): {ghosts}")
            divergence += self.weights["ghost_task"] * (len(ghosts) / max(1, len(gd_tasks)))
            
        # Additional state mismatches (e.g., specific statuses) could be added here
        
        score = max(0.0, 1.0 - divergence)
        
        if score < 1.0:
            logger.warning(f"[DivergenceAnalyzer] System health measured at {score:.2f}")
            
        return score
