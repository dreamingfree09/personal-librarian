# Controlled portable packaging

Run `packaging/build_release.ps1` from a clean reviewed Windows checkout with the
qualified Python/Qt dependencies and PyInstaller installed. `build_windows.ps1`
creates the controlled distribution and receipt without a ZIP. Both use a fresh,
create-only `tmp/controlled-build-*` directory. Existing distributions and archives
are neither reused nor deleted. No installer, signing, publication or deployment
is performed.

The reviewed spec has no project/owner data resources. The contract comes from
PyInstaller's explicit COLLECT graph, restricted to generated build inputs and the
selected Python runtime. Binary preprocessing uses the same settings as COLLECT.
Expected hashes come from those inputs, not from arbitrary discovered distribution
contents. Missing, changed or unexpected files/directories fail validation. Known
private/state classes also fail even when declared. Legitimate runtime resources
remain in the graph; DLLs are not removed to make a short suffix allowlist pass.

All path ancestors must be non-reparse. File reads additionally verify the opened
Windows handle's actual path and physical identity before reading and reject links.
The ZIP writer rechecks membership and hashes, checks bytes while archiving, verifies
the resulting ZIP's exact paths/order/size/hashes, then publishes without overwrite.
A failed candidate is not published; only its own temporary ZIP is removed. Existing
outputs, external link targets and source data are preserved.

Build provenance records actual HEAD, tree, tracked-content/status fingerprints,
clean/dirty state, Python, OS, architecture and installed dependencies. Clean is the
default; `--allow-dirty` is only for explicitly labelled disposable development
builds. Source drift across the build is rejected. No historical commit or inherited
validation statement is used as current evidence.

The receipt always starts with `validation.status = NOT_PERFORMED`. Successful
collection and byte verification do not establish packaged-application acceptance.
Subsequent acceptance evidence must remain separate and bind the exact archive hash.
Do not edit a build receipt to turn it into a validation certificate.

The contract is a local build-integrity record, not a signature or trust root against
a compromised builder/runtime or administrator. It assumes reviewed source and a
trusted dependency environment. It does not establish reproducible native binaries,
complete release acceptance, signing, or public-release approval. F07, F15 and G3/G4
remain separate findings. This independent packaging branch does not include the
unmerged F04 dependency correction; it must not be used to release the old Pillow.
