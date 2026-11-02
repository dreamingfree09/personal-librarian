"""Windows catalogue maintenance exclusion; abandoned leases require offline review."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import threading
import uuid

from personal_librarian.catalogue.errors import ProductionError

LEASE_NAME = '.catalogue-maintenance.json'
_owner = threading.local()


def require_catalogue_available(path: Path) -> None:
    lease = path.parent / LEASE_NAME
    if lease.exists() and getattr(_owner, 'lease', None) != lease:
        raise ProductionError('Catalogue maintenance is active or interrupted; offline review is required.')


@contextmanager
def catalogue_maintenance(directory: Path, operation: str):
    if os.name != 'nt':
        raise ProductionError('Catalogue publication/recovery requires the Windows maintenance contract.')
    lease = directory / LEASE_NAME
    state = {'operation': operation, 'attempt_id': str(uuid.uuid4()), 'pid': os.getpid(), 'retain': False}
    try:
        with lease.open('x', encoding='utf-8') as stream:
            json.dump(state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ProductionError('Catalogue maintenance lease already exists; do not steal an active/interrupted lease.') from exc
    previous = getattr(_owner, 'lease', None)
    _owner.lease = lease
    try:
        yield state
    finally:
        _owner.lease = previous
        if not state['retain']:
            lease.unlink()


def publish_no_replace(source: Path, destination: Path) -> None:
    """Windows MoveFileEx without REPLACE_EXISTING; no exists-then-replace race."""
    if os.name != 'nt':
        raise ProductionError('Atomic no-replace publication requires Windows.')
    os.rename(source, destination)


@contextmanager
def exclusive_file(path: Path):
    """Deny file reads/writes while allowing our same-volume rename.

    DELETE access rejects existing SQLite handles (which do not share delete).
    FILE_SHARE_DELETE alone prevents subsequent readers/writers, including raw
    sqlite3 clients. The returned descriptor remains bound across a rename.
    """
    import msvcrt

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000 | 0x00010000, 0x00000004, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ProductionError(f'Exclusive maintenance access refused: {ctypes.WinError(ctypes.get_last_error())}')
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, 'rb') as stream:
        yield stream


def stream_sha256(stream) -> str:
    stream.seek(0)
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()
