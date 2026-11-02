"""Create a portable candidate from an explicit controlled build contract."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from uuid import uuid4
import zipfile
from datetime import UTC, datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_contract import (contract_from_inputs, distribution_files, file_record,
                            read_regular, safe_path, seal, validate_contract)

RELEASE_VERSION = "0.1.0rc7"
ARCHIVE_NAME = f"PersonalLibrarian-{RELEASE_VERSION}-win64.zip"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def sha256_file(path: Path) -> str:
    return file_record(path)['sha256']


def verify_version_metadata(repository: Path) -> None:
    pyproject = tomllib.loads((repository / "pyproject.toml").read_text(encoding="utf-8"))
    if pyproject["project"]["version"] != RELEASE_VERSION:
        raise ValueError("Python project version does not match the release version.")
    package_init = (repository / "src/personal_librarian/__init__.py").read_text(
        encoding="utf-8"
    )
    if not re.search(rf'__version__\s*=\s*"{re.escape(RELEASE_VERSION)}"', package_init):
        raise ValueError("Runtime version does not match the release version.")
    windows_metadata = (repository / "packaging/version_info.txt").read_text(
        encoding="utf-8"
    )
    for expected in (
        "filevers=(0, 1, 0, 7)",
        "prodvers=(0, 1, 0, 7)",
        f"StringStruct(u'FileVersion', u'{RELEASE_VERSION}')",
        f"StringStruct(u'ProductVersion', u'{RELEASE_VERSION}')",
    ):
        if expected not in windows_metadata:
            raise ValueError(f"Windows version metadata is inconsistent: {expected}")


def git_output(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def source_state(repository: Path, *, allow_dirty: bool = False) -> dict:
    status=git_output(repository,'status','--porcelain=v1','--untracked-files=all')
    if status and not allow_dirty:
        raise ValueError('Release build requires a clean source checkout.')
    # Bind dirty test builds to actual tracked bytes, not merely the HEAD label.
    names=git_output(repository,'ls-files','-z').split('\0')
    tracked={name:file_record(repository/name) for name in names if name}
    return {'source_commit':git_output(repository,'rev-parse','HEAD'),
            'source_tree':git_output(repository,'rev-parse','HEAD^{tree}'),
            'working_tree_dirty':bool(status),'tracked_content_fingerprint':seal(tracked),
            'status_fingerprint':hashlib.sha256(status.encode()).hexdigest()}


def build_provenance(repository: Path, *, allow_dirty: bool = False) -> dict:
    return {**source_state(repository,allow_dirty=allow_dirty),
            'build_timestamp_utc':datetime.now(UTC).isoformat(timespec='seconds'),
            'environment':{'python':sys.version,'os':platform.platform(),'architecture':platform.machine(),
                           'dependencies':sorted([d.metadata['Name'],d.version] for d in importlib.metadata.distributions())},
            'validation':'NOT_PERFORMED'}


def verify_provenance(repository: Path, provenance: dict, *, allow_dirty: bool = False):
    if provenance.get('validation')!='NOT_PERFORMED':
        raise ValueError('Build provenance must not inherit validation claims.')
    current=source_state(repository,allow_dirty=allow_dirty)
    if any(provenance.get(key)!=value for key,value in current.items()):
        raise ValueError('Build source/provenance drift.')


def verify_archive(archive: Path, contract: dict) -> None:
    expected=validate_contract(contract)
    with read_regular(archive) as stream, zipfile.ZipFile(stream) as candidate:
        names=['PersonalLibrarian/'+name for name in sorted(expected,key=str.casefold)]
        if candidate.namelist()!=names: raise ValueError('Archive membership/order mismatch.')
        for info in candidate.infolist():
            record=expected[info.filename.removeprefix('PersonalLibrarian/')]
            if info.file_size != record['size']: raise ValueError('Archive entry size mismatch.')
            digest=hashlib.sha256(); size=0
            with candidate.open(info) as source:
                while chunk:=source.read(1024*1024): digest.update(chunk);size+=len(chunk)
            if {'size':size,'sha256':digest.hexdigest()}!=record:
                raise ValueError('Archive content mismatch.')


def create_archive(distribution: Path, contract: dict, archive: Path) -> None:
    distribution=safe_path(distribution); archive=safe_path(archive)
    files=distribution_files(distribution,contract)
    if archive.exists(): raise FileExistsError('Refusing to overwrite an archive.')
    archive.parent.mkdir(parents=True,exist_ok=True)
    safe_path(archive.parent)
    temporary=archive.with_name('.'+archive.name+'.'+uuid4().hex+'.tmp')
    created=False
    try:
        with temporary.open('xb') as output:
            created=True
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as destination:
                for source in files:
                    relative=source.relative_to(distribution).as_posix()
                    info=zipfile.ZipInfo('PersonalLibrarian/'+relative,_ZIP_TIMESTAMP)
                    info.compress_type=zipfile.ZIP_DEFLATED
                    info.external_attr=(0o755 if source.suffix.casefold()=='.exe' else 0o644)<<16
                    digest=hashlib.sha256();size=0
                    with read_regular(source) as incoming, destination.open(info,'w') as outgoing:
                        while chunk:=incoming.read(1024*1024):
                            digest.update(chunk);size+=len(chunk);outgoing.write(chunk)
                    if {'size':size,'sha256':digest.hexdigest()}!=contract['files'][relative]:
                        raise ValueError('Artifact changed during archive creation.')
        distribution_files(distribution,contract)
        verify_archive(temporary,contract)
        safe_path(archive.parent)
        if os.name=='nt': os.rename(temporary,archive)  # atomic, no replacement on Windows
        else:
            os.link(temporary,archive)
            temporary.unlink()
        created=False
    finally:
        if created: temporary.unlink(missing_ok=True)


def write_json_exclusive(path: Path, value: dict) -> None:
    with path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)


def verify_release_files(output: Path, contract: dict) -> dict:
    """Require a complete hash-bound build set; this is NOT package acceptance."""
    output = safe_path(output)
    marker = output / (ARCHIVE_NAME + '.build-complete.json')
    with read_regular(marker) as stream:
        completion = json.load(stream)
    expected_names = {ARCHIVE_NAME, ARCHIVE_NAME + '.manifest.json', ARCHIVE_NAME + '.sha256'}
    if (set(completion) != {'schema', 'files', 'contract_fingerprint', 'validation'}
            or completion['schema'] != 'portable-build-set-v1'
            or completion['validation'] != 'NOT_PERFORMED'
            or completion['contract_fingerprint'] != contract['fingerprint']
            or set(completion['files']) != expected_names):
        raise ValueError('Incomplete or inconsistent build set.')
    for name, record in completion['files'].items():
        if file_record(output / name) != record:
            raise ValueError('Build-set content drift.')
    verify_archive(output / ARCHIVE_NAME, contract)
    with read_regular(output / (ARCHIVE_NAME + '.manifest.json')) as stream:
        receipt = json.load(stream)
    if (receipt['provenance'] != contract['provenance']
            or receipt['files'] != validate_contract(contract)
            or receipt['build_contract_fingerprint'] != contract['fingerprint']
            or receipt['archive'] != {'name': ARCHIVE_NAME, **file_record(output / ARCHIVE_NAME)}
            or receipt['validation'] != {'status': 'NOT_PERFORMED', 'evidence': []}):
        raise ValueError('Build receipt does not match the controlled contract.')
    with read_regular(output / (ARCHIVE_NAME + '.sha256')) as stream:
        if stream.read() != f"{receipt['archive']['sha256']}  {ARCHIVE_NAME}\n".encode('ascii'):
            raise ValueError('Checksum receipt mismatch.')
    return receipt


def write_release_files(repository: Path, distribution: Path, output: Path, contract: dict, *, allow_dirty: bool=False) -> dict:
    repository=safe_path(repository);distribution=safe_path(distribution);output=safe_path(output)
    if not distribution.is_relative_to(repository/'tmp') or output!=repository/'release':
        raise ValueError('Only controlled temporary builds and the repository release output are supported.')
    validate_contract(contract)
    verify_version_metadata(repository)
    verify_provenance(repository,contract['provenance'],allow_dirty=allow_dirty)
    output.mkdir(exist_ok=True)
    archive=output/ARCHIVE_NAME
    manifest_path=output/(ARCHIVE_NAME+'.manifest.json')
    checksums=output/(ARCHIVE_NAME+'.sha256')
    completion_path=output/(ARCHIVE_NAME+'.build-complete.json')
    for target in (archive,manifest_path,checksums,completion_path):
        if target.exists(): raise FileExistsError('Refusing to overwrite release output.')
    create_archive(distribution,contract,archive)
    verify_provenance(repository,contract['provenance'],allow_dirty=allow_dirty)
    receipt={'release_version':RELEASE_VERSION,'release_status':'unsigned local candidate; package acceptance not performed',
             'signed':False,'installer':False,'provenance':contract['provenance'],
             'build_contract_fingerprint':contract['fingerprint'],'files':contract['files'],
             'archive':{'name':archive.name,**file_record(archive)},
             'validation':{'status':'NOT_PERFORMED','evidence':[]}}
    write_json_exclusive(manifest_path, receipt)
    with checksums.open('x',encoding='ascii',newline='\n') as stream: stream.write(f"{receipt['archive']['sha256']}  {archive.name}\n")
    # Publish the completion marker last. An interrupted partial set remains
    # preserved but cannot pass verify_release_files or be called accepted.
    completion={'schema':'portable-build-set-v1',
                'files':{path.name:file_record(path) for path in (archive,manifest_path,checksums)},
                'contract_fingerprint':contract['fingerprint'],'validation':'NOT_PERFORMED'}
    verify_provenance(repository,contract['provenance'],allow_dirty=allow_dirty)
    write_json_exclusive(completion_path,completion)
    return verify_release_files(output,contract)


def controlled_build(repository: Path, *, build_only: bool=False, allow_dirty: bool=False) -> dict:
    repository=safe_path(repository)
    verify_version_metadata(repository)
    provenance=build_provenance(repository,allow_dirty=allow_dirty)
    root=safe_path(repository/'tmp'/('controlled-build-'+uuid4().hex))
    root.mkdir(parents=True,exist_ok=False)
    context=root/'context.json';contract_path=root/'contract.json'
    context.write_text(json.dumps(provenance),encoding='utf8')
    env=dict(os.environ,PL_BUILD_CONTEXT=str(context),PL_BUILD_CONTRACT=str(contract_path))
    command=[sys.executable,'-m','PyInstaller','--distpath',str(root/'dist'),'--workpath',str(root/'work'),str(repository/'packaging/personal_librarian.spec')]
    subprocess.run(command,cwd=repository,env=env,check=True)
    contract=json.loads(contract_path.read_text(encoding='utf8'))
    if contract['provenance']!=provenance: raise ValueError('Build context mismatch.')
    verify_provenance(repository,provenance,allow_dirty=allow_dirty)
    distribution=root/'dist/PersonalLibrarian'
    distribution_files(distribution,contract)
    if build_only: return {'contract':str(contract_path),'distribution':str(distribution),'validation':'NOT_PERFORMED'}
    return write_release_files(repository,distribution,repository/'release',contract,allow_dirty=allow_dirty)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--repository-root',type=Path,required=True)
    parser.add_argument('--build-only',action='store_true')
    parser.add_argument('--allow-dirty',action='store_true',help='Disposable development build only; records actual dirty state.')
    args=parser.parse_args(argv)
    print(json.dumps(controlled_build(args.repository_root,build_only=args.build_only,allow_dirty=args.allow_dirty),indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
