# RUNTIME SEMANTIC LAWS

This document formally declares the immutable laws of the Novamind deterministic execution topology. These laws are **not advisory**. They must be physically enforced by Continuous Integration (CI), assertions, and static audits. If a PR violates any of these laws, it cannot be merged.

## 1. The WAL Durability Law
**No execution may proceed before durable persistence.**
- An intent may only enter the `DISPATCHED` state *after* the recovery WAL (Write-Ahead Log) has been successfully serialized and flushed (`fsync`) to disk.
- In-memory execution state is volatile and legally untrusted until journalized.

## 2. The Replay Safety Law
**`READY` state is impossible before topological reconciliation.**
- The system must not accept new work until replay completion, failure reconciliation, and orphan recovery have reached a terminal, consistent state.

## 3. The Concurrency Law
**Non-commutative intents MUST strictly serialize.**
- Intents that mutate shared state or physical domains (file systems, global registries) must acquire deterministic global or scoped execution locks.
- The order of lock acquisition *must* be deterministic and mathematically reproducible during replay.

## 4. The Recovery Law
**No orphans shall leak.**
- An intent caught in the `ORPHANED` state must forcefully terminate in a legal branch: reconcile, retry, abort, or escalate. 
- Silently abandoning an executing intent violates state machine topology.

## 5. The Capability Law
**Zero-trust adapter execution.**
- No OS-level Adapter execution may run unless a governing capability rule explicitly authorizes it.
- Execution requires an assigned `ReplayTrustLevel` and defined `VerificationSemantics`. 

## 6. The Verification Law
**Verification truth must propagate to the kernel.**
- If post-execution verification fails, it cannot be silently swallowed. It must trigger a state transition (e.g., `VERIFYING` -> `FAILED`) and correct the WAL trace.

## 7. The Semantic Ownership Law
**Exactly one semantic authority per mutable domain.**
- Every mutable architectural domain must be registered to one explicit owner in the `SemanticAuthorityRegistry`.
- Examples: 
  - `ReplayCoordinator` solely owns replay lifecycle.
  - `RuntimeKernel` solely owns the runtime FSM.
  - `ResourceLockManager` solely owns lock orchestration.
- Shadow authorities and multi-master mutations are strictly banned.

## 8. The Capability Escalation Law
**Low-trust capabilities shall not hijack high-trust domains.**
- Observational domains (like Browser interactions or UI scripts) operate under non-deterministic constraints.
- They are legally forbidden from:
  - Triggering kernel panic authority.
  - Mutating replay trust layers.
  - Altering core lifecycle states.
  - Overriding reconciliation behavior.

## 9. The Observability Isolation Law
**Observability is passive truth exposure.**
- Telemetry, intent tracing, and metric collection must *never* mutate runtime execution semantics.
- Observability components are legally forbidden from altering lifecycle states, altering replay trust, triggering reconciliation, changing scheduling topologies, or escalating kernel panics.
