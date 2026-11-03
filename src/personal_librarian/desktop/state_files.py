"""Handle-pinned application state on fixed local Windows NTFS.

The approved root is lexical and never replaced by a resolved descendant.
Directory handles prevent relocation throughout the operation. Final
files are opened without following reparse points and checked before reading.
This is not a defence against an administrator, kernel driver or volume remount.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import threading
import uuid

from personal_librarian.catalogue.maintenance import require_local_ntfs
from personal_librarian.catalogue.errors import ProductionError
from personal_librarian.safety import PathIntent, PathSafetyPolicy, windows_path_kind

_state_io_lock = threading.RLock()


class _Directory:
    def __init__(self, k, handle):
        self.k, self.handle = k, handle

    def close(self):
        if self.handle is not None:
            self.k.CloseHandle(self.handle)
            self.handle = None

    def publication_pin(self, path):
        # Rename needs a writable parent open internally. Keep its name pinned
        # while relaxing write sharing only AFTER our exclusive temp object
        # makes this directory nonempty. NTFS refuses junction/symlink tags on
        # a nonempty directory. All higher ancestors retain strong handles.
        replacement = _open(self.k, path, 0x80, 1, 3, directory=True)
        self.close()
        self.handle = replacement


class _Info(ctypes.Structure):
    _fields_ = [('attributes', W.DWORD), ('created', W.FILETIME),
                ('accessed', W.FILETIME), ('written', W.FILETIME),
                ('volume', W.DWORD), ('size_high', W.DWORD), ('size_low', W.DWORD),
                ('links', W.DWORD), ('index_high', W.DWORD), ('index_low', W.DWORD)]


def _kernel():
    if os.name != 'nt':
        raise OSError('Application state requires fixed local Windows NTFS.')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
    k.CreateFileW.restype = W.HANDLE
    k.CloseHandle.argtypes = [W.HANDLE]
    k.CloseHandle.restype = W.BOOL
    k.GetFileInformationByHandle.argtypes = [W.HANDLE, ctypes.POINTER(_Info)]
    k.GetFileInformationByHandle.restype = W.BOOL
    k.SetFileInformationByHandle.argtypes = [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD]
    k.SetFileInformationByHandle.restype = W.BOOL
    return k


def _open(k, path, access, share, disposition, directory=False):
    handle = k.CreateFileW(str(path), access, share, None, disposition,
                           0x00200000 | (0x02000000 if directory else 0x80), None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = _Info()
        if not k.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if (info.attributes & 0x400 or bool(info.attributes & 0x10) != directory
                or not (info.index_high or info.index_low)
                or (not directory and info.links != 1)):
            raise OSError('State path is not an ordinary single-link file/directory.')
        return handle
    except BaseException:
        k.CloseHandle(handle)
        raise


def _rename(k, handle, destination, replace, parent_handle):
    # Native FILE_RENAME_INFORMATION: BOOLEAN union, padding, then HANDLE.
    encoded = str(destination).encode('utf-16-le')
    class Rename(ctypes.Structure):
        _fields_ = [('replace', W.DWORD), ('root', W.HANDLE),
                    ('length', W.DWORD), ('name', W.WCHAR * (len(encoded)//2 + 1))]
    info = Rename()
    info.replace = bool(replace)
    info.root = parent_handle
    info.length = len(encoded)
    ctypes.memmove(ctypes.addressof(info) + Rename.name.offset, encoded, len(encoded))
    # The Win32 wrapper rejects a relative RootDirectory on some supported
    # builds. The native operation binds the destination to our pinned handle.
    class IoStatus(ctypes.Structure):
        _fields_ = [('status', ctypes.c_void_p), ('information', ctypes.c_size_t)]
    native = ctypes.WinDLL('ntdll')
    rename = native.NtSetInformationFile
    rename.argtypes = [W.HANDLE, ctypes.POINTER(IoStatus), W.LPVOID, W.ULONG, ctypes.c_int]
    rename.restype = ctypes.c_long
    status = rename(handle, ctypes.byref(IoStatus()), ctypes.byref(info), ctypes.sizeof(info), 10)
    if status != 0:
        convert = native.RtlNtStatusToDosError
        convert.argtypes = [ctypes.c_long]
        convert.restype = W.ULONG
        raise ctypes.WinError(convert(status))


def _discard(k, handle):
    delete = W.BOOLEAN(1)
    if not k.SetFileInformationByHandle(handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)):
        raise ctypes.WinError(ctypes.get_last_error())


class StateFiles:
    def __init__(self, root, policy=None):
        self.policy = policy or PathSafetyPolicy()
        result = self.policy.check_path(root, intent=PathIntent.WRITE)
        if not result.allowed or windows_path_kind(str(root)) != 'drive-absolute':
            raise OSError('Application state requires an approved absolute local root.')
        self.root = Path(root)
        if '..' in self.root.parts:
            raise OSError('State root traversal is unsupported.')

    @contextmanager
    def _parent(self, path, create=False):
        path = Path(path)
        checked = self.policy.check_path(path, intent=PathIntent.WRITE if create else PathIntent.READ)
        if not checked.allowed or '..' in path.parts:
            raise OSError('Unsafe application state path.')
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise OSError('State path is outside its original approved root.') from exc
        try:
            require_local_ntfs(self.root)
        except ProductionError as exc:
            raise OSError(str(exc)) from exc
        k = _kernel()
        with _state_io_lock, ExitStack() as held:
            for directory in reversed(path.parent.parents):
                self._pin(k, held, directory, create)
            parent_handle = self._pin(k, held, path.parent, create)
            yield k, parent_handle

    def _pin(self, k, held, directory, create):
        try:
            handle = _open(k, directory, 0x80000000, 1, 3, directory=True)
        except FileNotFoundError:
            if not create or (directory != self.root and self.root not in directory.parents):
                raise
            try:
                directory.mkdir()
            except FileExistsError:
                pass  # Another generator may have created this directory; pin and inspect it.
            handle = _open(k, directory, 0x80000000, 1, 3, directory=True)
        directory = _Directory(k, handle)
        held.callback(directory.close)
        return directory

    def read(self, path, *, limit=4*1024*1024):
        import msvcrt
        with self._parent(path) as (k, _):
            handle = _open(k, path, 0x80000000, 1, 3)
            try:
                fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            except BaseException:
                k.CloseHandle(handle)
                raise
            with os.fdopen(fd, 'rb') as stream:
                data = stream.read(limit+1)
                if len(data) > limit:
                    raise OSError('State file exceeds its bounded read size.')
                return data

    def publish(self, path, data, *, replace=False):
        """Publish only complete bytes. Cache races never replace the winner.

        Preferences intentionally use last-completed-save wins, replacing the
        directory entry rather than writing through an existing file identity.
        """
        import msvcrt
        path = Path(path)
        with self._parent(path, create=True) as (k, parent_handle):
            # Reject existing redirected destinations before publication. A
            # concurrent directory-entry replacement cannot redirect rename I/O
            # into its target: all ancestors stay pinned and the source is a handle.
            try:
                existing = _open(k, path, 0x80, 1|2|4, 3)
            except FileNotFoundError:
                pass
            else:
                k.CloseHandle(existing)
                if not replace:
                    return False
            temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
            handle = _open(k, temporary, 0x80000000|0x40000000|0x10000, 0, 1)
            try:
                fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
            except BaseException:
                k.CloseHandle(handle)
                raise
            published = False
            rename_started = False
            with os.fdopen(fd, 'w+b') as stream:
                try:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    parent_handle.publication_pin(path.parent)
                    try:
                        rename_started = True
                        _rename(k, handle, path.name, replace, parent_handle.handle)
                    except OSError as exc:
                        if not replace and exc.winerror in {80, 183}:
                            _discard(k, handle)
                            return False
                        raise
                    published = True
                    return True
                finally:
                    if not published and not rename_started:
                        _discard(k, handle)  # Delete only our open temporary object, never a path alias.
