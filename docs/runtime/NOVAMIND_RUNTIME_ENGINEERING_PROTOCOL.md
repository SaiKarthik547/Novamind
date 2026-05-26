# NOVAMIND RUNTIME ENGINEERING PROTOCOL

You are operating inside a **deterministic RuntimeKernel architecture**. The system depends on strict semantic execution rules, verifiable immutability, and deterministic replayability. 

Before proposing or executing ANY modification to Novamind's architecture, you MUST obey the following protocol.

## Pre-Modification Checklist
Before any structural change is written, answer these questions:
1. **Trace real execution paths:** Where does this logic actually run in the execution pipeline?
2. **Identify semantic authority owner:** Who owns this mutation (e.g. `RuntimeKernel`, `ResourceLockManager`, `RecoverySupervisor`)?
3. **Identify replay implications:** Does this break the deterministic WAL replay lineage?
4. **Identify concurrency implications:** Is this safe for multi-agent or parallel dispatch?
5. **Identify recovery implications:** What happens if the process crashes exactly during this instruction?
6. **Identify capability-governance implications:** Does this escalate low-trust observation into high-trust mutation?
7. **Identify lifecycle implications:** Does this violate the strict state machine flow?
8. **Identify observability implications:** Does this hide telemetry, or worse, does the telemetry mutate state?
9. **Identify determinism classification impact:** Are we upgrading or degrading the determinism trust level of an operation?
10. **Identify semantic duplication:** Are we accidentally duplicating authority that belongs elsewhere?

## Hard Constraints
You must **NEVER**:
- Assume architecture based on naming conventions (always read the trace).
- Introduce local or shadow authority ownership outside the Kernel.
- Bypass the `RuntimeKernel` orchestration layer.
- Bypass the WAL (Write-Ahead Log) persistence lineage.
- Bypass Capability validation during execution.
- Bypass Replay Trust Assignment.
- Claim stronger replay guarantees than the implementation actually provides.
- Perform local isolated fixes without global runtime tracing.

## Communication & Proposal Rules
Every architectural proposal or PR must explicitly distinguish:
- **Implemented Reality:** What the code *actually* does today.
- **Architectural Intention:** What the design intended.
- **Transitional Infrastructure:** Bridges or shims slated for deprecation.
- **Unresolved Semantic Gaps:** Risks, debt, or unverified claims.

## Primary Objective
Your singular, paramount objective across all system engineering tasks is to **preserve deterministic semantic runtime integrity.**

> [!WARNING]
> Do NOT use conversational prompts to enforce runtime boundaries. Prompts are advisory. All runtime laws must be enforced via hard code invariants, CI audits, and certification matrices.
