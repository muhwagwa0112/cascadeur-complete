"""Explicit finite topology authority for the three native unbaking actions.

These declarations bound an effect; they do not attest native completion or
qualify an ActionManager adapter.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator


KeyCount = Annotated[StrictInt, Field(ge=0)]


class UnbakingKeyLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    maximum_added_keys: KeyCount
    maximum_removed_keys: KeyCount
    maximum_written_keys: KeyCount

    @model_validator(mode="after")
    def topology_fits_write_bound(self):
        if self.maximum_added_keys + self.maximum_removed_keys > self.maximum_written_keys:
            raise ValueError("Added and removed unbaking keys exceed the written-key bound")
        return self


class UnbakingTopologyPolicy(UnbakingKeyLimits):
    allow_key_insertion: StrictBool
    allow_interpolation_change: StrictBool

    @model_validator(mode="after")
    def insertion_is_explicit(self):
        if self.maximum_added_keys and not self.allow_key_insertion:
            raise ValueError("Unbaking key additions require explicit insertion permission")
        return self


def unbaking_topology_policy(limits: UnbakingKeyLimits, *, allow_key_insertion: bool,
                            allow_interpolation_change: bool) -> UnbakingTopologyPolicy:
    """Lower typed counts together with the original intent's exact flags."""
    return UnbakingTopologyPolicy.model_validate({**limits.model_dump(mode="json"),
        "allow_key_insertion": allow_key_insertion, "allow_interpolation_change": allow_interpolation_change})


def require_unbaking_step(service, step):
    """Ask the native process before minting a token or reserving a recipe."""
    from .models import Operation
    result = service.client.execute("capture_source", [Operation(
        name="system.native_adapter_status", arguments={})])
    statuses = (result.result or {}).get("unbaking_steps", {}) if result.ok else {}
    status = statuses.get(step) if isinstance(statuses, dict) else None
    # No native adapter currently implements the complete step contract. A
    # generic operation capability cannot substitute for step-specific proof.
    if not isinstance(status, dict) or status.get("qualified") is not True:
        missing = status.get("missing", []) if isinstance(status, dict) else ["private_step_qualification"]
        raise ValueError("UNBAKING_STEP_UNQUALIFIED: " + str(step) + ": " + ",".join(missing))
    required = ("installed_callable_digest", "lowering_digest", "completion_contract_digest",
                "qualification_digest", "runtime_epoch", "runtime_fingerprint")
    if status.get("step") != step or any(not isinstance(status.get(key), str) or not status[key] for key in required):
        raise ValueError("UNBAKING_STEP_UNQUALIFIED: incomplete native step contract")
    return status
