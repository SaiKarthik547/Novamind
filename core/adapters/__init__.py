"""
core.adapters package.

Importing any submodule of this package first executes this file, so the
canonical adapter lanes register themselves exactly once, at package load:

- IntentContractRegistry: structural contracts each adapter is willing to accept.
- ADAPTER_REGISTRY: the adapter class behind each lane name.

Registration is in-memory only (no OS mutation), which keeps it safe to run
during RuntimeBootstrap construction (Gate 1.5 forbids worker spawn / adapter
assign / adapter execute during bootstrap — not module imports).

R1 scope: only the filesystem lane is loaded here. Remaining lanes
(process, browser, shell/pty, legacy UI) register when their convergence
phase lands — this file must not grow into an eager import of every adapter.
"""

from . import filesystem_adapter  # noqa: F401  (canonical filesystem lane registration)
