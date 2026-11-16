"""Pure geometry planning, conversion and equality checks; no SDK or issuer.

The outputs of this module are mathematical candidates. Evidence digests here
are identifiers to be checked by native process-private authority, not proof
that the stated coordinate convention or synchronous calculation was observed.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import math
import re
from typing import Literal

from .serialization_equivalence import canonical_digest


class GeometryContractError(ValueError):
    pass


def _positive_integer(value: int, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise GeometryContractError(label + "_INVALID")


def _sha(value: str) -> bool:
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _number(value: float | int) -> float:
    if type(value) not in (float, int) or not math.isfinite(value):
        raise GeometryContractError("NONFINITE_OR_INVALID_COORDINATE")
    return float(value)


def _vector(value: tuple[float, ...] | list[float], size: int) -> tuple[float, ...]:
    if type(value) not in (tuple, list) or len(value) != size:
        raise GeometryContractError("COORDINATE_SHAPE_INVALID")
    return tuple(_number(component) for component in value)


@dataclass(frozen=True)
class WindowPlan:
    mesh_id: str
    first_row: int
    stop_row: int
    frames: tuple[int, ...]
    reserved_array_bytes: int


@dataclass(frozen=True)
class CapturePlan:
    frames: tuple[int, ...]
    time_s: tuple[float, ...]
    mesh_ids: tuple[str, ...]
    pairs: tuple[tuple[str, str], ...]
    windows: tuple[WindowPlan, ...]
    calculation_count: int


def plan_capture(
    *, frames: tuple[int, ...], time_s: tuple[float, ...],
    vertex_counts: dict[str, int], static_array_bytes: dict[str, int],
    pairs: tuple[tuple[str, str], ...], required_mesh_ids: tuple[str, ...],
    max_calculations: int, max_array_bytes: int, max_frames_per_window: int = 2000,
) -> CapturePlan:
    """Plan mesh-major, ascending-frame calls. Never schedules native execution.

    Array reservation covers f32 raw + f64 canonical + f64 conversion temporary
    (20 bytes/component), plus supplied topology/skin/transform arrays. This is
    the proposed NumPy production representation, not the memory cost of Python
    tuples in the one-frame conversion example below. Projection, archive,
    file and total retained-artifact budgets remain separate native preflight.
    """
    if (type(frames) is not tuple or not frames
            or any(type(frame) is not int or frame < 0 for frame in frames)
            or any(a >= b for a, b in zip(frames, frames[1:]))):
        raise GeometryContractError("FRAME_GRID_MUST_BE_STRICTLY_INCREASING")
    if type(time_s) is not tuple or len(time_s) != len(frames):
        raise GeometryContractError("PHYSICAL_TIME_GRID_INVALID")
    times = tuple(_number(value) for value in time_s)
    if any(a >= b for a, b in zip(times, times[1:])):
        raise GeometryContractError("PHYSICAL_TIME_GRID_INVALID")
    for value, label in ((max_calculations, "CALCULATION_BUDGET"),
                         (max_array_bytes, "ARRAY_BUDGET"),
                         (max_frames_per_window, "WINDOW_FRAME_BUDGET")):
        _positive_integer(value, label)
    if max_frames_per_window > 2000:
        raise GeometryContractError("WINDOW_EXCEEDS_EXISTING_MESH_FRAME_LIMIT")
    if (type(vertex_counts) is not dict or not 1 <= len(vertex_counts) <= 128
            or any(type(key) is not str or not key for key in vertex_counts)
            or type(static_array_bytes) is not dict
            or set(vertex_counts) != set(static_array_bytes)):
        raise GeometryContractError("MESH_INVENTORY_INVALID")
    mesh_ids = tuple(sorted(vertex_counts))
    if (type(pairs) is not tuple or not pairs or type(required_mesh_ids) is not tuple
            or len(set(required_mesh_ids)) != len(required_mesh_ids)
            or any(type(key) is not str or not key for key in required_mesh_ids)):
        raise GeometryContractError("COLLISION_PAIR_SCOPE_INVALID")
    seen, covered = set(), set()
    for pair in pairs:
        if (type(pair) is not tuple or len(pair) != 2 or pair[0] == pair[1]
                or any(type(key) is not str or key not in vertex_counts for key in pair)):
            raise GeometryContractError("COLLISION_PAIR_SCOPE_INVALID")
        normalized = tuple(sorted(pair))
        if normalized in seen:
            raise GeometryContractError("DUPLICATE_COLLISION_PAIR")
        seen.add(normalized)
        covered.update(pair)
    if not set(required_mesh_ids) <= covered:
        raise GeometryContractError("REQUIRED_MESH_PAIR_CLOSURE_MISSING")
    calculation_count = len(frames) * len(mesh_ids)
    if calculation_count > max_calculations:
        raise GeometryContractError("MESH_CALCULATION_BUDGET_EXCEEDED")
    windows: list[WindowPlan] = []
    for mesh_id in mesh_ids:
        _positive_integer(vertex_counts[mesh_id], "VERTEX_COUNT")
        static = static_array_bytes[mesh_id]
        if type(static) is not int or static < 0:
            raise GeometryContractError("STATIC_ARRAY_SIZE_INVALID")
        bytes_per_frame = vertex_counts[mesh_id] * 3 * 20
        count = min(max_frames_per_window, (max_array_bytes - static) // bytes_per_frame)
        if count < 1:
            raise GeometryContractError("ONE_MESH_FRAME_EXCEEDS_ARRAY_BUDGET")
        for start in range(0, len(frames), count):
            stop = min(len(frames), start + count)
            windows.append(WindowPlan(mesh_id, start, stop, frames[start:stop],
                                      static + (stop - start) * bytes_per_frame))
    return CapturePlan(frames, times, mesh_ids, pairs, tuple(windows), calculation_count)


@dataclass(frozen=True)
class ReadBoundary:
    installed_build: str
    runtime_epoch: str
    loaded_fingerprint: str
    scene_instance_id: str
    active_scene_instance_id: str
    document_lineage_id: str
    source_digest: str
    motion_capture_digest: str
    evaluation_receipt_digest: str
    evaluation_projection_digest: str
    full_projection_digest: str
    topology_digest: str
    skin_digest: str
    transform_projection_digest: str
    context_digest: str
    selection_digest: str
    current_frame: int


def assert_read_compute_read(before: ReadBoundary, after: ReadBoundary, *,
                             expected_source_digest: str,
                             expected_motion_capture_digest: str,
                             expected_context_digest: str) -> None:
    """Reject drift; returning None is an equality check, not an attestation."""
    if type(before) is not ReadBoundary or type(after) is not ReadBoundary:
        raise GeometryContractError("READ_BOUNDARY_TYPE_INVALID")
    for boundary in (before, after):
        for field in fields(boundary):
            value = getattr(boundary, field.name)
            if field.name.endswith("_digest") or field.name == "loaded_fingerprint":
                if not _sha(value):
                    raise GeometryContractError("BOUNDARY_DIGEST_INVALID:" + field.name)
            elif field.name != "current_frame" and (type(value) is not str or not value):
                raise GeometryContractError("BOUNDARY_IDENTITY_INVALID:" + field.name)
        if type(boundary.current_frame) is not int or boundary.current_frame < 0:
            raise GeometryContractError("CURRENT_FRAME_INVALID")
        if boundary.active_scene_instance_id != boundary.scene_instance_id:
            raise GeometryContractError("CAPTURE_SCENE_NOT_ACTIVE")
        if boundary.evaluation_projection_digest != boundary.full_projection_digest:
            raise GeometryContractError("EVALUATION_NOT_CURRENT")
    if (before.source_digest != expected_source_digest
            or before.motion_capture_digest != expected_motion_capture_digest
            or before.context_digest != expected_context_digest):
        raise GeometryContractError("CAPTURE_REQUEST_BINDING_DIFFERS")
    if before != after:
        changed = [field.name for field in fields(before)
                   if getattr(before, field.name) != getattr(after, field.name)]
        raise GeometryContractError("SOURCE_CHANGED_DURING_CALCULATION:" + ",".join(changed))


@dataclass(frozen=True)
class CoordinateContract:
    raw_space: Literal["native_global", "native_mesh_local"]
    metres_per_native_unit: float
    solver_basis: tuple[tuple[float, float, float], ...]
    coordinate_evidence_digest: str
    conversion_policy_digest: str


def _validated_basis(contract: CoordinateContract) -> tuple[tuple[float, ...], ...]:
    if (type(contract) is not CoordinateContract
            or contract.raw_space not in ("native_global", "native_mesh_local")
            or not _sha(contract.coordinate_evidence_digest)
            or not _sha(contract.conversion_policy_digest)):
        raise GeometryContractError("COORDINATE_CONTRACT_INVALID")
    scale = _number(contract.metres_per_native_unit)
    if scale <= 0:
        raise GeometryContractError("POSITIVE_LENGTH_SCALE_REQUIRED")
    if type(contract.solver_basis) is not tuple or len(contract.solver_basis) != 3:
        raise GeometryContractError("BASIS_SHAPE_INVALID")
    rows = tuple(_vector(row, 3) for row in contract.solver_basis)
    for i in range(3):
        for j in range(3):
            dot = sum(rows[i][k] * rows[j][k] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > 1e-9:
                raise GeometryContractError("BASIS_NOT_ORTHONORMAL")
    a, b, c = rows
    det = (a[0] * (b[1] * c[2] - b[2] * c[1])
           - a[1] * (b[0] * c[2] - b[2] * c[0])
           + a[2] * (b[0] * c[1] - b[1] * c[0]))
    if abs(det - 1.0) > 1e-9:
        raise GeometryContractError("BASIS_NOT_PROPER_ROTATION")
    return rows


def canonicalize_frame(
    raw_positions: tuple[tuple[float, float, float], ...], *,
    contract: CoordinateContract,
    mesh_to_world: tuple[tuple[float, float, float, float], ...] | None,
    maximum_vertices: int,
) -> tuple[tuple[float, float, float], ...]:
    """Pure one-frame conversion; does not certify native actual geometry.

    mesh_to_world is an already observed column-vector affine matrix in native
    units. Its SDK read path and matrix convention must be qualified separately.
    """
    _positive_integer(maximum_vertices, "VERTEX_BUDGET")
    if type(raw_positions) is not tuple or not 1 <= len(raw_positions) <= maximum_vertices:
        raise GeometryContractError("VERTEX_COVERAGE_INVALID")
    basis = _validated_basis(contract)
    matrix = None
    if contract.raw_space == "native_mesh_local":
        if type(mesh_to_world) is not tuple or len(mesh_to_world) != 4:
            raise GeometryContractError("OBSERVED_MESH_TO_WORLD_REQUIRED")
        matrix = tuple(_vector(row, 4) for row in mesh_to_world)
        if matrix[3] != (0.0, 0.0, 0.0, 1.0):
            raise GeometryContractError("MESH_TO_WORLD_NOT_AFFINE")
    elif mesh_to_world is not None:
        raise GeometryContractError("WORLD_TRANSFORM_WOULD_BE_APPLIED_TWICE")
    result = []
    for position in raw_positions:
        local = _vector(position, 3)
        world = tuple(sum(matrix[row][axis] * local[axis] for axis in range(3))
                      + matrix[row][3] for row in range(3)) if matrix is not None else local
        canonical = tuple(contract.metres_per_native_unit
                          * sum(basis[row][axis] * world[axis] for axis in range(3))
                          for row in range(3))
        if not all(math.isfinite(value) for value in canonical):
            raise GeometryContractError("CANONICAL_COORDINATE_OVERFLOW")
        result.append(canonical)
    return tuple(result)


def array_contract_digest(*, frames: list[int], shape: list[int],
                          dtype: str, content_sha256: str) -> str:
    """Bind an array's shape/order/frame interpretation to separately hashed bytes."""
    if (not _sha(content_sha256) or dtype not in ("<f4", "<f8", "<i8")
            or type(frames) is not list or not frames
            or any(type(frame) is not int or frame < 0 for frame in frames)
            or any(a >= b for a, b in zip(frames, frames[1:]))
            or type(shape) is not list or not shape
            or any(type(size) is not int or size <= 0 for size in shape)):
        raise GeometryContractError("ARRAY_CONTRACT_INVALID")
    return canonical_digest({"frames": frames, "shape": shape, "dtype": dtype,
                             "order": "C", "content_sha256": content_sha256})

