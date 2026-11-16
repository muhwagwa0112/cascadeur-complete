"""Finite geometry capture declarations; native evidence is issued separately."""
from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .models import SourceBinding
from .motion_context import MotionContext


class GeometryCapturePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    mesh_ids: tuple[str, ...]
    pairs: tuple[tuple[str, str], ...]
    max_calculations: Annotated[StrictInt, Field(gt=0, le=32768)]
    max_array_bytes: Annotated[StrictInt, Field(gt=0, le=1024**3)]
    max_artifact_bytes: Annotated[StrictInt, Field(gt=0, le=2*1024**3)]

    @model_validator(mode="after")
    def exact_pair_closure(self):
        if (not 1 <= len(self.mesh_ids) <= 128 or any(not key for key in self.mesh_ids)
                or len(set(self.mesh_ids)) != len(self.mesh_ids) or not self.pairs):
            raise ValueError("Explicit unique mesh IDs and collision pairs required")
        normalized = [tuple(sorted(pair)) for pair in self.pairs]
        if (len(set(normalized)) != len(normalized) or any(a == b for a, b in self.pairs)
                or {key for pair in self.pairs for key in pair} != set(self.mesh_ids)):
            raise ValueError("Collision pairs must exactly cover the declared meshes")
        return self


class GeometryCaptureArguments(GeometryCapturePolicy):
    capture_id: str
    motion_source_binding: SourceBinding
    motion_capture_digest: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    origin_request_id: str
    context: dict

    @model_validator(mode="after")
    def explicit_identity_context(self):
        for value in (self.capture_id, self.origin_request_id):
            if str(uuid.UUID(value)) != value:
                raise ValueError("Canonical UUID required")
        MotionContext.from_dict(self.context)
        return self
