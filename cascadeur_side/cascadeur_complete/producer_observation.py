"""Prospective process observations, never producer/resource closure evidence.

Only a new immutable signed outbox can start this chain. Native records require
the current loaded runtime and a private same-process claim. Old outcomes and
original receipt bytes are never amended, and no producer-closures are issued.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path
import stat
import threading
import time
import uuid

from . import incident_store as store
from .state_lock import file_lock

_PURPOSE = b"cascadeur-complete/future-producer-observation/v1\0"
_LOADED_AT = time.time()
_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_MAX_DOCUMENT = 256 * 1024**2
_MAX_EVENTS = 4096
_CLAIMS = {}
_LOCK = threading.RLock()
_LEGACY = {"ffb7fc8e-417c-454c-a669-48625a086eda", "fcf3352a-483c-4f9c-bc18-8b61a58822eb"}


class ObservationUnavailable(ValueError):
    pass


def _fail(reason):
    raise ObservationUnavailable(reason)


def _digest(value):
    return hashlib.sha256(store.canonical(value)).hexdigest()


def _safe_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            _fail("PRODUCER_OBSERVATION_REPARSE_PATH")
    return path


def _present(path):
    # Missing is optional; access failures and unsafe aliases are not absence.
    try:
        _safe_path(path).lstat()
        return True
    except FileNotFoundError:
        return False


def _read(path, maximum=_MAX_DOCUMENT):
    path = _safe_path(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            _fail("PRODUCER_OBSERVATION_FILE_OR_BUDGET")
        raw = stream.read(maximum + 1)
        after, named = os.fstat(stream.fileno()), _safe_path(path).lstat()
        identity = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns)
        # On Windows fstat ctime is metadata-change time, while path stat can
        # expose creation time. Compare ctime only through the SAME descriptor;
        # compare the actual volume/file ID, length and mtime across the name.
        if (len(raw) > maximum or len(raw) != before.st_size
                or identity(before) != identity(after) or before.st_ctime_ns != after.st_ctime_ns
                or identity(after) != identity(named) or not stat.S_ISREG(named.st_mode) or named.st_nlink != 1):
            _fail("PRODUCER_OBSERVATION_FILE_CHANGED")
        return raw


def _request(root, value):
    root = _safe_path(root)
    request = store.decode(value) if isinstance(value, bytes) else store.decode(store.canonical(value))
    rid = request.get("request_id")
    if not isinstance(rid, str) or str(uuid.UUID(rid)) != rid or rid in _LEGACY:
        _fail("PROSPECTIVE_CANONICAL_REQUEST_REQUIRED")
    secret = _read(root / "state" / "bridge.key", 4096)
    store.verify_original(request, secret)
    directory = root / "state" / "request_records" / rid
    raw = _read(directory / "request.json")
    if store.decode(raw) != request:
        _fail("PRODUCER_IMMUTABLE_OUTBOX_DIFFERS")
    if isinstance(value, bytes) and value != raw:
        _fail("PRODUCER_RAW_OUTBOX_DIFFERS")
    return root, request, secret, directory, raw


def _binding(request):
    return {"request_id": request["request_id"], "request_digest": _digest(request),
            "operation_digest": _digest(request["operations"]),
            "runtime_epoch": request.get("runtime_epoch"),
            "loaded_fingerprint": request.get("adapter_fingerprint"),
            "execution_context_digest": _digest(request.get("execution_context")),
            "host_instance_id": request.get("host_instance_id")}


def _directory(root, rid):
    return _safe_path(root / "state" / "producer-observations" / rid)


def _load(path, secret, request, kind):
    value = store.decode(_read(path))
    store.verify(value, secret, _PURPOSE)
    if (value.get("schema_version") != 1 or value.get("kind") != kind
            or value.get("scope_kind") != "observed_partial_v1"
            or value.get("closure_authority") != "none" or value.get("binding") != _binding(request)):
        _fail("PRODUCER_OBSERVATION_BINDING_DIFFERS")
    return value


def _publish(path, request, secret, kind, **facts):
    value = store.seal({"schema_version": 1, "kind": kind, "scope_kind": "observed_partial_v1",
        "closure_authority": "none", "binding": _binding(request), "observed_at_ns": time.time_ns(),
        "issuer_code_sha256": _CODE_SHA256,
        **facts}, secret, _PURPOSE)
    store.publish_new(path, value)
    return value


class _FileId(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_ulonglong), ("identifier", ctypes.c_ubyte * 16)]


class _FileInfo(ctypes.Structure):
    _fields_ = [("attributes", w.DWORD), ("created", w.FILETIME), ("accessed", w.FILETIME),
        ("written", w.FILETIME), ("volume", w.DWORD), ("size_high", w.DWORD),
        ("size_low", w.DWORD), ("links", w.DWORD), ("index_high", w.DWORD), ("index_low", w.DWORD)]


def capture_current_process_identity():
    """Query THIS process and hash its descriptor-pinned executable; no terminate access."""
    if os.name != "nt":
        _fail("WINDOWS_PROCESS_OBSERVATION_REQUIRED")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        "GetProcessTimes": ([w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME)], w.BOOL),
        "QueryFullProcessImageNameW": ([w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
        "CreateFileW": ([w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
        "GetFileInformationByHandleEx": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD], w.BOOL),
        "GetFileInformationByHandle": ([w.HANDLE, ctypes.POINTER(_FileInfo)], w.BOOL),
        "ReadFile": ([w.HANDLE, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID], w.BOOL),
        "CloseHandle": ([w.HANDLE], w.BOOL)}
    for name, (args, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = args, result
    def checked(value):
        if not value or value == ctypes.c_void_p(-1).value:
            raise ObservationUnavailable("PROCESS_IDENTITY_WINERROR:" + str(ctypes.get_last_error()))
        return value
    process = checked(kernel.OpenProcess(0x1000, False, os.getpid()))
    image_handle = None
    try:
        created, exited, system, user = (w.FILETIME() for _ in range(4))
        checked(kernel.GetProcessTimes(process, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)))
        image, length = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
        checked(kernel.QueryFullProcessImageNameW(process, 0, image, ctypes.byref(length)))
        image_path = _safe_path(image.value)
        image_handle = checked(kernel.CreateFileW(str(image_path), 0x80000000, 1, None, 3, 0x00200000, None))
        identity, before, after = _FileId(), _FileInfo(), _FileInfo()
        checked(kernel.GetFileInformationByHandleEx(image_handle, 18, ctypes.byref(identity), ctypes.sizeof(identity)))
        checked(kernel.GetFileInformationByHandle(image_handle, ctypes.byref(before)))
        size = (int(before.size_high) << 32) | int(before.size_low)
        if before.attributes & (0x400 | 0x10) or before.links != 1 or not 0 < size <= 1024**3:
            _fail("PROCESS_IMAGE_ALIAS_OR_RESOURCE_LIMIT")
        digest, total, buffer = hashlib.sha256(), 0, ctypes.create_string_buffer(1024**2)
        while total < size:
            read = w.DWORD()
            checked(kernel.ReadFile(image_handle, buffer, min(len(buffer), size-total), ctypes.byref(read), None))
            if not read.value:
                _fail("PROCESS_IMAGE_TRUNCATED")
            total += read.value
            digest.update(buffer.raw[:read.value])
        checked(kernel.GetFileInformationByHandle(image_handle, ctypes.byref(after)))
        if (before.attributes, before.links, before.size_high, before.size_low,
                before.written.dwHighDateTime, before.written.dwLowDateTime) != (
                after.attributes, after.links, after.size_high, after.size_low,
                after.written.dwHighDateTime, after.written.dwLowDateTime):
            _fail("PROCESS_IMAGE_CHANGED")
        return {"pid": os.getpid(), "creation_time_100ns": (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime),
            "image": {"path": os.path.normcase(str(image_path)), "volume": int(identity.volume),
                "file_id": bytes(identity.identifier).hex(), "size": size, "sha256": digest.hexdigest()}}
    finally:
        if image_handle is not None:
            kernel.CloseHandle(image_handle)
        kernel.CloseHandle(process)


def _lock(root, request):
    return file_lock(_directory(root, request["request_id"]) / ".writer.lock")


def record_host_dispatch(root, signed_request):
    """Call for a NEW signed outbox before queue publication, not while reconciling."""
    root, request, secret, outbox, raw = _request(root, signed_request)
    path = _directory(root, request["request_id"]) / "host-dispatch.json"
    if not path.exists():
        _assert_new_dispatch(root, request, outbox)
    with _lock(root, request):
        if path.exists():
            return _load(path, secret, request, "host_dispatch")
        _assert_new_dispatch(root, request, outbox)
        return _publish(path, request, secret, "host_dispatch", raw_request_sha256=hashlib.sha256(raw).hexdigest(),
                        host_dispatcher=capture_current_process_identity())


def _assert_new_dispatch(root, request, outbox):
    now = time.time()
    if (not _LOADED_AT <= request.get("created_at", 0) <= now < request.get("expires_at", 0)
            or any((outbox / "runtime_events").glob("*.json"))
            or any(root.joinpath("state", "requests").glob("*" + request["request_id"] + "*"))):
        _fail("RETROSPECTIVE_HOST_DISPATCH_FORBIDDEN")


def _native_runtime(request):
    from . import guarded_runtime as guards
    from .incident_admission import diagnostic_request
    diagnostic = (request.get("runtime_epoch") is None and request.get("adapter_fingerprint") is None
        and diagnostic_request(request))
    if not diagnostic and (request.get("runtime_epoch") != guards.RUNTIME_EPOCH
            or request.get("adapter_fingerprint") != guards.LOADED_FINGERPRINT):
        _fail("PRODUCER_CURRENT_NATIVE_RUNTIME_DIFFERS")
    return {"runtime_epoch": guards.RUNTIME_EPOCH, "loaded_fingerprint": guards.LOADED_FINGERPRINT}


def record_native_claim_if_prospective(root, request):
    """Old senders still receive an admission rejection, without retroactive observations.

    Absence of the prospective host record is NOT permission to write. Every
    effect must still call assert_native_first_effect, which requires a private
    claim. This branch only keeps pre-admission rejection/terminal reporting alive.
    """
    rid = request.get("request_id")
    if not isinstance(rid, str) or str(uuid.UUID(rid)) != rid:
        _fail("CANONICAL_REQUEST_ID_REQUIRED")
    if not (_directory(_safe_path(root), rid) / "host-dispatch.json").exists():
        return None
    return record_native_claim(root, request)


def record_native_claim(root, request):
    """Call immediately before the first claimed receipt; never on a previous attempt."""
    runtime = _native_runtime(request)
    root, request, secret, outbox, _ = _request(root, request)
    key = (str(root), request["request_id"], _digest(request))
    with _LOCK, _lock(root, request):
        directory = _directory(root, request["request_id"])
        host = _load(directory / "host-dispatch.json", secret, request, "host_dispatch")
        if key in _CLAIMS:
            return _load(directory / "native-claim.json", secret, request, "native_claim")
        if ((directory / "native-claim.json").exists() or any((outbox / "runtime_events").glob("*.json"))
                or time.time() >= request.get("expires_at", 0)):
            _fail("RETROSPECTIVE_OR_REPLAYED_NATIVE_CLAIM_FORBIDDEN")
        identity = capture_current_process_identity()
        value = _publish(directory / "native-claim.json", request, secret, "native_claim",
            host_dispatch_digest=_digest(host), native_process=identity, observed_native_runtime=runtime)
        _CLAIMS[key] = (identity, _digest(value))
        return value


def assert_native_first_effect(root, request):
    """Recheck the private live claim on EVERY guard; publish its first observation once."""
    _native_runtime(request)
    root, request, secret, _, _ = _request(root, request)
    key = (str(root), request["request_id"], _digest(request))
    with _LOCK, _lock(root, request):
        claim = _CLAIMS.get(key)
        if claim is None:
            _fail("PRIVATE_PROSPECTIVE_NATIVE_CLAIM_REQUIRED")
        directory = _directory(root, request["request_id"])
        value = _load(directory / "native-claim.json", secret, request, "native_claim")
        if _digest(value) != claim[1] or capture_current_process_identity() != claim[0]:
            _fail("NATIVE_PROCESS_OBSERVATION_CHANGED")
        path = directory / "first-effect.json"
        if path.exists():
            result = _load(path, secret, request, "native_first_effect")
            if result.get("native_claim_digest") != claim[1]:
                _fail("NATIVE_FIRST_EFFECT_CLAIM_DIFFERS")
            return result
        return _publish(path, request, secret, "native_first_effect", native_claim_digest=claim[1],
                        native_process=claim[0])


def _events(outbox, *, allow_empty=False):
    paths = sorted((outbox / "runtime_events").glob("*.json"))
    if len(paths) > _MAX_EVENTS or not paths and not allow_empty:
        _fail("BOUNDED_RUNTIME_EVENT_CHAIN_REQUIRED")
    result, remaining = [], _MAX_DOCUMENT
    for path in paths:
        if remaining <= 0:
            _fail("RUNTIME_EVENT_ARCHIVE_BUDGET")
        raw = _read(path, remaining)
        result.append(raw)
        remaining -= len(raw)
    return result


def _check_events(raw_events, request, secret, *, require_terminal=True):
    from .incident_admission import diagnostic_request
    if not isinstance(raw_events, (list, tuple)) or not 0 < len(raw_events) <= _MAX_EVENTS:
        _fail("BOUNDED_RUNTIME_EVENT_CHAIN_REQUIRED")
    previous, entries, total = None, [], 0
    for seq, raw in enumerate(raw_events, 1):
        if not isinstance(raw, bytes) or len(raw) > _MAX_DOCUMENT:
            _fail("RUNTIME_EVENT_BYTES_REQUIRED")
        total += len(raw)
        if total > _MAX_DOCUMENT:
            _fail("RUNTIME_EVENT_ARCHIVE_BUDGET")
        value = store.decode(raw)
        store.verify_original(value, secret)
        context = request.get("execution_context") or {}
        diagnostic = (request.get("runtime_epoch") is None and request.get("adapter_fingerprint") is None
            and diagnostic_request(request))
        if (previous is not None and previous.get("phase") == "terminal"
                or value.get("seq") != seq or value.get("request_id") != request["request_id"]
                or value.get("request_digest") != _digest(request)
                or value.get("operation_digest") != _digest(request["operations"])
                or value.get("session_id") != request.get("session_id")
                or value.get("host_instance_id", "") != request.get("host_instance_id", "")
                or any(value.get(k) != context.get(k) for k in ("run_id", "step_id", "attempt_id", "lease_epoch"))
                or not diagnostic and value.get("runtime_epoch") != request.get("runtime_epoch")
                or value.get("terminal_result") is not None and _digest(value["terminal_result"]) != value.get("result_digest")):
            _fail("ORIGINAL_RUNTIME_EVENT_CHAIN_DIFFERS")
        entries.append({"seq": seq, "raw_sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "payload_digest": _digest(value)})
        previous = value
    if ((require_terminal or previous.get("phase") == "terminal")
            and (previous.get("phase") != "terminal" or not isinstance(previous.get("terminal_result"), dict))):
        _fail("ACTUAL_TERMINAL_RECEIPT_REQUIRED")
    return entries, previous


def _publish_raw(path, raw):
    # Same no-replace, fsync publication primitive as incident_store.publish_new.
    path = _safe_path(path)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".pending")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _records(directory, request, secret, raw_request):
    records = {}
    for name, kind in (("host-dispatch", "host_dispatch"), ("native-claim", "native_claim"),
                       ("first-effect", "native_first_effect"), ("terminal-index", "terminal_archive")):
        path = directory / (name + ".json")
        if _present(path):
            records[kind] = _load(path, secret, request, kind)
    host, claim, first, index = (records.get(k) for k in
        ("host_dispatch", "native_claim", "native_first_effect", "terminal_archive"))
    if host and host.get("raw_request_sha256") != hashlib.sha256(raw_request).hexdigest():
        _fail("HOST_DISPATCH_RAW_REQUEST_DIFFERS")
    if claim:
        if not host or claim.get("host_dispatch_digest") != _digest(host):
            _fail("NATIVE_CLAIM_HOST_OBSERVATION_DIFFERS")
        runtime = claim.get("observed_native_runtime")
        if (not isinstance(runtime, dict) or set(runtime) != {"runtime_epoch", "loaded_fingerprint"}
                or not isinstance(runtime["runtime_epoch"], str) or not runtime["runtime_epoch"]
                or not isinstance(runtime["loaded_fingerprint"], str) or not runtime["loaded_fingerprint"]):
            _fail("NATIVE_CLAIM_RUNTIME_OBSERVATION_REQUIRED")
        from .incident_admission import diagnostic_request
        diagnostic = (request.get("runtime_epoch") is None and request.get("adapter_fingerprint") is None
            and diagnostic_request(request))
        if not diagnostic and runtime != {"runtime_epoch": request.get("runtime_epoch"),
                "loaded_fingerprint": request.get("adapter_fingerprint")}:
            _fail("NATIVE_CLAIM_RUNTIME_OBSERVATION_DIFFERS")
    if first and (not claim or first.get("native_claim_digest") != _digest(claim)
            or first.get("native_process") != claim.get("native_process")):
        _fail("NATIVE_FIRST_EFFECT_CLAIM_DIFFERS")
    if index and (not host or not claim or index.get("host_dispatch_digest") != _digest(host)
            or index.get("native_claim_digest") != _digest(claim)):
        _fail("TERMINAL_OBSERVATION_CHAIN_DIFFERS")
    return records


def _terminal_facts(actual, request, secret, host, claim):
    entries, terminal = _check_events(actual, request, secret)
    if any(store.decode(raw).get("runtime_epoch") != claim["observed_native_runtime"]["runtime_epoch"] for raw in actual):
        _fail("TERMINAL_NATIVE_OBSERVATION_EPOCH_DIFFERS")
    return {"host_dispatch_digest": _digest(host), "native_claim_digest": _digest(claim),
        "events": entries, "terminal_payload_digest": _digest(terminal),
        "terminal_bytes_sha256": entries[-1]["raw_sha256"], "outcome": terminal["outcome"]}


def _check_archive_prefix(directory, actual):
    paths = sorted(_safe_path(directory / "terminal-archive").glob("*.json"))
    if len(paths) > len(actual):
        _fail("RETAINED_RECEIPT_PREFIX_DIFFERS")
    for seq, (path, raw) in enumerate(zip(paths, actual), 1):
        if path.name != str(seq).zfill(12) + ".json" or _read(path, len(raw)) != raw:
            _fail("RETAINED_RECEIPT_BYTES_DIFFER")
    return len(paths)


def _archive_locked(root, request, secret, outbox, raw_request, ordered_event_bytes=None, *, allow_pending=False):
    directory = _directory(root, request["request_id"])
    records = _records(directory, request, secret, raw_request)
    host, claim = (records.get(k) for k in ("host_dispatch", "native_claim"))
    if not host or not claim:
        if allow_pending:
            return None
        _fail("PROSPECTIVE_HOST_AND_NATIVE_CLAIM_REQUIRED")
    actual = _events(outbox, allow_empty=allow_pending)
    if ordered_event_bytes is not None and list(ordered_event_bytes) != actual:
        _fail("SUPPLIED_RECEIPTS_DIFFER_FROM_ACTUAL_OUTBOX")
    if not actual:
        if records.get("terminal_archive") or _check_archive_prefix(directory, actual):
            _fail("RETAINED_TERMINAL_WITHOUT_ORIGINAL")
        return None
    _, last = _check_events(actual, request, secret, require_terminal=not allow_pending)
    if allow_pending and last.get("phase") != "terminal":
        if records.get("terminal_archive") or _check_archive_prefix(directory, []):
            _fail("RETAINED_TERMINAL_WITHOUT_ORIGINAL")
        return None
    facts = _terminal_facts(actual, request, secret, host, claim)
    prefix_length = _check_archive_prefix(directory, actual)
    index = records.get("terminal_archive")
    if index:
        if any(index.get(k) != v for k, v in facts.items()) or prefix_length != len(actual):
            _fail("RETAINED_TERMINAL_ARCHIVE_DIFFERS")
        return index
    for seq, raw in enumerate(actual[prefix_length:], prefix_length + 1):
        _publish_raw(directory / "terminal-archive" / (str(seq).zfill(12) + ".json"), raw)
    return _publish(directory / "terminal-index.json", request, secret, "terminal_archive", **facts)


def _existing_request(root, request_id):
    rid = str(uuid.UUID(request_id))
    if rid != request_id:
        _fail("CANONICAL_REQUEST_ID_REQUIRED")
    request = store.decode(_read(Path(root) / "state" / "request_records" / rid / "request.json"))
    if request.get("request_id") != rid:
        _fail("PRODUCER_REQUEST_DIRECTORY_DIFFERS")
    return _request(root, request)


def archive_terminal(root, request_id, ordered_event_bytes=None):
    """Archive an already sealed terminal without calling or reclassifying native work."""
    root, request, secret, outbox, raw_request = _existing_request(root, request_id)
    with _lock(root, request):
        return _archive_locked(root, request, secret, outbox, raw_request, ordered_event_bytes)


def reconcile_terminal_if_prospective(root, request_id):
    """Finish ONLY a preexisting prospective terminal archive, including after restart.

    None means legacy/absent prospective chain or no terminal yet. No dispatch,
    process query, SDK call, private claim or first-effect record is created.
    Existing malformed/orphan records and archive prefixes fail visibly.
    """
    rid = str(uuid.UUID(request_id))
    if rid != request_id:
        _fail("CANONICAL_REQUEST_ID_REQUIRED")
    if rid in _LEGACY:
        return None
    directory = _directory(_safe_path(root), rid)
    # Avoid creating even a lock for an entirely unobserved old request.
    if not _present(directory):
        return None
    root, request, secret, outbox, raw_request = _existing_request(root, rid)
    # Validate present records before deciding whether there is enough authority
    # to take the writer lock; this never creates a missing prospective record.
    records = _records(directory, request, secret, raw_request)
    if not records.get("host_dispatch") or not records.get("native_claim"):
        if _check_archive_prefix(directory, []):
            _fail("RETAINED_TERMINAL_WITHOUT_PROSPECTIVE_CHAIN")
        return None
    with _lock(root, request):
        return _archive_locked(root, request, secret, outbox, raw_request, allow_pending=True)


def read_producer_observation(root, request_id):
    """Observation only. Missing prospective records stay missing, including after restart."""
    root, request, secret, outbox, raw_request = _existing_request(root, request_id)
    directory = _directory(root, request["request_id"])
    records = _records(directory, request, secret, raw_request)
    index = records.get("terminal_archive")
    if index:
        actual = _events(outbox)
        facts = _terminal_facts(actual, request, secret, records["host_dispatch"], records["native_claim"])
        if (any(index.get(k) != v for k, v in facts.items())
                or _check_archive_prefix(directory, actual) != len(actual)):
            _fail("RETAINED_TERMINAL_ARCHIVE_DIFFERS")
    return {"scope_kind": "observed_partial_v1", "closure_authority": "none", "records": records}
