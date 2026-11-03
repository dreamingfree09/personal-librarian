"""Current, bounded Windows physical-disk measurement; no drive enumeration."""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
import ntpath
import os
from pathlib import Path
import struct

from personal_librarian.catalogue.maintenance import require_local_ntfs
from personal_librarian.catalogue.errors import ProductionError
from personal_librarian.safety import PathIntent, PathSafetyPolicy


def _query(device: str, control: int, data: bytes = b'', size: int = 4096) -> bytes:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR,W.DWORD,W.DWORD,W.LPVOID,W.DWORD,W.DWORD,W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.DeviceIoControl.argtypes = [W.HANDLE,W.DWORD,W.LPVOID,W.DWORD,W.LPVOID,W.DWORD,ctypes.POINTER(W.DWORD),W.LPVOID]
    kernel.DeviceIoControl.restype = W.BOOL
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.CreateFileW(device,0,7,None,3,0,None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        output = ctypes.create_string_buffer(size)
        incoming = ctypes.create_string_buffer(data) if data else None
        returned = W.DWORD()
        if not kernel.DeviceIoControl(handle,control,incoming,len(data),output,size,ctypes.byref(returned),None):
            raise ctypes.WinError(ctypes.get_last_error())
        if returned.value > size:
            raise OSError('Invalid storage response size.')
        return output.raw[:returned.value]
    finally:
        kernel.CloseHandle(handle)


def _single_disk(extents: bytes) -> int | None:
    # Native VOLUME_DISK_EXTENTS: DWORD count, alignment, DISK_EXTENT.
    if len(extents) < 32 or struct.unpack_from('<I',extents)[0] != 1:
        return None
    number, start, length = struct.unpack_from('<I4xqq',extents,8)
    return number if number < 0xFFFFFFFF and start >= 0 and length > 0 else None


def _supported_bus(descriptor: bytes) -> bool:
    if len(descriptor) < 36:
        return False
    version, size = struct.unpack_from('<II',descriptor)
    if version < 36 or size > len(descriptor) or size < 36:
        return False
    # Conservative directly attached transports: ATA, USB, SATA, NVMe.
    # Unknown, RAID, SCSI/SAS, network, virtual, file-backed and Storage Spaces
    # require a topology-specific proof and are intentionally not inferred here.
    return descriptor[8] == 0 and struct.unpack_from('<I',descriptor,28)[0] in {3,7,11,17}


def physical_device_identity(path: Path) -> str | None:
    """Identity is valid for this evaluation only, never a permanent disk UUID."""
    if os.name != 'nt' or not PathSafetyPolicy().check_path(path,intent=PathIntent.READ).allowed:
        return None
    try:
        require_local_ntfs(path)
        if not path.exists():
            return None
        drive, _ = ntpath.splitdrive(str(path))
        disk = _single_disk(_query('\\\\.\\'+drive,0x00560000,size=32))
        if disk is None:
            return None
        descriptor = _query('\\\\.\\PhysicalDrive'+str(disk),0x002D1400,struct.pack('<III',0,0,0))
        if not _supported_bus(descriptor):
            return None
        return f'windows-physical-disk:{disk}'
    except (OSError, ValueError, ProductionError, struct.error):
        return None
