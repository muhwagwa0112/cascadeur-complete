"""Windows retirement of an independently authenticated, finite effect scope.

This is an internal executor, not a wire authorization endpoint. A code-owned
producer verifier must first authenticate the original attempt, its complete
producer/consumer set, and its sealed file footprint. An authenticated JSON
manifest, an operator's assertion, or PID absence alone does not supply that
knowledge. Legacy attempts without that evidence are unsupported.

Supported containment is deliberately finite: regular, singly linked files and
flat owned output directories, preserved in place. No deletion, recursive scan,
process-tree guess, automatic retry of termination, or workspace creation occurs.
The control layer owns approval, retirement_started journaling, and publication.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
from dataclasses import asdict, dataclass, is_dataclass
from functools import wraps
import hashlib
import hmac
import inspect
import json
import marshal
import os
from pathlib import Path
import threading

from . import incident_policy as p

EvidenceUnavailable = p.EvidenceUnavailable
_PURPOSE = b"cascadeur-complete/incident-os-retirement/v1\0"
_MAX_PROCESSES, _MAX_FILES = 64, 4096
_AUTHORITIES = {}
_EXECUTIONS = {}
_LOCK = threading.RLock()
_LOADED_MODULE_DIGEST = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _clone(value):
    return json.loads(p._canonical(asdict(value) if is_dataclass(value) else value))


def _fail(reason):
    raise EvidenceUnavailable(reason)


def _unavailable_boundary(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except EvidenceUnavailable:
            raise
        except (OSError, KeyError, AttributeError, TypeError, ValueError, OverflowError, ctypes.ArgumentError) as error:
            raise EvidenceUnavailable(function.__name__ + ":" + type(error).__name__ + ":" + str(error)) from error
    return call


def _source_pin(callback):
    if not inspect.isfunction(callback):
        _fail("CODE_OWNED_RESOURCE_VERIFIER_REQUIRED")
    source = Path(inspect.getsourcefile(callback) or "").resolve(strict=True)
    if source.parent != Path(__file__).resolve().parent:
        _fail("RESOURCE_VERIFIER_OUTSIDE_INSTALLED_PACKAGE")
    return {"module": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "qualname": callback.__qualname__,
            "code_sha256": hashlib.sha256(marshal.dumps(callback.__code__)).hexdigest()}


@dataclass(frozen=True)
class _Authority:
    name: str
    secret: bytes
    scope: object
    baseline: object
    approval: object
    workspace: object
    pins: tuple

    def check(self):
        if tuple(_source_pin(f) for f in (self.scope, self.baseline, self.approval, self.workspace)) != self.pins:
            _fail("RESOURCE_VERIFIER_BYTES_CHANGED")


def _enroll_authority(authority_id, *, receipt_secret, verify_scope, verify_baseline,
                      verify_approval, verify_workspace):
    """Private startup hook; never register from request arguments.

    Callbacks must be installed-package functions backed by actual producer or
    checkpoint authority. scope(manifest, original) returns exact original,
    manifest_digest, closure_evidence_digest, scope_revision, processes,
    resources, and resource_roots. Each process has pid/creation_time_100ns/
    image_path/image_sha256; each file has path/role/size/sha256. All children,
    external consumers and possible effects must be covered by that verifier;
    there is intentionally no caller 'closed' field.

    baseline(ref, original) authenticates preincident_checkpoint or
    immutable_fixture_generator provenance, returning path/size/sha256,
    provenance_path/provenance_sha256/provenance_digest/origin_kind.
    approval(plan, authorization) authenticates the exact approved outer plan
    and returns its approval digest. workspace(payload, intent, retirements)
    authenticates a new workspace/input derivation and returns workspace_path,
    baseline_digest and resources (path/size/sha256). It must bind the complete
    WorkIntent, original baseline lineage, registry/heads and all retirements.

    The original-domain secret issues a separate-purpose OS receipt ONLY inside
    the successful executor. A native mirror can verify it after host exit, then
    independently recheck current physical containment. HMAC does not replace
    any producer/baseline callback or OS observation.
    """
    if not isinstance(authority_id, str) or not authority_id or len(authority_id) > 160:
        _fail("INVALID_RESOURCE_AUTHORITY_ID")
    if not isinstance(receipt_secret, bytes) or len(receipt_secret) < 32:
        _fail("ORIGINAL_RESOURCE_AUTHORITY_KEY_UNAVAILABLE")
    callbacks = (verify_scope, verify_baseline, verify_approval, verify_workspace)
    authority = _Authority(authority_id, receipt_secret, *callbacks,
                           tuple(_source_pin(f) for f in callbacks))
    key = (authority_id, p.auth_domain_id(receipt_secret))
    with _LOCK:
        previous = _AUTHORITIES.get(key)
        if previous is not None and previous != authority:
            _fail("RESOURCE_AUTHORITY_ALREADY_ENROLLED")
        _AUTHORITIES[key] = authority


def _authority(manifest, original):
    try:
        authority = _AUTHORITIES[(manifest["authority_id"], original["domain"]["auth_domain_id"])]
    except (KeyError, TypeError):
        _fail("ORIGINAL_PRODUCER_RESOURCE_CONSUMER_VERIFIER_UNAVAILABLE")
    authority.check()
    return authority


class _FileInfo(ctypes.Structure):
    _fields_ = [("attributes", w.DWORD), ("created", w.FILETIME), ("accessed", w.FILETIME),
                ("written", w.FILETIME), ("volume", w.DWORD), ("size_high", w.DWORD),
                ("size_low", w.DWORD), ("links", w.DWORD), ("index_high", w.DWORD),
                ("index_low", w.DWORD)]


class _FileId(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_ulonglong), ("identifier", ctypes.c_ubyte * 16)]


def _api():
    if os.name != "nt":
        _fail("WINDOWS_RESOURCE_VERIFIER_REQUIRED")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateFileW": ([w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
        "CloseHandle": ([w.HANDLE], w.BOOL),
        "GetFileInformationByHandle": ([w.HANDLE, ctypes.POINTER(_FileInfo)], w.BOOL),
        "GetFileInformationByHandleEx": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
        "GetFinalPathNameByHandleW": ([w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD], w.DWORD),
        "ReadFile": ([w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID], w.BOOL),
        "SetFilePointerEx": ([w.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), w.DWORD], w.BOOL),
        "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        "GetProcessTimes": ([w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME),
                             ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)], w.BOOL),
        "QueryFullProcessImageNameW": ([w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
        "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
        "GetExitCodeProcess": ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
        "TerminateProcess": ([w.HANDLE, w.UINT], w.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def _checked(ok, label):
    if not ok:
        _fail(label + ":winerror=" + str(ctypes.get_last_error()))


def _ticks(value):
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


class _Handle:
    def __init__(self, kernel, value):
        if not value or value == ctypes.c_void_p(-1).value:
            _fail("RESOURCE_HANDLE_UNAVAILABLE:winerror=" + str(ctypes.get_last_error()))
        self.kernel, self.value = kernel, value

    def close(self):
        if self.value is not None:
            self.kernel.CloseHandle(self.value)
            self.value = None


def _identity(handle):
    info, identifier = _FileInfo(), _FileId()
    _checked(handle.kernel.GetFileInformationByHandle(handle.value, ctypes.byref(info)), "FILE_INFORMATION_UNAVAILABLE")
    _checked(handle.kernel.GetFileInformationByHandleEx(handle.value, 18, ctypes.byref(identifier),
                                                       ctypes.sizeof(identifier)), "FILE_ID_128_UNAVAILABLE")
    if info.attributes & 0x400:
        _fail("REPARSE_RESOURCE_UNSUPPORTED")
    directory = bool(info.attributes & 0x10)
    if not directory and info.links != 1:
        _fail("HARDLINK_RESOURCE_COVERAGE_UNAVAILABLE")
    path = ctypes.create_unicode_buffer(32768)
    length = handle.kernel.GetFinalPathNameByHandleW(handle.value, path, len(path), 0)
    if not 0 < length < len(path):
        _fail("FINAL_RESOURCE_PATH_UNAVAILABLE")
    return {"path": os.path.normcase(path.value), "volume": int(identifier.volume),
            "file_id": bytes(identifier.identifier).hex(), "kind": "directory" if directory else "file",
            "links": int(info.links), "size": (int(info.size_high) << 32) | int(info.size_low),
            "last_write_100ns": _ticks(info.written)}


def _key(identity):
    return identity["volume"], identity["file_id"]


def _local_path(path):
    path = Path(path)
    if not path.is_absolute() or path.drive.startswith("\\\\"):
        _fail("LOCAL_ABSOLUTE_RESOURCE_PATH_REQUIRED")
    if any(":" in part or part.endswith((".", " ")) or part == ".." for part in path.parts[1:]):
        _fail("ALTERNATE_STREAM_OR_NONCANONICAL_RESOURCE_PATH_UNSUPPORTED")
    return path


def _open_file(path, *, exclusive=False):
    """Pin every ancestor against reparse/rename; sharing restriction only at commit."""
    kernel = _api()
    path = _local_path(path)
    handles, identities = [], []
    try:
        for item in (*reversed(path.parents), path):
            # OPEN_REPARSE_POINT makes a symlink/junction observable rather than following it.
            value = kernel.CreateFileW(str(item), 0x80000000 if item == path else 0x80,
                1 if exclusive else 7, None, 3, 0x02200000, None)
            handle = _Handle(kernel, value)
            handles.append(handle)
            identities.append(_identity(handle))
        if any(row["kind"] != "directory" for row in identities[:-1]):
            _fail("RESOURCE_ANCESTOR_NOT_DIRECTORY")
        return handles, identities
    except BaseException:
        for handle in reversed(handles):
            handle.close()
        raise


def _close(handles):
    for handle in reversed(handles):
        handle.close()


def _hash_handle(handle, expected_size):
    before = _identity(handle)
    if before["kind"] != "file" or before["size"] != expected_size:
        _fail("RESOURCE_SIZE_OR_KIND_CHANGED")
    _checked(handle.kernel.SetFilePointerEx(handle.value, 0, None, 0), "RESOURCE_SEEK_FAILED")
    digest, total = hashlib.sha256(), 0
    buffer, read = ctypes.create_string_buffer(1024 * 1024), w.DWORD()
    while total < expected_size:
        _checked(handle.kernel.ReadFile(handle.value, buffer, min(len(buffer), expected_size - total),
                                        ctypes.byref(read), None), "RESOURCE_READ_FAILED")
        if read.value == 0:
            _fail("RESOURCE_TRUNCATED_DURING_READ")
        digest.update(buffer.raw[:read.value])
        total += read.value
    _checked(handle.kernel.ReadFile(handle.value, buffer, 1, ctypes.byref(read), None), "RESOURCE_READ_FAILED")
    if read.value or _identity(handle) != before:
        _fail("RESOURCE_CHANGED_DURING_READ")
    return digest.hexdigest()


def _file_record(expected, *, exclusive=False, retain=None):
    if type(expected.get("size")) is not int or expected["size"] < 0:
        _fail("DECLARED_RESOURCE_SIZE_REQUIRED")
    p._digest_string(expected.get("sha256"), "resource sha256")
    handles, ancestry = _open_file(expected["path"], exclusive=exclusive)
    try:
        actual = _hash_handle(handles[-1], expected["size"])
        if actual != expected["sha256"]:
            _fail("RESOURCE_HASH_DIFFERS")
        result = {"identity": ancestry[-1], "ancestor_ids": [list(_key(i)) for i in ancestry[:-1]],
                  "sha256": actual, "path": str(Path(expected["path"]).absolute())}
        if "role" in expected:
            if expected["role"] not in ("input", "output", "evidence"):
                _fail("RESOURCE_ROLE_UNSUPPORTED")
            result["role"] = expected["role"]
        return result
    finally:
        if retain is not None:
            retain.extend(handles)
        else:
            _close(handles)


def _directory_record(path, *, exclusive=False, retain=None):
    handles, ancestry = _open_file(path, exclusive=exclusive)
    try:
        if ancestry[-1]["kind"] != "directory":
            _fail("RESOURCE_DIRECTORY_REQUIRED")
        return {"path": str(Path(path).absolute()), "identity": ancestry[-1],
                "ancestor_ids": [list(_key(i)) for i in ancestry[:-1]]}
    finally:
        if retain is not None:
            retain.extend(handles)
        else:
            _close(handles)


def _same_file(left, right):
    # Directory timestamps/size can change through unrelated approved children;
    # identity, aliases and actual file content are checked separately.
    fields = ("path", "volume", "file_id", "kind", "links")
    return all(left["identity"][k] == right["identity"][k] for k in fields)


def _flat_namespaces(roots, resources):
    """All files in an owned output namespace must be explicitly preserved."""
    for root in roots:
        expected = {_key(row["identity"]) for row in resources
                    if list(_key(root["identity"])) == (row["ancestor_ids"][-1] if row["ancestor_ids"] else None)}
        actual = set()
        with os.scandir(root["path"]) as entries:
            for index, entry in enumerate(entries):
                if index >= _MAX_FILES:
                    _fail("FINITE_RESOURCE_NAMESPACE_BUDGET_EXCEEDED")
                handles, ancestry = _open_file(entry.path)
                try:
                    if ancestry[-1]["kind"] != "file":
                        _fail("NESTED_OR_NONREGULAR_OUTPUT_NAMESPACE_UNSUPPORTED")
                    actual.add(_key(ancestry[-1]))
                finally:
                    _close(handles)
        if actual != expected:
            _fail("OUTPUT_NAMESPACE_NOT_EXACT_ENROLLED_FILE_SET")
    root_keys = {tuple(_key(row["identity"])) for row in roots}
    for resource in resources:
        if resource["role"] == "output" and (not resource["ancestor_ids"] or
                                               tuple(resource["ancestor_ids"][-1]) not in root_keys):
            _fail("OUTPUT_OUTSIDE_CLOSED_FLAT_NAMESPACE")


def _process(expected):
    pid = expected.get("pid")
    if type(pid) is not int or pid <= 4 or pid == os.getpid():
        _fail("PRODUCER_PID_UNSUPPORTED")
    if type(expected.get("creation_time_100ns")) is not int or expected["creation_time_100ns"] <= 0:
        _fail("EXACT_ORIGINAL_PROCESS_CREATION_TIME_REQUIRED")
    kernel = _api()
    handle = _Handle(kernel, kernel.OpenProcess(0x1000 | 0x100000 | 1, False, pid))
    try:
        created, exited, system, user = (w.FILETIME() for _ in range(4))
        _checked(kernel.GetProcessTimes(handle.value, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(system), ctypes.byref(user)), "PROCESS_TIMES_UNAVAILABLE")
        if _ticks(created) != expected.get("creation_time_100ns"):
            _fail("PRODUCER_PID_REUSED_OR_CREATION_TIME_DIFFERS")
        image, length = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
        _checked(kernel.QueryFullProcessImageNameW(handle.value, 0, image, ctypes.byref(length)), "PROCESS_IMAGE_UNAVAILABLE")
        image_path = Path(image.value)
        record = _file_record({"path": str(image_path), "size": image_path.stat().st_size,
                               "sha256": expected.get("image_sha256")})
        given_image = Path(expected["image_path"])
        given_record = _file_record({"path": str(given_image), "size": given_image.stat().st_size,
                                    "sha256": expected.get("image_sha256")})
        if not _same_file(record, given_record):
            _fail("PRODUCER_IMAGE_IDENTITY_DIFFERS")
        # Keep the opened process object; reopening a PID after death is not equivalent.
        return handle, {"pid": pid, "creation_time_100ns": _ticks(created), "image": record}
    except BaseException:
        handle.close()
        raise


def _scope(authority, manifest, original):
    facts = _clone(authority.scope(_clone(manifest), _clone(original)))
    if (facts.get("original") != original or facts.get("manifest_digest") != p.digest(manifest)
            or not isinstance(facts.get("scope_revision"), str) or not facts["scope_revision"]):
        _fail("ORIGINAL_FINITE_SCOPE_BINDING_DIFFERS")
    p._digest_string(facts.get("closure_evidence_digest"), "producer closure evidence")
    processes, resources, roots = (facts.get(k) for k in ("processes", "resources", "resource_roots"))
    if (not isinstance(processes, list) or not 0 < len(processes) <= _MAX_PROCESSES
            or not isinstance(resources, list) or not 0 < len(resources) <= _MAX_FILES
            or not isinstance(roots, list) or not 0 < len(roots) <= _MAX_FILES):
        _fail("FINITE_PRODUCER_FILE_CLOSURE_REQUIRED")
    if len({(r["pid"], r["creation_time_100ns"]) for r in processes}) != len(processes):
        _fail("DUPLICATE_PRODUCER_IDENTITY")
    return facts


def _baseline(authority, reference, original):
    facts = _clone(authority.baseline(_clone(reference), _clone(original)))
    if facts.get("origin_kind") not in ("preincident_checkpoint", "immutable_fixture_generator"):
        _fail("IMMUTABLE_PREINCIDENT_BASELINE_PROVENANCE_UNAVAILABLE")
    p._digest_string(facts.get("provenance_digest"), "baseline provenance")
    file = _file_record(facts)
    provenance_path = Path(facts["provenance_path"])
    provenance = _file_record({"path": str(provenance_path), "size": provenance_path.stat().st_size,
                               "sha256": facts["provenance_sha256"]})
    return {"facts": facts, "file": file, "provenance": provenance}


def _new_workspace(path):
    path = _local_path(path)
    try:
        path.lstat()
    except FileNotFoundError:
        pass
    else:
        _fail("NEW_WORKSPACE_MUST_NOT_EXIST")
    if path.name in ("", ".", ".."):
        _fail("NEW_WORKSPACE_MUST_NOT_EXIST")
    return {"path": str(path), "parent": _directory_record(path.parent),
            "create": "exclusive_new_directory"}


def _disjoint(workspace, roots, resources, baseline):
    parent = workspace["parent"]
    parent_chain = {tuple(row) for row in parent["ancestor_ids"]} | {_key(parent["identity"])}
    for root in roots:
        if _key(root["identity"]) in parent_chain:
            _fail("NEW_WORKSPACE_INSIDE_RETIRED_NAMESPACE")
    for resource in resources:
        if resource["role"] == "output" and _key(resource["identity"]) in {
                _key(baseline["file"]["identity"]), _key(baseline["provenance"]["identity"])}:
            _fail("BASELINE_ALIASES_UNKNOWN_OUTPUT")


@_unavailable_boundary
def inspect_retirement_scope(producer_manifest, original_ref, baseline_ref, new_workspace):
    """Read-only exact plan components. No process termination or file creation."""
    manifest, original = _clone(producer_manifest), _clone(original_ref)
    authority = _authority(manifest, original)
    facts = _scope(authority, manifest, original)
    processes, handles = [], []
    try:
        for expected in facts["processes"]:
            handle, actual = _process(expected)
            handles.append(handle)
            processes.append(actual)
        resources = [_file_record(row) for row in facts["resources"]]
        if len({_key(r["identity"]) for r in resources}) != len(resources):
            _fail("RESOURCE_ALIASES_DUPLICATE_SAME_FILE")
        roots = [_directory_record(path) for path in facts["resource_roots"]]
        if len({_key(r["identity"]) for r in roots}) != len(roots):
            _fail("RESOURCE_ROOT_ALIASES_DUPLICATE")
        _flat_namespaces(roots, resources)
        baseline = _baseline(authority, baseline_ref, original)
        workspace = _new_workspace(new_workspace["path"] if isinstance(new_workspace, dict) else new_workspace)
        _disjoint(workspace, roots, resources, baseline)
        component = {"schema_version": 1, "authority_id": authority.name, "original": original,
            "producer_manifest": manifest, "scope_facts": facts, "processes": processes,
            "resources": resources, "resource_roots": roots, "baseline_ref": _clone(baseline_ref),
            "baseline": baseline, "baseline_digest": p.digest(baseline), "new_workspace": workspace,
            "operations": [{"kind": "terminate_exact_process", "identity": row} for row in processes]
                + [{"kind": "preserve_in_place", "identity": row["identity"], "sha256": row["sha256"]}
                   for row in resources]}
        component["component_digest"] = p.digest(component)
        return component
    finally:
        _close(handles)


def _validate_plan(plan):
    plan = _clone(plan)
    supplied = plan.pop("component_digest", None)
    if plan.get("schema_version") != 1 or p.digest(plan) != supplied:
        _fail("RETIREMENT_COMPONENT_DIGEST_DIFFERS")
    plan["component_digest"] = supplied
    authority = _authority(plan["producer_manifest"], plan["original"])
    if authority.name != plan["authority_id"] or _scope(authority, plan["producer_manifest"], plan["original"]) != plan["scope_facts"]:
        _fail("PRODUCER_RESOURCE_SCOPE_CHANGED")
    facts = plan["scope_facts"]
    if (len(plan["processes"]) != len(facts["processes"]) or len(plan["resources"]) != len(facts["resources"])
            or len(plan["resource_roots"]) != len(facts["resource_roots"])
            or plan.get("baseline_digest") != p.digest(plan["baseline"])):
        _fail("RETIREMENT_COMPONENT_COVERAGE_DIFFERS")
    operations = [{"kind": "terminate_exact_process", "identity": row} for row in plan["processes"]]
    operations += [{"kind": "preserve_in_place", "identity": row["identity"], "sha256": row["sha256"]}
                   for row in plan["resources"]]
    if plan["operations"] != operations:
        _fail("RETIREMENT_OPERATION_LIST_DIFFERS")
    return plan, authority


def _current_resources(plan, *, exclusive=False, retain=None):
    resources = [_file_record(row, exclusive=exclusive, retain=retain) for row in plan["scope_facts"]["resources"]]
    roots = [_directory_record(row["path"], exclusive=exclusive, retain=retain) for row in plan["resource_roots"]]
    if (any(not _same_file(a, b) or a["sha256"] != b["sha256"] for a, b in zip(resources, plan["resources"]))
            or any(not _same_file(a, b) for a, b in zip(roots, plan["resource_roots"]))):
        _fail("RETIRED_RESOURCE_IDENTITY_CHANGED")
    _flat_namespaces(roots, resources)
    baseline = _baseline(_authority(plan["producer_manifest"], plan["original"]), plan["baseline_ref"], plan["original"])
    if baseline != plan["baseline"]:
        _fail("BASELINE_IDENTITY_OR_PROVENANCE_CHANGED")
    return resources, roots, baseline


def _termination_observation(handle, process):
    if handle.kernel.WaitForSingleObject(handle.value, 0) != 0:
        _fail("ORIGINAL_PROCESS_OBJECT_NOT_SIGNALED")
    created, exited, system, user = (w.FILETIME() for _ in range(4))
    _checked(handle.kernel.GetProcessTimes(handle.value, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(system), ctypes.byref(user)), "TERMINATED_PROCESS_TIMES_UNAVAILABLE")
    code = w.DWORD()
    _checked(handle.kernel.GetExitCodeProcess(handle.value, ctypes.byref(code)), "PROCESS_EXIT_CODE_UNAVAILABLE")
    if _ticks(created) != process["creation_time_100ns"] or not _ticks(exited):
        _fail("TERMINATED_PROCESS_IDENTITY_DIFFERS")
    return {"identity": process, "wait_result": 0, "exit_time_100ns": _ticks(exited), "exit_code": int(code.value)}


def _module_digest():
    actual = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if actual != _LOADED_MODULE_DIGEST:
        _fail("OS_RETIREMENT_EXECUTOR_BYTES_CHANGED")
    return actual


def _receipt_mac(authority, body):
    key = hmac.new(authority.secret, _PURPOSE, hashlib.sha256).digest()
    return hmac.new(key, p._canonical(body), hashlib.sha256).hexdigest()


@_unavailable_boundary
def execute_approved_retirement(plan, authorization):
    """Execute once, after control has durably recorded retirement_started.

    The private approval verifier must authenticate that durable started state,
    exact outer-plan/operator approval, expiry and heads. It returns an approval
    digest, never a boolean. Partial termination is unknown: a second call only
    observes retained process objects, and never dispatches another termination.
    """
    _module_digest()
    plan, authority = _validate_plan(plan)
    approval_digest = authority.approval(_clone(plan), _clone(authorization))
    p._digest_string(approval_digest, "operator approval")
    component = plan["component_digest"]
    with _LOCK:
        attempt = _EXECUTIONS.get(component)
        if attempt is None:
            attempt = {"approval_digest": approval_digest, "handles": [], "files": [], "started": False}
            _EXECUTIONS[component] = attempt
            try:
                # Acquire every denied-write/delete file pin BEFORE any process effect.
                _current_resources(plan, exclusive=True, retain=attempt["files"])
                current_workspace = _new_workspace(plan["new_workspace"]["path"])
                if not _same_file(current_workspace["parent"], plan["new_workspace"]["parent"]):
                    _fail("NEW_WORKSPACE_PARENT_CHANGED")
                for expected, planned in zip(plan["scope_facts"]["processes"], plan["processes"]):
                    handle, actual = _process(expected)
                    attempt["handles"].append(handle)
                    if actual != planned:
                        _fail("ORIGINAL_PROCESS_IDENTITY_CHANGED")
                if _scope(authority, plan["producer_manifest"], plan["original"]) != plan["scope_facts"]:
                    _fail("PRODUCER_SCOPE_CHANGED_BEFORE_TERMINATION")
                attempt["started"] = True
                for handle in attempt["handles"]:
                    if handle.kernel.WaitForSingleObject(handle.value, 0) == 0x102:
                        _checked(handle.kernel.TerminateProcess(handle.value, 0xE0000001), "EXACT_PROCESS_TERMINATION_FAILED")
                    if handle.kernel.WaitForSingleObject(handle.value, 5000) != 0:
                        _fail("PROCESS_TERMINATION_NOT_OBSERVED")
            except BaseException:
                if not attempt["started"]:
                    _close(attempt["files"]); _close(attempt["handles"])
                    del _EXECUTIONS[component]
                raise
        if attempt["approval_digest"] != approval_digest:
            _fail("RETIREMENT_APPROVAL_CHANGED")
        observations = [_termination_observation(handle, process)
                        for handle, process in zip(attempt["handles"], plan["processes"])]
        if len(observations) != len(plan["processes"]):
            _fail("COMPLETE_PRODUCER_TERMINATION_NOT_OBSERVED")
        resources, roots, baseline = _current_resources(plan)
        body = {"schema_version": 1, "kind": "windows_exact_retirement", "original": plan["original"],
            "component_digest": component, "authority_id": authority.name, "issuer_module_sha256": _module_digest(),
            "approval_digest": approval_digest, "producer_scope_digest": p.digest(plan["scope_facts"]),
            "terminations": observations, "resources": resources, "resource_roots": roots,
            "baseline": baseline, "new_workspace": plan["new_workspace"], "disposition": "preserved_in_place"}
        body["os_receipt_mac"] = _receipt_mac(authority, body)
        attempt["payload"] = _clone(body)
        return body


@_unavailable_boundary
def verify_retirement_evidence(payload, plan):
    """Verify code-issued durable OS observations AND current containment.

    Native/host mirrors enroll the original-domain authority/key separately.
    After restart this relies on the authenticated executor receipt's issuer
    bytes and recorded exact-object wait, never on reopening a missing PID.
    """
    plan, authority = _validate_plan(plan)
    payload = _clone(payload)
    supplied = payload.pop("os_receipt_mac", None)
    expected = _receipt_mac(authority, payload)
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
        _fail("OS_RETIREMENT_RECEIPT_AUTHENTICATION_FAILED")
    if (payload.get("schema_version") != 1 or payload.get("kind") != "windows_exact_retirement"
            or payload.get("original") != plan["original"] or payload.get("component_digest") != plan["component_digest"]
            or payload.get("authority_id") != authority.name or payload.get("issuer_module_sha256") != _module_digest()
            or payload.get("producer_scope_digest") != p.digest(plan["scope_facts"])
            or payload.get("disposition") != "preserved_in_place" or payload.get("new_workspace") != plan["new_workspace"]):
        _fail("OS_RETIREMENT_RECEIPT_BINDING_DIFFERS")
    p._digest_string(payload.get("approval_digest"), "operator approval")
    observations = payload.get("terminations")
    if not isinstance(observations, list) or len(observations) != len(plan["processes"]):
        _fail("OS_RECEIPT_PRODUCER_COVERAGE_DIFFERS")
    for row, process in zip(observations, plan["processes"]):
        if (row.get("identity") != process or row.get("wait_result") != 0
                or type(row.get("exit_time_100ns")) is not int or row["exit_time_100ns"] < process["creation_time_100ns"]
                or type(row.get("exit_code")) is not int):
            _fail("EXACT_PROCESS_TERMINATION_RECEIPT_INVALID")
    live = _EXECUTIONS.get(plan["component_digest"])
    if live is not None:
        actual = [_termination_observation(h, process) for h, process in zip(live["handles"], plan["processes"])]
        if actual != observations:
            _fail("RETAINED_PROCESS_OBJECT_OBSERVATION_DIFFERS")
    resources, roots, baseline = _current_resources(plan)
    if (payload.get("resources") != resources or payload.get("resource_roots") != roots
            or payload.get("baseline") != baseline):
        _fail("RETIRED_RESOURCE_CONTENT_OR_CONTAINMENT_CHANGED")
    payload["os_receipt_mac"] = supplied
    return {"original": plan["original"], "component_digest": plan["component_digest"],
            "producer_set_digest": p.digest(plan["processes"]), "termination_evidence_digest": p.digest(observations),
            "retired_resource_manifest_digest": p.digest(resources),
            "quarantined_output_manifest_digest": p.digest({"disposition": "preserved_in_place",
                "resource_roots": roots, "outputs": [r for r in resources if r["role"] == "output"]}),
            "os_receipt_digest": p.digest(payload), "disposition": "preserved_in_place"}


@_unavailable_boundary
def verify_separation(payload, intent, retirements):
    """Validate authenticated new-input derivation and physical namespace separation.

    payload.retirement_components contains {plan, receipt} for EVERY supplied
    RetirementClosure; caller closure objects alone never authorize separation.
    The workspace verifier supplies code-owned baseline/lineage facts, then this
    function checks current directory/file handles, aliases and all old outputs.
    """
    payload, intent_value = _clone(payload), _clone(intent)
    retirement_values = [_clone(r) for r in retirements]
    components = payload.get("retirement_components")
    if not isinstance(components, list) or len(components) != len(retirement_values) or not components:
        _fail("ALL_RETIREMENT_COMPONENTS_REQUIRED_FOR_SEPARATION")
    checked, plans = [], []
    for item, retirement in zip(components, retirement_values):
        result = verify_retirement_evidence(item["receipt"], item["plan"])
        for name in ("original", "producer_set_digest", "termination_evidence_digest",
                     "retired_resource_manifest_digest", "quarantined_output_manifest_digest"):
            if retirement.get(name) != result[name]:
                _fail("SEPARATION_RETIREMENT_REFERENCE_DIFFERS")
        plans.append(item["plan"])
        checked.append(result)
    authority = _authority(plans[0]["producer_manifest"], plans[0]["original"])
    facts = _clone(authority.workspace(_clone(payload), _clone(intent_value), _clone(retirement_values)))
    if facts.get("intent_digest") != p.digest(intent_value) or facts.get("baseline_digest") != intent_value.get("baseline_digest"):
        _fail("NEW_WORKSPACE_INTENT_OR_BASELINE_LINEAGE_UNVERIFIED")
    workspace_path = Path(facts["workspace_path"])
    existing = workspace_path.exists()
    workspace = _directory_record(workspace_path) if existing else _new_workspace(workspace_path)
    if not intent_value.get("workspace_generation_id") or not intent_value.get("run_id"):
        _fail("NEW_WORKSPACE_GENERATION_AND_RUN_REQUIRED")
    resources_expected = facts.get("resources")
    if not isinstance(resources_expected, list) or not 0 <= len(resources_expected) <= _MAX_FILES:
        _fail("FINITE_NEW_WORKSPACE_RESOURCE_SET_REQUIRED")
    resources = [_file_record(r) for r in resources_expected]
    if len({_key(r["identity"]) for r in resources}) != len(resources):
        _fail("NEW_WORKSPACE_RESOURCE_ALIAS")
    for plan in plans:
        if str(Path(facts["workspace_path"]).absolute()) != plan["new_workspace"]["path"]:
            _fail("WORKSPACE_NOT_APPROVED_EXACT_NEW_PATH")
        current_parent = _directory_record(Path(facts["workspace_path"]).parent)
        if not _same_file(current_parent, plan["new_workspace"]["parent"]):
            _fail("NEW_WORKSPACE_PARENT_IDENTITY_CHANGED")
        if facts["baseline_digest"] != plan.get("baseline_digest"):
            _fail("NEW_WORKSPACE_BASELINE_NOT_APPROVED")
        _disjoint({"parent": workspace if existing else workspace["parent"]},
                  plan["resource_roots"], plan["resources"], plan["baseline"])
        baseline_ids = {_key(plan["baseline"][key]["identity"]) for key in ("file", "provenance")}
        workspace_key = list(_key(workspace["identity"])) if existing else None
        for resource in resources:
            if (workspace_key is None or workspace_key not in resource["ancestor_ids"]) and _key(resource["identity"]) not in baseline_ids:
                _fail("INPUT_OUTSIDE_NEW_WORKSPACE_OR_AUTHENTICATED_BASELINE")
        unknown_outputs = {_key(r["identity"]) for r in plan["resources"] if r["role"] == "output"}
        if any(_key(row["identity"]) in unknown_outputs for row in resources):
            _fail("NEW_WORKSPACE_ALIASES_UNKNOWN_OUTPUT")
        if intent_value.get("runtime_epoch") == plan["original"]["original_runtime_epoch"]:
            _fail("RETIRED_RUNTIME_EPOCH_REUSED")
        if intent_value.get("run_id") == plan["original"].get("original_run_id"):
            _fail("RETIRED_RUN_ID_REUSED")
    return {"intent_digest": p.digest(intent_value), "workspace": workspace,
            "resources": resources, "baseline_digest": facts["baseline_digest"],
            "retirement_os_receipt_digests": [r["os_receipt_digest"] for r in checked]}
