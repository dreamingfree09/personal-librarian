"""Bounded Windows guard timing observations; not a replacement acceptance test.

The original -File command and supplementary -EncodedCommand probe are distinct.
Only the frozen, structurally checked retired repository script is invoked.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
MARKER = 'M5_RETIRED_GUARD'


def checked_script() -> Path:
    path = ROOT / 'scripts/Invoke-M5OneDriveAcquisition.ps1'
    text = path.read_text(encoding='utf-8').replace('\r\n', '\n')
    # Frozen repository blob; newline-neutral for Git Windows checkouts.
    expected = (ROOT / 'tools/retired_guard_script.sha256').read_text().strip()
    if hashlib.sha256(text.encode()).hexdigest() != expected:
        raise RuntimeError('Retired script changed; structural review required before invocation.')
    if not (text.index('throw "M5_RETIRED_GUARD:') < text.index('$roots = @(')
            < text.index('CreateDirectory($auditDir)')):
        raise RuntimeError('Retired guard order is invalid.')
    return path


def observe(command: list[str], directory: Path, limit: float) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    created = time.monotonic() - start
    events = []; lock = threading.Lock()

    def read(stream, label):
        with (directory / (label + '.log')).open('wb') as log:
            for line in iter(stream.readline, b''):
                elapsed = time.monotonic() - start
                log.write(line); log.flush()
                with lock:
                    events.append({'stream': label, 'elapsed': elapsed,
                                   'text': line.decode('utf-8', errors='replace').rstrip()})
        stream.close()

    readers = [threading.Thread(target=read, args=(stream, label), daemon=True)
               for stream, label in ((child.stdout, 'stdout'), (child.stderr, 'stderr'))]
    for reader in readers: reader.start()
    timed_out = False
    try:
        code = child.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        timed_out = True; child.kill(); code = child.wait()
    ended = time.monotonic() - start
    for reader in readers: reader.join(timeout=5)
    complete = not any(reader.is_alive() for reader in readers)
    result = {'pid': child.pid, 'command': command, 'create_seconds': created,
              'elapsed_seconds': ended, 'returncode': code, 'timed_out': timed_out,
              'observation_limit': limit, 'output_complete': complete, 'events': events}
    (directory / 'result.json').write_text(json.dumps(result, indent=2))
    return result


def instrumented(script: Path) -> str:
    quoted = str(script).replace("'", "''")
    return r'''
$watch = [Diagnostics.Stopwatch]::StartNew()
function Mark($name) {
    [Console]::Out.WriteLine(('GUARD_PROBE:' + $name + ':' + $watch.Elapsed.TotalSeconds.ToString('R',[Globalization.CultureInfo]::InvariantCulture)))
    [Console]::Out.Flush()
}
Mark 'READY'
[Console]::Out.WriteLine(('PS_VERSION:' + $PSVersionTable.PSVersion.ToString()))
[Console]::Out.WriteLine(('PS_PID:' + $PID))
$tokens=$null; $errors=$null
Mark 'PARSE_BEGIN'
$ast=[Management.Automation.Language.Parser]::ParseFile('__PATH__',[ref]$tokens,[ref]$errors)
Mark 'PARSE_END'
if ($errors.Count -ne 0 -or $ast.EndBlock.Statements[0] -isnot [Management.Automation.Language.ThrowStatementAst]) { throw 'Unexpected guard structure' }
Mark 'INVOKE_BEGIN'
try { & '__PATH__'; Mark 'UNEXPECTED_SUCCESS'; exit 0 }
catch {
    Mark 'GUARD_CAUGHT'
    [Console]::Error.WriteLine($_.Exception.Message)
    [Console]::Error.Flush()
    Mark 'EXIT_BEGIN'
    exit 1
}
'''.replace('__PATH__', quoted)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'tmp/guard-diagnostic')
    args = parser.parse_args()
    if os.name != 'nt': raise RuntimeError('Windows diagnostic only.')
    executable = shutil.which('powershell.exe')
    if executable is None: raise RuntimeError('Windows PowerShell unavailable.')
    script = checked_script()
    args.output.mkdir(parents=True, exist_ok=False)
    environment = {'os': platform.platform(), 'python': platform.python_version(),
                   'cpu_count': os.cpu_count(), 'processor': platform.processor(),
                   'runner_os': os.environ.get('RUNNER_OS'),
                   'runner_arch': os.environ.get('RUNNER_ARCH'),
                   'image_version': os.environ.get('ImageVersion'), 'executable': executable,
                   'definition': '3 sequential pairs; first observed vs subsequent warm launches; no retries',
                   'observation_limit_note': '30 seconds is diagnostic observation only, not a changed test budget.'}
    (args.output/'environment.json').write_text(json.dumps(environment, indent=2))
    encoded = base64.b64encode(instrumented(script).encode('utf-16-le')).decode()
    results = []
    for index in range(3):
        for kind, tail in [('original', ['-File', str(script)]),
                           ('instrumented', ['-EncodedCommand', encoded])]:
            result = observe([executable, '-NoProfile', '-NonInteractive', *tail],
                             args.output/f'{index+1}-{kind}', 30)
            result.update(kind=kind, index=index+1)
            result['guard_refused'] = (result['returncode'] != 0 and not result['timed_out']
                and result['output_complete'] and any(MARKER in e['text'] for e in result['events']))
            results.append(result)
            (args.output/'results.json').write_text(json.dumps(results, indent=2))
            print(json.dumps({k: result[k] for k in ('kind','index','pid','create_seconds',
                'elapsed_seconds','returncode','timed_out','guard_refused')}), flush=True)
            if not result['guard_refused']: return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
