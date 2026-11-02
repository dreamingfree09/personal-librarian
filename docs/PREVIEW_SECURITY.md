# Preview decoder security boundary

The preview service accepts JPEG (`.jpg`, `.jpeg`), PNG, GIF and WebP only.
The extension selects the single permitted Pillow decoder; detected format is
checked before pixel loading or metadata transformation. Renaming another format
does not admit it. Sources are opened read-only. Existing 50-million-pixel limits,
Pillow bomb checks, EXIF orientation, transparency and atomic cache publication
remain in place. Cache version v3 prevents reuse of previews admitted by the old
unrestricted decoder path. Failures return unavailable and remove temporary output.

Runtime Pillow is constrained to `>=13.0.0,<14`; CI uses 13.0.0. The qualified
PySide6/Shiboken 6.11.2 family is unchanged. The 13.0.0 fixed release is documented
by [Pillow release notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html)
and the [JPEG decoder advisory](https://github.com/python-pillow/Pillow/security/advisories/GHSA-8g5g-8vmr-9782).

Validation uses only synthetic images: four supported formats, misleading suffixes,
excluded decoders, malformed bytes/metadata, pixel/bomb limits, orientation, alpha,
cache failures and native Qt rendering. A harmless disguised TIFF was admitted by
the original implementation and rejected after correction. The native Windows
suite runs through the existing parent-process observer; success requires exit 0.
The existing two-version qualified Qt CI lifecycle matrix is also required.

Dependency advisory counts are feed matches, not proof of exploitability in this
application. Private evidence retains the actual installed inventories and feed
responses. The local guest reuses a read-only Python runtime with a guest-local
Pillow 13.0.0 overlay; its older package metadata remains visible in inventory.
Hosted CI installs the controlled dependencies into a fresh environment.

This correction does not claim F07 application-data junction safety, fully sandboxed
image decoding, or resolution of the excluded Qt 6.12 native shutdown failure.
