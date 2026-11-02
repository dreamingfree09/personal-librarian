"""Windows catalogue maintenance exclusion; abandoned leases require offline review."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import ntpath
import os
from pathlib import Path
import stat
import threading
import uuid

from personal_librarian.catalogue.errors import ProductionError

LEASE_NAME = '.catalogue-maintenance.json'
_owner = threading.local()


def require_local_ntfs(path: Path) -> None:
    """Maintenance is supported only on fixed local NTFS, with no reparse hops."""
    raw = str(path)
    drive, tail = ntpath.splitdrive(raw)
    if os.name != 'nt' or len(drive) != 2 or drive[1] != ':' or not tail.startswith('\\'):
        raise ProductionError('Maintenance requires a fixed local NTFS path; UNC/network paths are unsupported.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    drive_type = kernel.GetDriveTypeW
    drive_type.argtypes = [wintypes.LPCWSTR]
    drive_type.restype = wintypes.UINT
    root = drive + '\\'
    if drive_type(root) != 3:  # DRIVE_FIXED; reject mapped network drives before stat.
        raise ProductionError('Maintenance requires a fixed local NTFS volume; network/removable/unknown drives are unsupported.')
    # Reject mounted folders, symlinks and junctions rather than infer the
    # semantics of a different target volume through an apparently local path.
    for component in reversed((path, *path.parents)):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ProductionError('Maintenance does not support reparse paths.')
    volume = kernel.GetVolumeInformationW
    volume.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                       ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                       ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    volume.restype = wintypes.BOOL
    filesystem = ctypes.create_unicode_buffer(64)
    if not volume(root, None, 0, None, None, None, filesystem, len(filesystem)):
        raise ProductionError('Cannot establish the maintenance filesystem type.')
    if filesystem.value.upper() != 'NTFS':
        raise ProductionError('Maintenance supports fixed local NTFS only.')


def file_identity(value) -> tuple[int, int]:
    """Python 3.13 Windows device + nonzero file index, never content identity."""
    info = value.lstat() if isinstance(value, Path) else os.fstat(value.fileno())
    if (not stat.S_ISREG(info.st_mode) or not info.st_ino
            or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ProductionError('Cannot establish a regular non-reparse maintenance file identity.')
    return info.st_dev, info.st_ino


def identity_at(path: Path) -> tuple[int, int] | None:
    try:
        return file_identity(path)
    except FileNotFoundError:
        return None


def require_catalogue_available(path: Path) -> None:
    lease = path.parent / LEASE_NAME
    if lease.exists() and getattr(_owner, 'lease', None) != lease:
        raise ProductionError('Catalogue maintenance is active or interrupted; offline review is required.')


@contextmanager
def catalogue_maintenance(directory: Path, operation: str):
    if os.name != 'nt':
        raise ProductionError('Catalogue publication/recovery requires the Windows maintenance contract.')
    require_local_ntfs(directory)
    lease = directory / LEASE_NAME
    state = {'operation': operation, 'attempt_id': str(uuid.uuid4()), 'pid': os.getpid(), 'retain': False}
    try:
        with lease.open('x', encoding='utf-8') as stream:
            # Lease existence is the durable block, not a stale copy of the
            # in-process cleanup flag. Only verified terminal states remove it.
            json.dump({key: value for key, value in state.items() if key != 'retain'}, stream, sort_keys=True)
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
