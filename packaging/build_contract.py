"""Controlled PyInstaller input/output contract; no distribution-derived allowlist."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import base64
import importlib.metadata
import re
import zipfile
import os
from pathlib import Path, PurePosixPath
import stat

SCHEMA = 'controlled-pyinstaller-v1'
# Resource names alone are never permission to collect arbitrary application data.
# These exceptions correspond to the reviewed spec's actual runtime requirements.
FORBIDDEN_COMPONENTS = {'backup', 'backups', 'catalogue', 'inventories', 'logs',
                        'credentials', 'secrets', '.ssh', '.aws'}
# Observed in the pinned setuptools 80.9.0 wheel's collected runtime graph.
# Every byte, including the nested RECORD, must match the outer wheel RECORD.
SETUPTOOLS_RESOURCES = {
    '_internal/setuptools/_vendor/importlib_metadata-8.0.0.dist-info/' + name
    for name in ('installer', 'license', 'metadata', 'record', 'requested', 'wheel', 'top_level.txt')
} | {'_internal/setuptools/_vendor/jaraco/text/lorem ipsum.txt'}


def require_resource_name(name: str) -> str:
    relative_name(name)
    lowered = name.casefold()
    parts = lowered.split('/')
    if any(part.startswith('.env') or part in FORBIDDEN_COMPONENTS for part in parts):
        raise ValueError('Private/state resource is forbidden.')
    if lowered == 'personallibrarian.exe':
        return 'application-executable'
    if lowered.startswith('_internal/') and Path(lowered).suffix in {'.dll', '.pyd'}:
        return 'runtime-binary'
    if lowered == '_internal/base_library.zip':
        return 'python-base-library'
    if re.fullmatch(r'_internal/numpy-[^/]+\.dist-info/requested', lowered):
        return 'empty-installer-marker'
    if lowered in SETUPTOOLS_RESOURCES:
        return 'setuptools-vendored-resource'
    if re.fullmatch(r'_internal/pyside6/translations/(?:qt|qtbase)(?:_[a-z0-9]+)+\.qm', lowered):
        return 'qt-translation'
    if re.fullmatch(r'_internal/(numpy|pillow|pyside6|pyside6_addons|pyside6_essentials|shiboken6)-[^/]+\.dist-info/licenses/(?:[^/]+/)*(?:[a-z0-9_-]+_)?(?:license|copying)(?:\.(?:txt|md|rst))?', lowered):
        return 'dependency-license'
    if re.fullmatch(r'_internal/(numpy|pillow|pyside6|pyside6_addons|pyside6_essentials|shiboken6)-[^/]+\.dist-info/(?:delvewheel|installer|metadata|record|wheel|entry_points\.txt)', lowered):
        return 'dependency-metadata'
    raise ValueError('Resource lacks an explicit reviewed runtime approval.')


def verify_resource_origin(name: str, source: Path, *, workpath: Path | None, records=None) -> None:
    """Bind narrowly approved data to generated stdlib or installed wheel RECORD.

    This is a trusted-build check, not authentication of an attacker-supplied
    contract. No broad image/document/archive/config resource exception exists.
    """
    rule = require_resource_name(name)
    if rule in {'application-executable', 'runtime-binary'}:
        return
    source = safe_path(source)
    if rule == 'empty-installer-marker' and file_record(source)['size'] != 0:
        raise ValueError('Installer REQUESTED marker must be empty.')
    if rule == 'python-base-library':
        if workpath is None or source != safe_path(workpath / 'base_library.zip'):
            raise ValueError('Base library must be the controlled generated input.')
        with read_regular(source) as stream, zipfile.ZipFile(stream) as archive:
            names = archive.namelist()
            if not names or len({n.casefold() for n in names}) != len(names):
                raise ValueError('Invalid generated Python library.')
            for member in names:
                relative_name(member)
                if not member.casefold().endswith('.pyc'):
                    raise ValueError('Only generated Python modules belong in the base library.')
        return
    expected = '/'.join(name.split('/')[1:])
    # Wheel RECORD binds both destination and source, not just a file extension
    # or a convenient runtime directory. The selected environment is trusted.
    if records is None:
        records = [(dist, tuple(dist.files or ())) for dist in importlib.metadata.distributions()]
    for distribution, items in records:
        if rule == 'setuptools-vendored-resource' and (
            distribution.metadata['Name'].casefold() != 'setuptools'
            or distribution.version != '80.9.0'
        ):
            continue
        for item in items:
            if str(item).replace('\\', '/').casefold() != expected.casefold():
                continue
            if safe_path(Path(distribution.locate_file(item))) != source:
                continue
            # RECORD is the installed metadata authority and has no self-hash.
            # Only its exact distribution-located file receives this exception.
            if rule == 'dependency-metadata' and source.name.casefold() == 'record' and item.hash is None:
                return
            if item.hash is None or item.hash.mode != 'sha256':
                continue
            expected_hash = base64.urlsafe_b64decode(item.hash.value + '===').hex()
            if file_record(source)['sha256'] == expected_hash:
                return
    raise ValueError('Runtime data is not bound to its installed dependency RECORD.')



def safe_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    if os.name == 'nt' and (len(path.drive) != 2 or path.drive[1] != ':'):
        raise ValueError('Only local drive paths are supported for packaging.')
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked/reparse packaging paths are forbidden.')
    return path


def relative_name(name: str) -> str:
    p = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or p.is_absolute()
            or any(x in ('', '.', '..') or x.endswith((' ', '.')) for x in name.split('/'))
            or any(x.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(10)),*(f'LPT{i}' for i in range(10))} for x in p.parts)):
        raise ValueError('Invalid portable artifact path.')
    return name


@contextmanager
def read_regular(path: Path):
    """Open without following a final link; verify actual Windows handle path before reading."""
    path = safe_path(path)
    if os.name == 'nt':
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = [wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        handle = create(str(path),0x80000000,1,None,3,0x00200000,None)  # OPEN_REPARSE_POINT; share read only
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), 'Cannot lock packaging input for read')
        close = kernel.CloseHandle; close.argtypes=[wintypes.HANDLE]
        try:
            final = kernel.GetFinalPathNameByHandleW
            final.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
            final.restype=wintypes.DWORD
            buffer=ctypes.create_unicode_buffer(32768)
            length=final(handle,buffer,len(buffer),0)
            if not length or length >= len(buffer):
                raise ValueError('Cannot establish the opened artifact path.')
            # GetFinalPathName returns long names; Windows TEMP may use 8.3
            # aliases. Expand names only (not junction/symlink resolution), then
            # retain both physical containment and handle/file identity checks.
            expand = kernel.GetLongPathNameW
            expand.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            expand.restype = wintypes.DWORD
            expected = ctypes.create_unicode_buffer(32768)
            expanded = expand(str(path), expected, len(expected))
            if not expanded or expanded >= len(expected):
                raise ValueError('Cannot establish the long artifact path.')
            safe_path(Path(expected.value))
            if os.path.normcase(buffer.value.removeprefix('\\\\?\\')) != os.path.normcase(expected.value):
                raise ValueError('Opened artifact escaped its physical path.')
            descriptor=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
            handle=None
        finally:
            if handle is not None: close(handle)
        stream=os.fdopen(descriptor,'rb')
    else:
        stream=os.fdopen(os.open(path,os.O_RDONLY | os.O_NOFOLLOW),'rb')
    with stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Artifact must be a regular non-linked file.')
        safe_path(path)
        current=path.lstat()
        if (info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino):
            raise ValueError('Artifact identity changed during open.')
        yield stream


def file_record(path: Path) -> dict:
    with read_regular(path) as stream:
        digest=hashlib.sha256(); size=0
        while chunk:=stream.read(1024*1024):
            digest.update(chunk);size+=len(chunk)
        return {'size':size,'sha256':digest.hexdigest()}


def seal(value: dict) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_contract(contract: dict) -> dict:
    if set(contract) != {'schema','provenance','files','fingerprint'} or contract['schema'] != SCHEMA:
        raise ValueError('Unknown build contract.')
    material={key:value for key,value in contract.items() if key!='fingerprint'}
    if contract['fingerprint']!=seal(material): raise ValueError('Build contract fingerprint mismatch.')
    files=contract['files']
    if not files or 'PersonalLibrarian.exe' not in files: raise ValueError('Executable missing from contract.')
    folded=set()
    for name, record in files.items():
        relative_name(name)
        require_resource_name(name)
        if name.casefold() in folded: raise ValueError('Case-colliding artifact paths.')
        folded.add(name.casefold())
        if set(record)!={'size','sha256'} or type(record['size']) is not int or record['size']<0 or len(record['sha256'])!=64 or any(c not in '0123456789abcdef' for c in record['sha256']):
            raise ValueError('Invalid artifact identity.')
    provenance=contract['provenance']
    if provenance.get('validation') != 'NOT_PERFORMED': raise ValueError('Build cannot claim package validation.')
    return files


def distribution_files(distribution: Path, contract: dict) -> list[Path]:
    expected=validate_contract(contract)
    distribution=safe_path(distribution)
    if not distribution.is_dir(): raise ValueError('Distribution missing.')
    actual=set(); directories={'.'}
    for name in expected:
        directories.update(str(p) for p in PurePosixPath(name).parents)
    def walk(directory):
        for child in directory.iterdir():
            safe_path(child)
            info=child.lstat(); relative=child.relative_to(distribution).as_posix()
            if stat.S_ISDIR(info.st_mode):
                if relative not in directories: raise ValueError('Unexpected distribution directory.')
                walk(child)
            elif stat.S_ISREG(info.st_mode):
                if relative not in expected: raise ValueError('Unexpected distribution file.')
                if file_record(child)!=expected[relative]: raise ValueError('Distribution hash/size mismatch.')
                actual.add(relative)
            else: raise ValueError('Unsupported distribution entry.')
    walk(distribution)
    if actual!=set(expected): raise ValueError('Missing distribution artifact.')
    return [distribution/name for name in sorted(expected,key=str.casefold)]


def contract_from_inputs(distribution: Path, inputs: dict[str,Path], provenance: dict, *, workpath: Path | None = None) -> dict:
    """Called only with reviewed build graph inputs, never an rglob of dist."""
    records = None
    for name, source in inputs.items():
        rule = require_resource_name(name)
        if rule in {'qt-translation', 'dependency-license', 'dependency-metadata',
                    'empty-installer-marker', 'setuptools-vendored-resource'} and records is None:
            # Snapshot RECORD metadata once per build; every resource still gets
            # its own source-path and current-byte verification. No global cache.
            records = [(dist, tuple(dist.files or ())) for dist in importlib.metadata.distributions()]
        verify_resource_origin(name, source, workpath=workpath, records=records)
    files={relative_name(name):file_record(source) for name,source in inputs.items()}
    material={'schema':SCHEMA,'provenance':provenance,'files':files}
    contract={**material,'fingerprint':seal(material)}
    distribution_files(distribution,contract)
    return contract


def record_pyinstaller_build(collection, repository: Path, workpath: Path, context_path: Path, receipt_path: Path):
    """Use PyInstaller's explicit COLLECT graph and its processed binary sources."""
    import sys
    from PyInstaller.building.utils import process_collected_binary
    context=json.loads(context_path.read_text(encoding='utf8'))
    inputs={}
    for destination, source, kind in collection.toc:
        if kind not in {'EXECUTABLE','PKG','BINARY','EXTENSION','DATA'}:
            raise ValueError('Unsupported build graph entry; no link/dependency passthrough.')
        source=safe_path(Path(source))
        # This spec contains no owner/project data resources. Only generated
        # build products and the selected Python runtime may supply resources.
        if not (source.is_relative_to(safe_path(workpath)) or any(source.is_relative_to(safe_path(Path(root))) for root in {sys.prefix, sys.base_prefix})):
            raise ValueError('Build input is outside the controlled runtime/build roots.')
        if kind in {'BINARY','EXTENSION'}:
            source=Path(process_collected_binary(str(source),destination,use_strip=False,use_upx=False,upx_exclude=[],target_arch=None,codesign_identity=None,entitlements_file=None,strict_arch_validation=(kind=='EXTENSION')))
        name=(Path(destination) if kind in {'EXECUTABLE','PKG'} else Path(collection.contents_directory or '')/destination).as_posix()
        if name in inputs: raise ValueError('Duplicate build graph artifact.')
        inputs[name]=source
    contract=contract_from_inputs(Path(collection.name),inputs,context,workpath=workpath)
    with receipt_path.open('x',encoding='utf8') as stream: json.dump(contract,stream,indent=2,sort_keys=True)
