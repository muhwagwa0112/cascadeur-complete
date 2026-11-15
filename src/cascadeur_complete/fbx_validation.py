"""Bounded binary FBX parsing and explicit export-contract validation.

The parser does not evaluate FBX interpolation or skinning. A structure pass is
one input to target roundtrip validation, never a motion-quality pass.
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
import zlib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO

import numpy as np

from .export_models import ExportExpectation, ExportProfile, ValidationReport

MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
# Blender/Assimp's fixed-time exporter convention, not a universal signature.
FOOTER_START = bytes.fromhex("fabcab09d0c8d466b176fb831cf7267e")
FOOTER_END = bytes.fromhex("f85a8c6adef5d97eece90ce3758f290b")
LEGACY_KTIME = 46186158000
NEW_KTIME = 141120000
FPS = {1: (120, 1), 2: (100, 1), 3: (60, 1), 4: (50, 1), 5: (48, 1), 6: (30, 1),
       7: (30, 1), 8: (30000, 1001), 9: (30000, 1001), 10: (25, 1), 11: (24, 1),
       13: (24000, 1001), 15: (96, 1), 16: (72, 1), 17: (60000, 1001), 18: (120000, 1001)}


class FbxError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class ParseLimits:
    supported_versions: tuple[int, ...] = (7400, 7500, 7700)
    max_file_bytes: int = 2 * 1024**3
    max_depth: int = 64
    max_nodes: int = 2_000_000
    max_properties: int = 4_000_000
    max_property_bytes: int = 512 * 1024**2
    max_array_elements: int = 32_000_000
    max_decompressed_bytes: int = 512 * 1024**2
    require_footer: bool = True


@dataclass(frozen=True)
class FbxNode:
    name: str
    properties: tuple
    children: tuple[FbxNode, ...]


@dataclass(frozen=True)
class FbxDocument:
    version: int
    nodes: tuple[FbxNode, ...]
    sha256: str
    byte_length: int
    footer_verified: bool


def find(nodes, name):
    for node in nodes:
        if node.name == name:
            yield node
        yield from find(node.children, name)


def _one(nodes, name):
    found = [node for node in nodes if node.name == name]
    if len(found) != 1:
        raise FbxError("FBX_STRUCTURE_INVALID", f"Expected one {name}, got {len(found)}")
    return found[0]


class _Reader:
    def __init__(self, stream: BinaryIO, size: int, version: int, limits: ParseLimits):
        self.stream, self.size, self.limits = stream, size, limits
        self.header = struct.Struct("<QQQB" if version >= 7500 else "<IIIB")
        self.nodes = self.properties = self.property_bytes = self.decoded_bytes = 0

    def read(self, count, boundary):
        if count < 0 or self.stream.tell() + count > min(boundary, self.size):
            raise FbxError("FBX_TRUNCATED", "Read exceeds containing scope")
        data = self.stream.read(count)
        if len(data) != count:
            raise FbxError("FBX_TRUNCATED", "Short read")
        return data

    def unpack(self, fmt, boundary):
        return struct.unpack(fmt, self.read(struct.calcsize(fmt), boundary))

    def prop(self, boundary):
        kind = self.read(1, boundary)
        scalars = {b"Y": "<h", b"C": "<B", b"Z": "<b", b"I": "<i", b"F": "<f", b"D": "<d", b"L": "<q"}
        if kind in scalars:
            value = self.unpack(scalars[kind], boundary)[0]
            if isinstance(value, float) and not math.isfinite(value):
                raise FbxError("FBX_NONFINITE", "Nonfinite scalar")
            return value
        if kind in (b"S", b"R"):
            count = self.unpack("<I", boundary)[0]
            if count > self.limits.max_property_bytes:
                raise FbxError("FBX_RESOURCE_LIMIT", "String/blob exceeds property budget")
            value = self.read(count, boundary)
            if kind == b"R":
                return value
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise FbxError("FBX_INVALID_STRING", "String is not UTF-8") from exc
        dtypes = {b"f": "<f4", b"d": "<f8", b"l": "<i8", b"i": "<i4", b"b": "u1", b"c": "i1"}
        if kind not in dtypes:
            raise FbxError("FBX_PROPERTY_UNSUPPORTED", f"Unknown property tag {kind!r}")
        count, encoding, stored = self.unpack("<III", boundary)
        dtype = np.dtype(dtypes[kind])
        expected = count * dtype.itemsize
        if count > self.limits.max_array_elements or stored > self.limits.max_property_bytes:
            raise FbxError("FBX_RESOURCE_LIMIT", "Array exceeds element/stored budget")
        self.decoded_bytes += expected
        if self.decoded_bytes > self.limits.max_decompressed_bytes:
            raise FbxError("FBX_RESOURCE_LIMIT", "Cumulative array budget exceeded")
        data = self.read(stored, boundary)
        if encoding == 1:
            decoder = zlib.decompressobj()
            try:
                data = decoder.decompress(data, expected + 1)
            except zlib.error as exc:
                raise FbxError("FBX_INVALID_COMPRESSION", "Invalid zlib stream") from exc
            if not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
                raise FbxError("FBX_INVALID_COMPRESSION", "Compressed array exceeds declared length or has trailing data")
        elif encoding != 0:
            raise FbxError("FBX_ENCODING_UNSUPPORTED", f"Array encoding {encoding}")
        if len(data) != expected:
            raise FbxError("FBX_ARRAY_LENGTH", "Decoded array size differs from declared size")
        value = np.frombuffer(data, dtype=dtype)
        if value.dtype.kind == "f" and not np.isfinite(value).all():
            raise FbxError("FBX_NONFINITE", "Nonfinite array")
        return value

    def node(self, boundary, depth=0):
        start = self.stream.tell()
        if depth > self.limits.max_depth:
            raise FbxError("FBX_RESOURCE_LIMIT", "Nesting depth exceeded")
        raw = self.read(self.header.size, boundary)
        if raw == bytes(self.header.size):
            return None
        end, count, byte_length, name_length = self.header.unpack(raw)
        if end <= start + self.header.size or end > min(self.size, boundary) or not name_length:
            raise FbxError("FBX_NODE_OFFSET", "Invalid node end/name")
        self.nodes += 1
        self.properties += count
        self.property_bytes += byte_length
        if (self.nodes > self.limits.max_nodes or self.properties > self.limits.max_properties
                or self.property_bytes > self.limits.max_property_bytes):
            raise FbxError("FBX_RESOURCE_LIMIT", "Node/property budget exceeded")
        try:
            name = self.read(name_length, end).decode("ascii")
        except UnicodeDecodeError as exc:
            raise FbxError("FBX_INVALID_STRING", "Node name is not ASCII") from exc
        property_end = self.stream.tell() + byte_length
        if property_end > end or count > byte_length:
            raise FbxError("FBX_PROPERTY_LENGTH", "Impossible property count/length")
        properties = tuple(self.prop(property_end) for _ in range(count))
        if self.stream.tell() != property_end:
            raise FbxError("FBX_PROPERTY_LENGTH", "Property bytes were not consumed exactly")
        children = []
        if self.stream.tell() < end:
            if end - self.stream.tell() < self.header.size:
                raise FbxError("FBX_NODE_OFFSET", "Missing child terminator")
            while self.stream.tell() < end - self.header.size:
                child = self.node(end - self.header.size, depth + 1)
                if child is None:
                    raise FbxError("FBX_NODE_OFFSET", "Early child terminator")
                children.append(child)
            if self.read(self.header.size, end) != bytes(self.header.size):
                raise FbxError("FBX_NODE_OFFSET", "Invalid child terminator")
        if self.stream.tell() != end:
            raise FbxError("FBX_NODE_OFFSET", "Node end mismatch")
        return FbxNode(name, properties, tuple(children))


def file_sha256(path: str | Path, max_bytes: int | None = None) -> str:
    digest, size = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            if max_bytes is not None and size > max_bytes:
                raise FbxError("FBX_RESOURCE_LIMIT", "File exceeds budget")
            digest.update(block)
    return digest.hexdigest()


def _timestamp_footer_checksum(nodes) -> bytes:
    """Recompute the SDK footer ID from its header timestamp, never a prefix.

    Algorithm evidence: hamish-milne/FbxWriter Fbx/FbxBinary.cs,
    GenerateFooterCode/Encrypt. Maintained Assimp FBXExporter.cpp separately
    documents why its fixed-time GENERIC_FOOTID is only an exporter convention.
    This checksum is format consistency, not cryptographic authentication.
    """
    from datetime import datetime
    try:
        header = _one(nodes, 'FBXHeaderExtension')
        timestamp = _one(header.children, 'CreationTimeStamp')
        values = {}
        for field in ('Year', 'Month', 'Day', 'Hour', 'Minute', 'Second', 'Millisecond'):
            entry = _one(timestamp.children, field)
            if len(entry.properties) != 1 or type(entry.properties[0]) is not int:
                raise ValueError('Timestamp components must be single native integers')
            values[field] = entry.properties[0]
        if not 0 <= values['Millisecond'] < 1000:
            raise ValueError('Invalid millisecond')
        datetime(values['Year'], values['Month'], values['Day'], values['Hour'],
                 values['Minute'], values['Second'], values['Millisecond'] * 1000)
        stamp = (f"{values['Second']:02}{values['Month']:02}{values['Hour']:02}"
                 f"{values['Day']:02}{values['Millisecond'] // 10:02}"
                 f"{values['Year']:04}{values['Minute']:02}").encode('ascii')
        state = bytearray.fromhex('58aba9f06ca2d83f4d4749a3b4b2e73d')
        key = bytes.fromhex('e24f7b5fcde4c86ddbd8fbd74058c678')
        for mask in (stamp, key, stamp):
            carry = 64
            for index in range(16):
                state[index] ^= carry ^ mask[index]
                carry = state[index]
        return bytes(state)
    except (FbxError, ValueError, OverflowError) as exc:
        raise FbxError('FBX_FOOTER_UNSUPPORTED', 'Missing/invalid SDK footer timestamp') from exc


def read_fbx_structure(path: str | Path, limits: ParseLimits | None = None) -> FbxDocument:
    limits = limits or ParseLimits()
    if any(value <= 0 for name, value in vars(limits).items() if name.startswith("max_")):
        raise ValueError("Parse budgets must be positive")
    source = Path(path)
    size = source.stat().st_size
    if size > limits.max_file_bytes:
        raise FbxError("FBX_RESOURCE_LIMIT", "File exceeds budget")
    with source.open("rb") as stream:
        initial_stat = os.fstat(stream.fileno())
        if stream.read(23) != MAGIC:
            raise FbxError("FBX_FORMAT_UNSUPPORTED", "Only binary FBX is supported")
        raw_version = stream.read(4)
        if len(raw_version) != 4:
            raise FbxError("FBX_TRUNCATED", "Missing version")
        version = struct.unpack("<I", raw_version)[0]
        if version not in limits.supported_versions:
            raise FbxError("FBX_VERSION_UNSUPPORTED", str(version))
        reader = _Reader(stream, size, version, limits)
        nodes = []
        while True:
            node = reader.node(size)
            if node is None:
                break
            nodes.append(node)
        remaining = size - stream.tell()
        if remaining > 256:
            raise FbxError("FBX_FOOTER_UNSUPPORTED", "Unexpected bytes after root terminator")
        footer = stream.read(remaining)
        # A timestamp-dependent ID precedes zero alignment, repeated version,
        # 120 zeros and the fixed terminal signature. Never accept arbitrary IDs.
        footer_ok = False
        if 160 <= len(footer) <= 192 and footer[-16:] == FOOTER_END:
            version_offset = len(footer) - 140
            footer_ok = (footer[16:version_offset] == bytes(version_offset - 16)
                         and footer[version_offset:version_offset + 4] == raw_version
                         and footer[version_offset + 4:-16] == bytes(120))
            if footer_ok and footer[:16] != FOOTER_START:
                # Diagnostic parsing can inspect an unsupported ID, but can
                # never promote it to footer_verified or structural validation.
                try:
                    footer_ok = footer[:16] == _timestamp_footer_checksum(nodes)
                except FbxError:
                    footer_ok = False
        if limits.require_footer and not footer_ok:
            raise FbxError("FBX_FOOTER_UNSUPPORTED", "Unrecognized/truncated binary footer")
        stream.seek(0)
        digest = hashlib.sha256()
        hashed_bytes = 0
        while block := stream.read(1024 * 1024):
            hashed_bytes += len(block)
            if hashed_bytes > size:
                raise FbxError("FBX_SOURCE_CHANGED", "File grew during validation")
            digest.update(block)
        if hashed_bytes != size:
            raise FbxError("FBX_SOURCE_CHANGED", "File size changed during validation")
        final_stat = os.fstat(stream.fileno())
        if (initial_stat.st_size, initial_stat.st_mtime_ns, initial_stat.st_ctime_ns) != (
                final_stat.st_size, final_stat.st_mtime_ns, final_stat.st_ctime_ns):
            raise FbxError("FBX_SOURCE_CHANGED", "File metadata changed during validation")
    return FbxDocument(version, tuple(nodes), digest.hexdigest(), size, footer_ok)


def properties(node: FbxNode) -> dict:
    result = {}
    for prop in find(node.children, "P"):
        values = prop.properties
        if (len(values) < 4 or not all(isinstance(value, str) for value in values[:4])
                or not values[0] or values[0] in result):
            raise FbxError("FBX_PROPERTY_INVALID", "Invalid/duplicate named property")
        if len(values) == 4:
            # Blender fbx_utils.py p_compound/_elem_props_set writes exactly
            # four strings and no scalar. Keep explicit absence, never zero.
            if values[1] != 'Compound':
                raise FbxError('FBX_PROPERTY_INVALID', 'Only Compound may omit its value')
            result[values[0]] = None
        else:
            result[values[0]] = values[4:] if len(values) > 5 else values[4]
    return result


def timebase(doc: FbxDocument) -> int:
    header = [node for node in doc.nodes if node.name == "FBXHeaderExtension"]
    flags = list(find(header, "TCDefinition"))
    if not flags:
        return LEGACY_KTIME
    if doc.version < 7700 or len(flags) != 1 or len(flags[0].properties) != 1:
        raise FbxError("FBX_TIMECODE_UNSUPPORTED", "Timecode flag/version mismatch")
    value = flags[0].properties[0]
    if value not in (0, 127):
        raise FbxError("FBX_TIMECODE_UNSUPPORTED", str(value))
    return NEW_KTIME if value == 0 else LEGACY_KTIME


def _name(node):
    if len(node.properties) < 2 or not isinstance(node.properties[1], str):
        raise FbxError("FBX_OBJECT_INVALID", "Missing object name")
    return node.properties[1].split("\x00", 1)[0].removeprefix(f"{node.name}::")


def _time_span(values, detail):
    if (len(values) != 2 or any(type(value) is not int or not -(2**63) <= value < 2**63
                                for value in values) or values[0] > values[1]):
        raise FbxError("EXPORT_TIME_SPAN_INVALID", detail)
    return tuple(values)


def take_span(doc: FbxDocument, take_name: str) -> dict:
    """Read explicit local clip metadata; never infer it from curves or globals.

    FbxTakeInfo.mLocalTimeSpan and FbxAnimStack.LocalStart/LocalStop describe
    the local take interval. Reference time is separate and may be offset.
    https://help.autodesk.com/cloudhelp/2020/ENU/FBX-API-Reference/cpp_ref/class_fbx_take_info.html
    """
    stacks = [node for node in _one(doc.nodes, "Objects").children
              if node.name == "AnimationStack"]
    if len(stacks) != 1 or _name(stacks[0]) != take_name:
        raise FbxError("EXPORT_TAKE_MATCH", "Exact single requested take required")
    stack = properties(stacks[0])

    def named_pair(start, stop):
        if start not in stack and stop not in stack:
            return None
        if start not in stack or stop not in stack:
            raise FbxError("EXPORT_TIME_SPAN_INVALID", f"Partial {start}/{stop}")
        return _time_span((stack[start], stack[stop]), f"AnimationStack.{start}/{stop}")

    local = named_pair("LocalStart", "LocalStop")
    reference = named_pair("ReferenceStart", "ReferenceStop")
    sources = ["Objects/AnimationStack/LocalStart+LocalStop"] if local is not None else []
    take_nodes = [node for node in doc.nodes if node.name == "Takes"]
    if len(take_nodes) > 1:
        raise FbxError("EXPORT_TAKE_AMBIGUOUS", "Duplicate Takes containers")
    if take_nodes:
        takes = [node for node in take_nodes[0].children if node.name == "Take"]
        if (len(takes) != 1 or takes[0].properties != (take_name,)):
            raise FbxError("EXPORT_TAKE_AMBIGUOUS", "Exact single matching Takes/Take required")
        current = [node for node in take_nodes[0].children if node.name == "Current"]
        if len(current) > 1 or (current and current[0].properties not in (("",), (take_name,))):
            raise FbxError("EXPORT_TAKE_AMBIGUOUS", "Current take disagrees with the requested take")

        def take_pair(name, required=False):
            matches = [node for node in takes[0].children if node.name == name]
            if not matches and not required:
                return None
            if len(matches) != 1:
                raise FbxError("EXPORT_TIME_SPAN_INVALID", f"Unique Takes/Take/{name} required")
            return _time_span(matches[0].properties, f"Takes/Take/{name}")

        take_local = take_pair("LocalTime", required=True)
        take_reference = take_pair("ReferenceTime")
        if local is not None and local != take_local:
            raise FbxError("EXPORT_TAKE_SPAN_DISAGREEMENT", "Stack and take local intervals differ")
        if reference is not None and take_reference is not None and reference != take_reference:
            raise FbxError("EXPORT_TAKE_SPAN_DISAGREEMENT", "Stack and take reference intervals differ")
        local = take_local
        reference = take_reference if take_reference is not None else reference
        sources.append("Takes/Take/LocalTime")
    if local is None:
        raise FbxError("EXPORT_TAKE_SPAN_UNVERIFIED", "No explicit local take interval")
    return {"name": take_name, "local_start": local[0], "local_stop": local[1],
            "reference_start": reference[0] if reference is not None else None,
            "reference_stop": reference[1] if reference is not None else None,
            "sources": sources}


def _round_tick(value: Fraction) -> int:
    # Nearest integer; half ties go away from zero (positive ties round up).
    sign = -1 if value < 0 else 1
    value = abs(value)
    return sign * ((2 * value.numerator + value.denominator) // (2 * value.denominator))


def expected_ticks(profile: ExportProfile, ticks_per_second: int) -> np.ndarray:
    origin = profile.first_frame if profile.time_origin == "zero" else 0
    values = [_round_tick(Fraction((frame - origin) * profile.fps_den * ticks_per_second,
                                  profile.fps_num))
              for frame in range(profile.first_frame, profile.last_frame + 1)]
    if min(values) < -(2**63) or max(values) >= 2**63:
        raise FbxError("FBX_TIMECODE_UNSUPPORTED", "Requested ticks exceed signed 64-bit FBX time")
    return np.asarray(values, dtype=np.int64)


def _array(node, child_name):
    child = _one(node.children, child_name)
    if len(child.properties) != 1 or not isinstance(child.properties[0], np.ndarray):
        raise FbxError("FBX_ARRAY_LENGTH", f"Missing {child_name} array")
    return child.properties[0]


def validate_fbx_structure(doc: FbxDocument, profile: ExportProfile,
                           expected: ExportExpectation) -> ValidationReport:
    checks = []
    check_counts = {}

    def require(condition, code, detail):
        if not condition:
            raise FbxError(code, detail)
        if code not in check_counts:
            item = {"id": code, "ok": True, "count": 0}
            check_counts[code] = item
            checks.append(item)
        check_counts[code]["count"] += 1

    try:
        require(doc.footer_verified, "FBX_FOOTER_VERIFIED", "Diagnostic parse cannot be promoted to validation")
        settings = properties(_one(doc.nodes, "GlobalSettings"))
        for key, value in (("UpAxis", profile.axes.up_axis), ("UpAxisSign", profile.axes.up_sign),
                           ("FrontAxis", profile.axes.front_axis), ("FrontAxisSign", profile.axes.front_sign),
                           ("CoordAxis", profile.axes.coord_axis), ("CoordAxisSign", profile.axes.coord_sign)):
            require(settings.get(key) == value, "EXPORT_AXES_MATCH", key)
        scale = settings.get("UnitScaleFactor")
        require(isinstance(scale, (int, float)) and scale > 0 and math.isfinite(scale)
                and math.isclose(scale / 100, profile.metres_per_export_unit, rel_tol=1e-10),
                "EXPORT_UNITS_MATCH", "UnitScaleFactor differs from profile")
        mode = settings.get("TimeMode")
        if mode == 14:
            custom = settings.get("CustomFrameRate")
            require(isinstance(custom, (int, float)) and math.isfinite(custom) and custom > 0,
                    "EXPORT_FPS_KNOWN", "Custom frame rate missing")
            rate = float(custom)
        elif mode in FPS:
            rate = FPS[mode][0] / FPS[mode][1]
        else:
            raise FbxError("FBX_FPS_UNSUPPORTED", str(mode))
        require(math.isclose(rate, profile.fps_num / profile.fps_den, rel_tol=profile.tolerances.fps_relative),
                "EXPORT_FPS_MATCH", "Frame rate differs from profile")
        ticks = expected_ticks(profile, timebase(doc))
        require(len(expected.time_s) == len(ticks) and bool(np.allclose(
            np.diff(expected.time_s), profile.fps_den / profile.fps_num, rtol=0, atol=1e-9)) and math.isclose(
            expected.time_s[-1] - expected.time_s[0], (len(ticks) - 1) * profile.fps_den / profile.fps_num,
            abs_tol=1e-9), "EXPORT_DURATION_MATCH", "Expected physical duration differs from profile")
        # GlobalSettings is the scene's default timeline, not the selected clip.
        # SDK FbxGlobalSettings.GetTimelineDefaultTimeSpan documents this distinction.
        global_span = _time_span((settings.get("TimeSpanStart"), settings.get("TimeSpanStop")),
                                 "GlobalSettings.TimeSpanStart/TimeSpanStop")
        objects = _one(doc.nodes, "Objects").children
        by_id = {}
        for node in objects:
            require(bool(node.properties) and type(node.properties[0]) is int,
                    "FBX_OBJECT_ID", "Missing integer object ID")
            identity = node.properties[0]
            require(identity not in by_id and identity != 0, "FBX_UNIQUE_IDS", "Duplicate/reserved object ID")
            by_id[identity] = node
        edges = []
        for edge in _one(doc.nodes, "Connections").children:
            p = edge.properties
            require(edge.name == "C" and len(p) in (3, 4) and p[0] in ("OO", "OP"),
                    "FBX_CONNECTION_SHAPE", "Unknown connection")
            require((p[0] == "OO" and len(p) == 3) or (p[0] == "OP" and len(p) == 4),
                    "FBX_CONNECTION_SHAPE", "Connection arity differs from kind")
            require(p[1] in by_id and (p[2] in by_id or p[2] == 0),
                    "FBX_CONNECTION_TARGET", "Dangling connection")
            edges.append(p)
        models = {identity: node for identity, node in by_id.items() if node.name == "Model"}
        parents = {}
        for edge in edges:
            if edge[0] == "OO" and edge[1] in models and (edge[2] in models or edge[2] == 0):
                require(edge[1] not in parents, "FBX_MODEL_PARENT", "Multiple parents")
                parents[edge[1]] = edge[2]
        paths, visiting, unique_paths = {}, set(), set()

        def path(identity):
            if identity in paths:
                return paths[identity]
            require(identity not in visiting, "FBX_HIERARCHY_ACYCLIC", "Model hierarchy cycle")
            require(len(visiting) < 256, "FBX_RESOURCE_LIMIT", "Model hierarchy depth exceeds supported budget")
            visiting.add(identity)
            parent = parents.get(identity, 0)
            prefix = path(parent) + "/" if parent else ""
            value = prefix + _name(models[identity])
            visiting.remove(identity)
            require(value not in unique_paths, "FBX_PATH_UNIQUE", "Ambiguous model path")
            paths[identity] = value
            unique_paths.add(value)
            return value

        for identity in models:
            path(identity)
        actual_paths = set(paths.values())
        allowed_paths = {bone.node_path for bone in profile.skeleton_map} | set(profile.allowed_helper_nodes) | set(profile.mesh_refs)
        require(actual_paths == allowed_paths, "EXPORT_TARGET_CLOSURE", "Missing or extra model path")
        id_for_path = {value: identity for identity, value in paths.items()}
        for bone in profile.skeleton_map:
            identity = id_for_path[bone.node_path]
            parent_path = paths.get(parents.get(identity, 0))
            require(parent_path == bone.parent_path and expected.parent_paths.get(bone.node_path) == parent_path,
                    "EXPORT_SKELETON_TOPOLOGY", bone.node_path)
        stacks = [node for node in objects if node.name == "AnimationStack"]
        require(len(stacks) == 1 and _name(stacks[0]) == profile.take_name,
                "EXPORT_TAKE_MATCH", "Exact single requested take required")
        stack_id = stacks[0].properties[0]
        span = take_span(doc, profile.take_name)
        for key, tick in (("local_start", ticks[0]), ("local_stop", ticks[-1])):
            require(abs(span[key] - int(tick)) <= profile.tolerances.ticks,
                    "EXPORT_TAKE_SPAN", key)
        require(global_span[0] <= span["local_start"] <= span["local_stop"] <= global_span[1],
                "EXPORT_GLOBAL_SPAN", "Explicit take interval lies outside the scene timeline")
        # FBX connections run child -> parent: curve -> curve node -> layer -> stack.
        layers = {e[1] for e in edges if e[0] == "OO" and e[2] == stack_id
                  and by_id[e[1]].name == "AnimationLayer"}
        curve_nodes = {e[1] for e in edges if e[0] == "OO" and e[2] in layers
                       and by_id[e[1]].name == "AnimationCurveNode"}
        model_bindings = {}
        for edge in edges:
            if edge[0] == "OP" and edge[1] in curve_nodes and edge[2] in models:
                model_bindings.setdefault(edge[1], []).append(edge)
        channels = {}
        for edge in edges:
            if edge[0] != "OP" or edge[2] not in curve_nodes or by_id[edge[1]].name != "AnimationCurve":
                continue
            bindings = model_bindings.get(edge[2], ())
            require(len(bindings) == 1 and len(edge) == 4 and edge[3] in ("d|X", "d|Y", "d|Z"),
                    "EXPORT_CURVE_BINDING", "Ambiguous curve target")
            target = bindings[0]
            key = (paths[target[2]], target[3], edge[3][-1])
            require(key not in channels, "EXPORT_CURVE_UNIQUE", "Duplicate channel")
            channels[key] = by_id[edge[1]]
        all_curves = {identity for identity, node in by_id.items() if node.name == "AnimationCurve"}
        require(all_curves == {node.properties[0] for node in channels.values()},
                "EXPORT_CURVE_TAKE_MEMBERSHIP", "Curve belongs to another/unbound take or target")
        for curve in channels.values():
            times, values = _array(curve, "KeyTime"), _array(curve, "KeyValueFloat")
            require(times.dtype.kind in "iu" and len(times) > 0 and len(times) == len(values)
                    and bool(np.all(times[1:] > times[:-1])) and bool(np.isfinite(values).all()),
                    "EXPORT_CURVE_VALID", "Empty/nonincreasing curve or value coverage mismatch")
            require(times[0] >= ticks[0] - profile.tolerances.ticks
                    and times[-1] <= ticks[-1] + profile.tolerances.ticks,
                    "EXPORT_CURVE_INTERVAL", "Curve outside requested interval")
        for channel in profile.required_channels:
            curve = channels.get((channel.node_path, channel.property, channel.axis))
            if channel.animated:
                require(curve is not None, "EXPORT_REQUIRED_CHANNEL", str(channel))
                if profile.bake == "dense":
                    times = _array(curve, "KeyTime")
                    nearest = np.searchsorted(times, ticks)
                    nearest = np.clip(nearest, 0, len(times) - 1)
                    left = np.maximum(nearest - 1, 0)
                    distance = np.minimum(np.abs(times[nearest] - ticks), np.abs(times[left] - ticks))
                    require(bool(np.all(distance <= profile.tolerances.ticks)),
                            "EXPORT_DENSE_COVERAGE", str(channel))
            else:
                require(channel.constant_value is not None, "EXPORT_CONSTANT_DECLARED", str(channel))
                if curve is not None:
                    require(bool(np.all(np.abs(_array(curve, "KeyValueFloat") - channel.constant_value) <= 1e-8)),
                            "EXPORT_CONSTANT_CHANNEL", str(channel))
                else:
                    values = properties(models[id_for_path[channel.node_path]]).get(channel.property)
                    require(isinstance(values, tuple) and len(values) == 3
                            and abs(values["XYZ".index(channel.axis)] - channel.constant_value) <= 1e-8,
                            "EXPORT_CONSTANT_CHANNEL", str(channel))
        _validate_skin(by_id, edges, paths, profile, require)
        return ValidationReport(status="pass", artifact_sha256=doc.sha256, checks=tuple(checks))
    except FbxError as exc:
        status = "unsupported" if "UNSUPPORTED" in exc.code else "fail"
        return ValidationReport(status=status, artifact_sha256=doc.sha256,
                                checks=tuple(checks) + ({"id": exc.code, "ok": False, "detail": str(exc)},),
                                reason_codes=(exc.code,))
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        return ValidationReport(status="fail", artifact_sha256=doc.sha256,
                                checks=tuple(checks) + ({"id": "FBX_STRUCTURE_INVALID", "ok": False,
                                                        "detail": str(exc)[:1000]},),
                                reason_codes=("FBX_STRUCTURE_INVALID",))


def _validate_skin(by_id, edges, paths, profile, require):
    mesh_ids = {identity for identity, node in by_id.items()
                if node.name == "Model" and len(node.properties) > 2 and node.properties[2] == "Mesh"}
    require({paths[i] for i in mesh_ids} == set(profile.mesh_refs),
            "EXPORT_MESH_MATCH", "Unexpected/missing mesh")
    if not profile.include_mesh:
        require(not any(node.name == "Deformer" for node in by_id.values()),
                "EXPORT_NO_SKIN", "Skeleton-only profile contains deformers")
        return
    parents, children = {}, {}
    for edge in edges:
        if edge[0] == "OO":
            parents.setdefault(edge[1], set()).add(edge[2])
            children.setdefault(edge[2], set()).add(edge[1])
    bone_ids = {identity for identity, value in paths.items()
                if value in {bone.node_path for bone in profile.skeleton_map}}
    for mesh_id in mesh_ids:
        geometries = [identity for identity in children.get(mesh_id, ()) if by_id[identity].name == "Geometry"]
        require(len(geometries) == 1, "EXPORT_SKIN_GEOMETRY", "Mesh needs exact geometry")
        geometry_id = geometries[0]
        positions = _array(by_id[geometry_id], "Vertices")
        require(len(positions) % 3 == 0, "EXPORT_VERTEX_SHAPE", "Vertices are not triples")
        vertex_count = len(positions) // 3
        polygons = _array(by_id[geometry_id], "PolygonVertexIndex")
        vertex_indices = np.where(polygons < 0, -polygons - 1, polygons)
        require(polygons.dtype.kind in "iu" and bool(np.all((vertex_indices >= 0) & (vertex_indices < vertex_count)))
                and len(polygons) > 0 and polygons[-1] < 0,
                "EXPORT_POLYGON_INDICES", "Invalid polygon topology")
        skin_ids = [identity for identity in children.get(geometry_id, ())
                    if by_id[identity].name == "Deformer" and len(by_id[identity].properties) > 2
                    and by_id[identity].properties[2] == "Skin"]
        require(len(skin_ids) == 1, "EXPORT_SKIN_LINK", "Mesh needs exact skin binding")
        sums = np.zeros(vertex_count)
        clusters = [identity for identity in children.get(skin_ids[0], ())
                    if by_id[identity].name == "Deformer" and len(by_id[identity].properties) > 2
                    and by_id[identity].properties[2] == "Cluster"]
        require(bool(clusters), "EXPORT_CLUSTER_LINK", "Skin has no clusters")
        for cluster_id in clusters:
            cluster = by_id[cluster_id]
            indices, weights = _array(cluster, "Indexes"), _array(cluster, "Weights")
            require(len(indices) == len(weights) and indices.dtype.kind in "iu"
                    and bool(np.all((indices >= 0) & (indices < vertex_count)))
                    and bool(np.all(weights >= 0)), "EXPORT_WEIGHTS_VALID", "Invalid skin weights/indices")
            linked = bone_ids & children.get(cluster_id, set())
            require(len(linked) == 1, "EXPORT_CLUSTER_BONE", "Cluster needs exact expected bone")
            for name in ("Transform", "TransformLink"):
                require(len(_array(cluster, name)) == 16, "EXPORT_SKIN_MATRIX", name)
            np.add.at(sums, indices, weights)
        require(bool(np.all(sums > 0)), "EXPORT_SKIN_COVERAGE", "Unweighted vertices")
        if profile.weights_normalization == "unit_sum":
            require(bool(np.all(np.abs(sums - 1) <= 1e-5)), "EXPORT_WEIGHT_SUM", "Weights do not sum to one")
