import os
import json
import logging
from typing import Dict, Any

from core.execution.recovery_journal import RecoveryJournal
from core.execution.capability_registry import ReplayPolicy, CAPABILITY_REGISTRY

logger = logging.getLogger("ReplayCoordinator")

class ReplayCoordinator:
    """
    Phase 15C: Owns replay sequencing, intent reconstruction, and divergence classification.

    Reads from RecoveryJournal (durability owner).
    Coordinates intent reconstruction with the canonical execution authority.

    IMPORTANT:
    - This coordinator does NOT invent its own state invariants.
    - It uses the canonical IntentExecutionState machine for divergence checks.
    - Capability lookup uses CAPABILITY_REGISTRY.get(), not invented APIs.
    """
    def __init__(self, journal: RecoveryJournal):
        self.journal = journal
        self._reconstructed_intents: Dict[str, Any] = {}

    def analyze_lineage(self) -> Dict[str, Any]:
        """
        Reads the RecoveryJournal and reconstructs the causal graph and state of all intents.
        """
        logger.info("ReplayCoordinator: Analyzing journal lineage.")

        self._reconstructed_intents.clear()
        divergences = 0

        filepath = self.journal.filepath
        if not os.path.exists(filepath):
            return {"reconstructed_intents": 0, "divergences_detected": 0}

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        intent_id = record.get("intent_id")
                        state_val = record.get("state")
                        payload = record.get("payload", {})

                        if not intent_id:
                            continue

                        is_first_record = intent_id not in self._reconstructed_intents
                        if is_first_record:
                            self._reconstructed_intents[intent_id] = {
                                "id": intent_id,
                                "state": state_val,
                                "payload": payload,
                                "history": []
                            }

                        self._reconstructed_intents[intent_id]["history"].append(record)

                        # Validate state machine invariants using canonical execution state.
                        # The FIRST record has no predecessor to transition from — comparing
                        # it against itself would flag a spurious divergence on every intent.
                        try:
                            from core.execution.intent_execution_state import IntentExecutionState

                            curr_enum = IntentExecutionState(self._reconstructed_intents[intent_id]["state"]) if self._reconstructed_intents[intent_id]["state"] else None
                            next_enum = IntentExecutionState(state_val) if state_val else None

                            if not is_first_record and curr_enum is not None and next_enum is not None:
                                from core.execution.intent_execution_state import LEGAL_TRANSITIONS
                                allowed = LEGAL_TRANSITIONS.get(curr_enum, frozenset())
                                if next_enum not in allowed:
                                    logger.error(
                                        f"Divergence detected: Intent {intent_id} attempted illegal transition "
                                        f"{curr_enum.value} -> {next_enum.value}"
                                    )
                                    divergences += 1
                        except ValueError:
                            # State value not in canonical Enum; legacy WAL or corruption
                            divergences += 1

                        self._reconstructed_intents[intent_id]["state"] = state_val

                    except json.JSONDecodeError:
                        logger.error("Failed to parse WAL record.")
                        divergences += 1

        except OSError as e:
            logger.error(f"Failed to read recovery journal: {e}")
            divergences += 1

        return {
            "reconstructed_intents": len(self._reconstructed_intents),
            "divergences_detected": divergences,
            "intents": self._reconstructed_intents
        }

    def execute_replay_plan(self, kernel_dispatcher) -> int:
        """
        Dispatches intents via the canonical execution authority according to ReplayPolicy.

        NOTE: This path is transitional. Replay must be capability-aware and must never
        blindly re-execute external side effects. For now, this method reconstructs and
        dispatches only where a dispatcher is explicitly provided and the policy allows it.
        """
        logger.info("ReplayCoordinator: Executing replay plan.")

        from core.execution.capability_registry import DeterminismClass
        from core.execution.execution_intent import ExecutionIntent, VerificationMode, RollbackMode, IntentPriority
        from core.execution.verification_taxonomy import VerificationMode as VTVerificationMode

        dispatched_count = 0

        for intent_id, intent_data in self._reconstructed_intents.items():
            payload = intent_data.get("payload", {})
            adapter = payload.get("adapter", "unknown")
            operation = payload.get("operation", payload.get("action", "unknown"))
            target = payload.get("target", "unknown")

            # Fetch ReplayPolicy from capability registry
            policy = ReplayPolicy.NON_REPLAYABLE
            capability_name = f"{adapter}.{operation}" if adapter and operation else None
            if capability_name:
                try:
                    defn = CAPABILITY_REGISTRY.get(capability_name)
                    if defn is not None:
                        policy = defn.replay_policy
                except Exception:
                    pass

            if policy not in (ReplayPolicy.STRICT, ReplayPolicy.STRUCTURAL):
                continue

            try:
                logger.info(f"Replaying intent {intent_id} (Policy: {policy.value})")

                verification_mode = VerificationMode.NONE if VTVerificationMode is VerificationMode else VTVerificationMode.NONE
                reconstructed_intent = ExecutionIntent(
                    adapter=adapter,
                    operation=operation,
                    idempotent=True,
                    verification_mode=verification_mode,
                    rollback_strategy=RollbackMode.NO_ROLLBACK,
                    capability_scope={"target": target, "action": operation},
                    payload=payload,
                    intent_id=intent_id,
                    priority=IntentPriority.BACKGROUND,
                    determinism=DeterminismClass.STRICT.value,
                )

                if hasattr(kernel_dispatcher, "dispatch") or hasattr(kernel_dispatcher, "dispatch_sync"):
                    dispatch_fn = getattr(kernel_dispatcher, "dispatch", getattr(kernel_dispatcher, "dispatch_sync", None))
                    if dispatch_fn is not None:
                        dispatch_fn(reconstructed_intent)
                dispatched_count += 1
            except Exception as e:
                logger.error(f"Failed to dispatch replay for intent {intent_id}: {e}")

        return dispatched_count
