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
A failed ZIP candidate is not published; only its own temporary ZIP is removed.
Existing outputs, external link targets and source data are preserved.

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
remain separate findings. The packaging branch includes the accepted F04 correction and must be validated
with Pillow 13.0.0 and the qualified Qt 6.11.2 runtime.


## Declared resource admission

Resource classification is case-insensitive, including sensitive directory and
configuration names. Ordinary runtime binaries remain supported. Other data is
closed by default: an arbitrary declared image, document, inventory, archive or
configuration does not become approved merely by appearing in COLLECT or a sealed
contract. No general image/document suffix exception is enabled.

The narrow runtime data approvals are the generated `base_library.zip` (exact
controlled work location, Python-module-only members), Qt translation resources,
and dependency licence/installation metadata for the named installed libraries.
These resources must match both the source location and SHA-256 in the installed
wheel RECORD. RECORD itself has no self-hash: only the exact metadata file located
by its installed distribution is approved. This deliberately trusts the selected
installed package metadata, not arbitrary declared inputs. The approved data policy is reapplied in contract validation,
distribution validation, ZIP verification and release-receipt generation. Future
runtime assets need a reviewed rule and origin check; naming a file like an asset
is insufficient. Selected virtual-environment and base-Python roots are supported.
The installed dependency metadata and reviewed builder remain trusted inputs.

## Interrupted release-set publication

The archive, manifest and checksum are create-only. A hash-bound
`.build-complete.json` marker is written last, after all three are present and
source provenance is checked again. `verify_release_files()` requires that marker,
rechecks every file and the ZIP against the contract, and rejects incomplete or
changed sets. This marker records build completeness, never acceptance:
`validation = NOT_PERFORMED` remains mandatory. External smoke/release acceptance
must be recorded separately against the exact archive hash.

If manifest/checksum/marker publication fails, partial outputs are preserved and
the command fails. They cannot pass the completion verifier; rerunning does not
overwrite them. Operators must retain/review interrupted evidence and use a fresh
isolated build checkout. This is not an atomic multi-file delivery transaction,
public-release workflow or power-loss durability guarantee. G3/G4 delivery work
remains open. Do not distribute a ZIP merely because its filename exists.
