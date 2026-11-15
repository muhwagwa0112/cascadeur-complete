"""Descriptor-bound intake for retained export and consumer JSON files."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

# Matches the existing maximum TargetImportSettings.max_report_bytes. Retained
# canonical captures/records use this ceiling; raw worker reports additionally
# retain their profile's (possibly smaller) explicit byte budget.
MAX_EXPORT_JSON_BYTES = 256 * 1024**2


def _regular(info):
    return (stat.S_ISREG(info.st_mode)
            and not (getattr(info, 'st_file_attributes', 0)
                     & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)))


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_bounded_bytes(path, max_bytes=MAX_EXPORT_JSON_BYTES):
    """Reject oversize/nonregular/changed files before returning bounded bytes.

    Read through the checked descriptor in finite chunks, including at most one
    byte beyond the budget to detect growth. Never trust a pathname stat followed
    by an unrestricted read. This detects observed changes; it does not replace
    the caller's cryptographic content/provenance checks.
    """
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_EXPORT_JSON_BYTES:
        raise ValueError('EXPORT_JSON_BUDGET_INVALID')
    path = Path(path)
    before = path.lstat()
    if not _regular(before):
        raise ValueError('EXPORT_JSON_REGULAR_FILE_REQUIRED')
    if before.st_size > max_bytes:
        raise ValueError('EXPORT_JSON_RESOURCE_LIMIT')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    flags |= getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOINHERIT', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if not _regular(opened) or _identity(opened) != _identity(before):
            raise ValueError('EXPORT_JSON_CHANGED')
        if opened.st_size > max_bytes:
            raise ValueError('EXPORT_JSON_RESOURCE_LIMIT')
        payload = bytearray()
        while True:
            block = stream.read(min(1024**2, max_bytes + 1 - len(payload)))
            if not block:
                break
            payload.extend(block)
            if len(payload) > max_bytes:
                raise ValueError('EXPORT_JSON_RESOURCE_LIMIT')
        after, named = os.fstat(stream.fileno()), path.lstat()
        if (not _regular(named) or len(payload) != opened.st_size
                or _identity(opened) != _identity(after)
                or _identity(after) != _identity(named)):
            raise ValueError('EXPORT_JSON_CHANGED')
    return payload


def read_bounded_json(path, max_bytes=MAX_EXPORT_JSON_BYTES):
    payload = read_bounded_bytes(path, max_bytes)
    try:
        return json.loads(payload.decode('utf-8'))
    except RecursionError as error:
        raise ValueError('EXPORT_JSON_NESTING_UNSUPPORTED') from error
