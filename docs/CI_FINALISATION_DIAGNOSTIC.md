# Windows CI finalisation qualification

This is the bounded PR #3 follow-up to accepted F01-F03 at
`7ce1fb3543b86f19eb38788e90e0f7bd10452b2d`. It does not resolve F04-F17 or
G1-G4, authorise integration, or change recovery/bootstrap/command-mode code.

## Finding and remaining limitation

The failure is after successful unittest assertions, during native process
finalisation. A parent process captured Windows status `0xC0000005` with
faulthandler reporting `Aborted`, an access violation and no Python frame.
The ordinary PowerShell CI step reported exit 1 without this detail.

The failure reproduces with the PySide6 6.12.0 family on Python 3.13.1,
3.13.16 and 3.13.17. Python 3.13.17 is therefore not a necessary cause.
Repeated runs in the same environment can both pass and crash. A green
rerun alone does not resolve the problem.

The exact native ownership fault remains unresolved: these observations do
not prove an upstream Qt defect or a CPython defect. No speculative worker
rewrite is applied. The bounded correction qualifies **PySide6 6.11.2** and
pins it in project metadata. `requirements-ci.txt` fixes the other comparison
dependencies, and ordinary CI fixes Python 3.13.17. The lifecycle matrix
also exercises Python 3.13.16. Relaxing the Qt pin requires a fresh controlled
qualification, including successful process shutdown, not just assertions.

## Controlled evidence

At diagnostic revision `cf5c3d1a9575f66bbdd27e47ec579c7f3b8ae7fc`,
[matrix run 41429639686](https://github.com/dreamingfree09/personal-librarian/actions/runs/41429639686)
held Pillow 12.3.0, NumPy 2.5.4 and setuptools 80.9.0 fixed:

| Python | PySide6 family | First full process | Second full process | Desktop-only process |
| --- | --- | --- | --- | --- |
| 3.13.16 | 6.11.2 | 239 / OK / exit 0 | 239 / OK / exit 0 | 44 / OK / exit 0 |
| 3.13.17 | 6.11.2 | 239 / OK / exit 0 | 239 / OK / exit 0 | 44 / OK / exit 0 |
| 3.13.16 | 6.12.0 | 239 / OK / access violation | 239 / OK / exit 0 | 44 / OK / access violation |
| 3.13.17 | 6.12.0 | 239 / OK / access violation | 239 / OK / access violation | 44 / OK / exit 0 |

The first observer's supplementary ordering runs had an import-path defect
(`tests.*` fixture helpers were unavailable). Those runs are **invalid for
product diagnosis**, and their failures remain recorded. The canonical
`-m unittest` runs and isolated desktop discovery commands above are unaffected.
Commit `df5fdb7124ffaa6f1d8840fd737be5ac794c7c68` corrects that observer path.

In [corrected matrix run 41430525516](https://github.com/dreamingfree09/personal-librarian/actions/runs/41430525516),
both Python 3.13.16 and 3.13.17 / PySide6 6.11.2 jobs completed all ten child
processes each with exit 0: two canonical 239-test runs; three instrumented 239-test runs
(normal, desktop-first, desktop-last); 195 non-desktop tests; 44 desktop
tests; and the individual 10-, 16- and 18-test desktop modules. Each
instrumented full run recorded unittest `SystemExit(0)`, no active global
Qt pool threads, the Python atexit marker and final OS exit 0.

Both corrected Qt 6.12.0 jobs failed. Their observed/order runs demonstrated
`SystemExit(0)` and zero active Qt pool threads followed by native failure
before the final Python atexit marker. Return codes included `0xC0000005`
and 3. Non-desktop processes exited 0. A desktop foundation module also
crashed in the second matrix, so the defect is not exclusive to combined
desktop modules. These results reinforce the runtime qualification while
leaving the exact native cause unresolved.

Hosted comparisons use Windows Server 2025 build 26100. Local independent
reproductions use a network-disabled Windows 11 build 26100 sandbox,
Python 3.13.1, Pillow 12.3.0 and NumPy 2.5.2. No owner/production drives are
mapped. Changing only the Qt package family to 6.12.0 reproduced three
access violations in five 44-test desktop runs. The M30/usability pair
also crashed once in three runs; the real AsyncPage background path is
therefore not necessary to reproduce the failure.

## Worker investigation

`AsyncPage.Worker` uses default QRunnable auto-deletion; `LibraryPage._Worker`
disables auto-deletion and retains active workers until its finished signal.
The existing Library worker test uses a capturing pool and synchronous
`run()`, so it is not a threaded shutdown test.

Disposable diagnostic-only experiments parented signal objects to the
corresponding page, without replacing any acceptance test:

| 44-test experiment, Qt 6.12.0 | Access violations / runs |
| --- | --- |
| unchanged control | 2 / 6 |
| AsyncPage signals parented | 4 / 6 |
| LibraryPage signals parented | 2 / 6 |
| both parented | 1 / 6 |

None establishes a fix. No such experiment was applied to product code.
The unresolved native fault needs a smaller reproducer/native stack before
attributing it to either worker class. A known-failing runtime is excluded
instead of hiding the failure through per-module acceptance, forced exits,
exception suppression, or changes to existing assertions.

## Reproduction and acceptance

Use an isolated Windows environment with the repository's synthetic tests:

```powershell
python -m pip install -r requirements-ci.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pip install --no-deps --no-build-isolation -e .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m pip check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -X faulthandler -u tools/diagnose_test_process.py --groups --desktop-repeats 5
$testExit = $LASTEXITCODE
Write-Output "Diagnostic parent LASTEXITCODE=$testExit"
exit $testExit
```

The parent does not import Qt. Its primary children run exactly
`python -X faulthandler -u -m unittest discover -s tests -v`.
Supplementary observer/order runs may perturb timing and are labelled.
Any failed or timed-out child fails the parent. Three harness regressions
verify separate stdout/stderr, timeouts, and `OK` followed by exit 1.
The original 236 tests remain intact; the total is now 239.

Each run preserves executable, OS/Python/dependency inventory, PID, command,
stdout, stderr, duration, final OS status and summary separately under
ignored `tmp/ci-finalisation/`. Existing evidence directories cannot be
silently overwritten. GitHub uploads synthetic evidence even on failure;
that does not turn the job green. Raw artifacts are also retained privately
with their published SHA-256 hashes, independently of hosted expiry.

The final candidate requires green Windows process-exit checks and a fresh
Aether review of its exact head/tree. PR #3 remains draft. No merge or
release is part of this diagnostic.
