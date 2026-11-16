"""Preparation requirements only: no native unbaking executor is implemented."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MissingUnbakingContract:
    step: str
    missing_evidence: tuple[str, ...]
    registration_allowed: bool = False


def current_unbaking_requirements() -> tuple[MissingUnbakingContract, ...]:
    """Describe the inspected HEAD's missing installed bindings/completion.

    This is a static implementation-preparation record, not a live SDK probe.
    None of these records may be accepted by guarded_runtime.register_adapter.
    """
    requirements = (
        "Exact installed action ID to callable binding and source/version digest",
        "Explicit object/layer/frame scope with no implicit scope expansion",
        "Synchronous no-yield leaf completion or a separately supported async protocol",
        "Request/scene/epoch-correlated success, failure and cancellation",
        "Complete pre/post projection and existing topology/count checks",
        "Process-private observation from an authorized bounded native qualification",
    )
    steps = ("prepare_keys_by_fulcrums", "adjust_keys_and_interpolation",
             "adjust_autoposing_lock_state")
    return tuple(MissingUnbakingContract(step, requirements) for step in steps)


def block_unqualified_step(step: str) -> None:
    """Fail closed; there is intentionally no success or sparse-fallback branch."""
    matches = [item for item in current_unbaking_requirements() if item.step == step]
    if not matches:
        raise ValueError("INVALID_UNBAKING_STEP")
    raise ValueError("UNBAKING_INSTALLED_BINDING_AND_COMPLETION_UNOBSERVED:" + step)

