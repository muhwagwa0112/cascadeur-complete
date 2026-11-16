"""Executable decision-table reference, not an SDK adapter or an authority issuer.

This file belongs to the R5 design packet, not to the Cascadeur package. It has
no I/O, dispatch, retry, token, journal or recovery implementation. Its inputs
represent facts *after* the private native verifier has checked the original
attempt, callback lifetime and complete effect scope. Constructing these
dataclasses, or obtaining a CandidateDecision, proves none of those facts.

Production must use the private lookup/validation boundary described in
COMPLETION_IMPLEMENTATION.md. A public JSON object must never be deserialized
into these classes and treated as native evidence. Python 3.11 syntax.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Completion(str, Enum):
    COMPLETED = "completed"
    NO_EFFECT = "no_effect"
    UNKNOWN = "unknown"


class Postcondition(str, Enum):
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AttemptIdentity:
    request_digest: str
    operation_digest: str
    source_digest: str
    runtime_epoch: str
    runtime_fingerprint: str
    scene_instance_id: str
    callback_generation: int


@dataclass(frozen=True)
class ObservationSummary:
    """Verifier output shape only; this class is not a verifier."""

    attempt: AttemptIdentity
    completion: Completion
    postcondition: Postcondition
    native_evidence_digest: str | None
    before_projection_digest: str
    actual_after_digest: str | None
    effect_scope_digest: str | None


@dataclass(frozen=True)
class CandidateDecision:
    outcome: str
    ok: bool
    reason: str
    recovery_candidate: bool
    # This reference always returns a non-authoritative candidate. Actual
    # recovery eligibility has a separate private proof and durable receipt.
    authority: bool = field(default=False, init=False)


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_attempt(value: AttemptIdentity) -> bool:
    return (
        isinstance(value, AttemptIdentity)
        and all(_sha256(item) for item in (
            value.request_digest, value.operation_digest, value.source_digest,
            value.runtime_fingerprint,
        ))
        and isinstance(value.runtime_epoch, str) and bool(value.runtime_epoch)
        and isinstance(value.scene_instance_id, str) and bool(value.scene_instance_id)
        and type(value.callback_generation) is int
        and value.callback_generation >= 0
    )


def classify_candidate(
    attempt: AttemptIdentity,
    observation: ObservationSummary | None,
    *,
    dispatched: bool,
    executor_ok: bool,
    current_callback_generation: int,
) -> CandidateDecision:
    """Apply the proposed decision table to an already-verified summary.

    Write phase is deliberately not an input: ``not_started``/``completed``
    alone cannot prove native completion. Current generation is rechecked
    before terminal sealing in production, not just when the adapter returns.
    The result never authorizes recovery, replay, publication, or retirement.
    """
    if (not _valid_attempt(attempt) or type(dispatched) is not bool
            or type(executor_ok) is not bool
            or type(current_callback_generation) is not int
            or current_callback_generation < 0):
        raise ValueError("Invalid classifier input")
    if not dispatched:
        if executor_ok or observation is not None:
            raise ValueError("A pre-dispatch rejection cannot carry a native result")
        return CandidateDecision("rejected_pre_dispatch", False,
                                 "REQUEST_REJECTED_BEFORE_DISPATCH", False)

    unknown = CandidateDecision("outcome_unknown", False,
                                "NATIVE_COMPLETION_UNPROVEN", False)
    if not isinstance(observation, ObservationSummary):
        return unknown
    if (observation.attempt != attempt
            or current_callback_generation != attempt.callback_generation):
        return CandidateDecision("outcome_unknown", False,
                                 "ATTEMPT_OR_CALLBACK_BOUNDARY_CHANGED", False)
    if (not isinstance(observation.completion, Completion)
            or not isinstance(observation.postcondition, Postcondition)):
        return unknown
    if observation.completion is Completion.UNKNOWN:
        return unknown
    if not all(_sha256(value) for value in (
        observation.native_evidence_digest, observation.before_projection_digest,
        observation.actual_after_digest, observation.effect_scope_digest,
    )):
        return unknown

    if observation.completion is Completion.NO_EFFECT:
        if observation.before_projection_digest != observation.actual_after_digest:
            return CandidateDecision("outcome_unknown", False,
                                     "NO_EFFECT_OBSERVATION_CONTRADICTS_STATE", False)
        # Preserve the existing wire outcome for a dispatched no-effect failure.
        return CandidateDecision("failed_after_dispatch", False,
                                 "QUALIFIED_NO_EFFECT_FAILURE", False)

    if observation.postcondition is Postcondition.UNAVAILABLE:
        return unknown
    if not executor_ok or observation.postcondition is Postcondition.MISMATCHED:
        return CandidateDecision("failed_after_dispatch", False,
                                 "COMPLETED_EXECUTION_FAILED_CONTRACT", True)
    return CandidateDecision("succeeded", True,
                             "EXECUTION_CONTRACT_MATCHED_QUALITY_SEPARATE", False)


def recovery_is_candidate(
    decision: CandidateDecision,
    *,
    write_phase: str,
    failure_kind: str | None,
    original_operation: str,
) -> bool:
    """Cheap negative filter only; True is never ``recovery_eligible=True``.

    The actual adapter must still authenticate a request-specific failure
    attestation, a same-scope post_source, immutable checkpoint bytes, restore
    capability and the original durable terminal before any restore dispatch.
    """
    return (
        isinstance(decision, CandidateDecision)
        and decision.outcome == "failed_after_dispatch"
        and decision.recovery_candidate
        and write_phase in {"started", "completed"}
        and failure_kind != "guard_rejected_before_first_write"
        and original_operation not in {"safety.rollback", "safety.rollback_internal"}
    )
