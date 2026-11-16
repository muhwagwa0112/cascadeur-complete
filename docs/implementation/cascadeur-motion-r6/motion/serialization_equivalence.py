"""Pure mathematical comparison candidates; never native proof or authorization.

A candidate returned here must not enable a capability, issue a source, seal a
receipt, or authorize restore. Native integration must resolve DerivedPolicy
from process-private, installed-build evidence before accepting a non-exact
candidate. No such evidence issuer is implemented in this reference module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
import struct
from typing import Any, Literal


class ComparisonContractError(ValueError):
    pass


def _json_only(value: Any) -> None:
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ComparisonContractError("NONFINITE_PROJECTION")
        return
    if type(value) is list:
        for item in value:
            _json_only(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_only(item)
        return
    raise ComparisonContractError("NON_JSON_PROJECTION_TYPE")


def canonical_digest(value: Any) -> str:
    """Same JSON encoding as guarded_runtime.digest, for strict JSON inputs."""
    _json_only(value)
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _copy(value: Any) -> Any:
    _json_only(value)
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _digest_string(value: str) -> bool:
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _index(rows: Any, label: str) -> dict[str, dict[str, Any]]:
    if type(rows) is not list:
        raise ComparisonContractError("MISSING_" + label)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if type(row) is not dict or type(row.get("id")) is not str or not row["id"]:
            raise ComparisonContractError("INVALID_" + label + "_IDENTITY")
        if row["id"] in result:
            raise ComparisonContractError("DUPLICATE_" + label + "_IDENTITY")
        result[row["id"]] = row
    return result


def role_layout_digest(projection: dict[str, Any]) -> str:
    """Structural binding only; NEVER use this digest as source identity."""
    value = _copy(projection)
    _index(value.get("data"), "DATA")
    for row in value["data"]:
        if type(row.get("values")) is not list:
            raise ComparisonContractError("MISSING_DATA_VALUES")
        row["values"] = {"removed_only_for_role_layout": True}
    return canonical_digest(value)


@dataclass(frozen=True)
class DerivedRule:
    data_id: str
    data_owner_id: str
    behaviour_owner_id: str
    behaviour_id: str
    property_name: str
    property_kind: Literal["DataType", "DataRangeType"]
    property_index: int | None
    sample_shape: tuple[int, ...]
    metric: Literal["float32_components", "rotation_wxyz"]
    native_type_evidence_digest: str
    dependency_evidence_digest: str
    units: str
    max_ulps: int
    max_absolute_native: float
    max_angle_radians: float
    max_norm_error: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "data_id": self.data_id, "data_owner_id": self.data_owner_id,
            "behaviour_owner_id": self.behaviour_owner_id,
            "behaviour_id": self.behaviour_id, "property_name": self.property_name,
            "property_kind": self.property_kind, "property_index": self.property_index,
            "sample_shape": list(self.sample_shape), "metric": self.metric,
            "native_type_evidence_digest": self.native_type_evidence_digest,
            "dependency_evidence_digest": self.dependency_evidence_digest,
            "units": self.units, "max_ulps": self.max_ulps,
            "max_absolute_native": self.max_absolute_native,
            "max_angle_radians": self.max_angle_radians,
            "max_norm_error": self.max_norm_error,
        }


@dataclass(frozen=True)
class DerivedPolicy:
    schema_version: int
    installed_build: str
    loaded_fingerprint: str
    role_evidence_digest: str
    expected_role_layout_digest: str
    rules: tuple[DerivedRule, ...]
    max_components: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "installed_build": self.installed_build,
            "loaded_fingerprint": self.loaded_fingerprint,
            "role_evidence_digest": self.role_evidence_digest,
            "expected_role_layout_digest": self.expected_role_layout_digest,
            "rules": [rule.as_dict() for rule in self.rules],
            "max_components": self.max_components,
        }


@dataclass(frozen=True)
class FieldMetric:
    data_id: str
    metric: str
    compared_components: int
    maximum_ulps: int
    maximum_absolute_native: float
    maximum_angle_radians: float
    accepted: bool


@dataclass(frozen=True)
class ComparisonCandidate:
    """Untrusted numeric result. Contains no completion or authorization field."""
    accepted: bool
    kind: Literal["exact", "derived_numeric", "different"]
    before_digest: str
    after_digest: str
    exact_fields_digest: str | None
    policy_digest: str | None
    fields: tuple[FieldMetric, ...]
    failure_codes: tuple[str, ...]


def _validate_rule(rule: DerivedRule) -> None:
    names = (rule.data_id, rule.data_owner_id, rule.behaviour_owner_id,
             rule.behaviour_id, rule.property_name, rule.units)
    if any(type(name) is not str or not name for name in names):
        raise ComparisonContractError("RULE_IDENTITY_OR_UNITS_MISSING")
    if any(not _digest_string(value) for value in
           (rule.native_type_evidence_digest, rule.dependency_evidence_digest)):
        raise ComparisonContractError("RULE_EVIDENCE_DIGEST_INVALID")
    if type(rule.sample_shape) is not tuple or len(rule.sample_shape) > 3 or any(
            type(size) is not int or not 1 <= size <= 16 for size in rule.sample_shape):
        raise ComparisonContractError("RULE_SHAPE_UNSUPPORTED")
    if rule.property_kind == "DataType":
        if rule.property_index is not None:
            raise ComparisonContractError("SCALAR_PROPERTY_HAS_RANGE_INDEX")
    elif rule.property_kind == "DataRangeType":
        if type(rule.property_index) is not int or rule.property_index < 0:
            raise ComparisonContractError("RANGE_PROPERTY_INDEX_REQUIRED")
    else:
        raise ComparisonContractError("RULE_PROPERTY_KIND_UNSUPPORTED")
    if type(rule.max_ulps) is not int or rule.max_ulps < 0:
        raise ComparisonContractError("ULP_BUDGET_INVALID")
    limits = (rule.max_absolute_native, rule.max_angle_radians, rule.max_norm_error)
    if any(type(value) is not float or not math.isfinite(value) or value < 0
           for value in limits):
        raise ComparisonContractError("NUMERIC_BUDGET_INVALID")
    if rule.metric == "float32_components":
        if rule.max_angle_radians != 0.0 or rule.max_norm_error != 0.0:
            raise ComparisonContractError("UNUSED_ROTATION_BUDGET")
    elif rule.metric == "rotation_wxyz":
        if (rule.sample_shape != (4,) or rule.max_ulps != 0
                or rule.max_absolute_native != 0.0
                or rule.max_angle_radians > math.pi
                or rule.max_norm_error >= 1.0):
            raise ComparisonContractError("ROTATION_CONTRACT_INVALID")
    else:
        raise ComparisonContractError("NUMERIC_METRIC_UNSUPPORTED")


def _validate_binding(projection: dict[str, Any], row: dict[str, Any],
                      rule: DerivedRule) -> None:
    if row.get("owner") != rule.data_owner_id:
        raise ComparisonContractError("DATA_OWNER_CHANGED")
    objects = _index(projection.get("objects"), "OBJECT")
    owner = objects.get(rule.behaviour_owner_id)
    if owner is None:
        raise ComparisonContractError("BEHAVIOUR_OWNER_MISSING")
    behaviour = _index(owner.get("behaviours"), "BEHAVIOUR").get(rule.behaviour_id)
    if behaviour is None:
        raise ComparisonContractError("BEHAVIOUR_MISSING")
    properties = behaviour.get("properties")
    if type(properties) is not list:
        raise ComparisonContractError("BEHAVIOUR_PROPERTIES_MISSING")
    matching = [prop for prop in properties if type(prop) is dict
                and prop.get("name") == rule.property_name]
    if len(matching) != 1 or matching[0].get("kind") != rule.property_kind:
        raise ComparisonContractError("DERIVED_PROPERTY_BINDING_CHANGED")
    value = matching[0].get("value")
    if rule.property_kind == "DataRangeType":
        if type(value) is not list or rule.property_index >= len(value):
            raise ComparisonContractError("DERIVED_PROPERTY_RANGE_CHANGED")
        value = value[rule.property_index]
    if value != rule.data_id:
        raise ComparisonContractError("DERIVED_DATA_REFERENCE_CHANGED")


def _flatten(value: Any, shape: tuple[int, ...]) -> list[float]:
    if not shape:
        if type(value) is not float or not math.isfinite(value):
            raise ComparisonContractError("DERIVED_FLOAT_TYPE_OR_VALUE_INVALID")
        return [value]
    if type(value) is not list or len(value) != shape[0]:
        raise ComparisonContractError("DERIVED_SHAPE_CHANGED")
    result: list[float] = []
    for item in value:
        result.extend(_flatten(item, shape[1:]))
    return result


def _f32_order(value: float) -> int:
    try:
        packed = struct.pack(">f", value)
    except OverflowError as error:
        raise ComparisonContractError("VALUE_NOT_FLOAT32") from error
    restored = struct.unpack(">f", packed)[0]
    if restored.hex() != value.hex():
        raise ComparisonContractError("VALUE_NOT_EXACT_FLOAT32")
    bits = struct.unpack(">I", packed)[0]
    magnitude = bits & 0x7fffffff
    return 0x80000000 - magnitude if bits & 0x80000000 else 0x80000000 + magnitude


def _rotation_angle(left: list[float], right: list[float],
                    norm_limit: float) -> float:
    a, b = math.hypot(*left), math.hypot(*right)
    if (a == 0.0 or b == 0.0 or not math.isfinite(a) or not math.isfinite(b)
            or abs(a - 1.0) > norm_limit or abs(b - 1.0) > norm_limit):
        raise ComparisonContractError("DERIVED_ROTATION_NOT_UNIT")
    qa, qb = [value / a for value in left], [value / b for value in right]
    chord = min(math.hypot(*(x - y for x, y in zip(qa, qb))),
                math.hypot(*(x + y for x, y in zip(qa, qb))))
    return 4.0 * math.asin(min(1.0, chord / 2.0))


def compare_projections(
    before: dict[str, Any], after: dict[str, Any], *,
    expected_before_digest: str,
    installed_build: str, loaded_fingerprint: str,
    policy: DerivedPolicy | None = None,
) -> ComparisonCandidate:
    """Compare JSON projections. A caller cannot turn this result into evidence.

    Native caller supplies expected_before_digest from its exact private anchor,
    and resolves policy from installed, process-private classification evidence.
    The function never derives or widens tolerances from the observed difference.
    """
    before_digest, after_digest = canonical_digest(before), canonical_digest(after)
    if not _digest_string(expected_before_digest) or before_digest != expected_before_digest:
        raise ComparisonContractError("EXACT_ANCHOR_DIGEST_MISMATCH")
    if before_digest == after_digest:
        return ComparisonCandidate(True, "exact", before_digest, after_digest,
                                   before_digest, None, (), ())
    if policy is None:
        return ComparisonCandidate(False, "different", before_digest, after_digest,
                                   None, None, (), ("SERIALIZATION_PROFILE_UNAVAILABLE",))
    if (type(policy.schema_version) is not int or policy.schema_version != 1
            or policy.installed_build != installed_build
            or policy.loaded_fingerprint != loaded_fingerprint
            or not _digest_string(policy.loaded_fingerprint)
            or not _digest_string(policy.role_evidence_digest)
            or not _digest_string(policy.expected_role_layout_digest)
            or type(policy.rules) is not tuple or not 1 <= len(policy.rules) <= 64
            or type(policy.max_components) is not int
            or not 1 <= policy.max_components <= 2_000_000):
        raise ComparisonContractError("SERIALIZATION_PROFILE_SCOPE_INVALID")
    if (role_layout_digest(before) != policy.expected_role_layout_digest
            or role_layout_digest(after) != policy.expected_role_layout_digest):
        raise ComparisonContractError("SERIALIZATION_ROLE_LAYOUT_CHANGED")
    if len({rule.data_id for rule in policy.rules}) != len(policy.rules):
        raise ComparisonContractError("DUPLICATE_DERIVED_RULE")
    left_rows, right_rows = _index(before.get("data"), "DATA"), _index(after.get("data"), "DATA")
    left_masked, right_masked = _copy(before), _copy(after)
    left_masked_rows = _index(left_masked["data"], "DATA")
    right_masked_rows = _index(right_masked["data"], "DATA")
    compared, metrics, failures = 0, [], []
    for rule in policy.rules:
        _validate_rule(rule)
        left, right = left_rows.get(rule.data_id), right_rows.get(rule.data_id)
        if left is None or right is None:
            raise ComparisonContractError("DERIVED_DATA_MISSING")
        _validate_binding(before, left, rule)
        _validate_binding(after, right, rule)
        mode = left.get("mode")
        if mode not in ("Animation", "Static"):
            raise ComparisonContractError("DERIVED_DATA_MODE_UNSUPPORTED")
        count = before.get("frames") if mode == "Animation" else 1
        if type(count) is not int or not 1 <= count <= 20001:
            raise ComparisonContractError("DERIVED_SAMPLE_COUNT_INVALID")
        components = count * math.prod(rule.sample_shape)
        compared += components
        if compared > policy.max_components:
            raise ComparisonContractError("SERIALIZATION_COMPARISON_BUDGET_EXCEEDED")
        a = _flatten(left.get("values"), (count, *rule.sample_shape))
        b = _flatten(right.get("values"), (count, *rule.sample_shape))
        maximum_ulps, maximum_abs, maximum_angle = 0, 0.0, 0.0
        accepted = True
        if rule.metric == "float32_components":
            for x, y in zip(a, b):
                ulps, absolute = abs(_f32_order(x) - _f32_order(y)), abs(x - y)
                maximum_ulps, maximum_abs = max(maximum_ulps, ulps), max(maximum_abs, absolute)
                accepted = accepted and ulps <= rule.max_ulps and absolute <= rule.max_absolute_native
        else:
            for start in range(0, len(a), 4):
                angle = _rotation_angle(a[start:start + 4], b[start:start + 4], rule.max_norm_error)
                maximum_angle = max(maximum_angle, angle)
                accepted = accepted and angle <= rule.max_angle_radians
        metrics.append(FieldMetric(rule.data_id, rule.metric, components,
                                   maximum_ulps, maximum_abs, maximum_angle, accepted))
        if not accepted:
            failures.append("DERIVED_NUMERIC_BUDGET_EXCEEDED:" + rule.data_id)
        marker = {"excluded_only_for_numeric_comparison": rule.data_id}
        left_masked_rows[rule.data_id]["values"] = marker
        right_masked_rows[rule.data_id]["values"] = marker
    exact_digest = canonical_digest(left_masked)
    if exact_digest != canonical_digest(right_masked):
        failures.append("AUTHORED_OR_UNCLASSIFIED_FIELDS_CHANGED")
    accepted = not failures
    return ComparisonCandidate(
        accepted, "derived_numeric" if accepted else "different",
        before_digest, after_digest, exact_digest if accepted else None,
        canonical_digest(policy.as_dict()), tuple(metrics), tuple(failures),
    )

