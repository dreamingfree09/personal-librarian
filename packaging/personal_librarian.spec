# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

repository = Path(SPECPATH).parent
source = repository / "src"

import os
import sys
sys.path.insert(0, str(repository / 'packaging'))
from build_contract import record_pyinstaller_build
context = os.environ.get('PL_BUILD_CONTEXT')
receipt = os.environ.get('PL_BUILD_CONTRACT')
if not context or not receipt:
    raise ValueError('Use the controlled build wrapper; build context is required.')


analysis = Analysis(
    [str(repository / "packaging" / "desktop_entry.py")],
    pathex=[str(source)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "unittest", "tkinter"],
    noarchive=False,
    optimize=1,
)
python_archive = PYZ(analysis.pure)
executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PersonalLibrarian",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version=str(repository / "packaging" / "version_info.txt"),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
distribution = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PersonalLibrarian",
)

# Receipt is derived from the explicit build graph, not the distribution directory.
record_pyinstaller_build(distribution, repository, Path(workpath), Path(context), Path(receipt))
