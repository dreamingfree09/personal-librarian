# M25 Owner Usability Feedback

## Owner usability pass

Completed: 24 August 2026

Release candidate tested:
- RC1 initially
- RC2 accepted for continued testing after preview-binding fix

## What felt good

- Standalone packaged application launched successfully outside the repository.
- Production catalogue health showed PASS.
- Independent disaster-recovery readiness showed PASS.
- Overview presented the key catalogue and backup state correctly.
- Exact Duplicates loaded real production groups and previews.
- Similar Images showed visually related but non-identical content correctly.
- Read-only image viewer supported zoom, fit-to-window, 100%, panning and Escape close.
- Decision History, Plans, Quarantine and Backups / Recovery were clearly read-only where intended.
- No general physical execution, delete, quarantine, restore or catalogue-recovery controls were exposed.
- Decision nomination confirmation clearly separated nomination from approval.
- RC2 exact-duplicate preview binding remained correct across multiple real groups.
- RC2 Similar Images preview binding also remained correct.

## Release-blocking issue found

RC1 exposed a serious stale-preview binding defect during the owner pass.

Exact duplicate group 41904 reported three physical representations with the same SHA-256, but the visible preview panel showed unrelated images.

The cause was asynchronous thumbnail/detail completion being associated with mutable row indexes rather than stable context/generation/instance/path identity.

This was treated as release-blocking because visual review evidence could not be trusted for owner decisions.

The issue was fixed in RC2.

RC2 verification confirmed:
- exact group 41904 showed the same underlying image for all three physical representations;
- exact group 41442 also showed aligned previews;
- additional exact groups remained aligned;
- rapid switching could no longer overwrite current previews with stale callbacks;
- Similar Images context 2634 remained correctly bound.

Accepted fix commit:
`8fb254e M25: fix stale preview binding and release RC2`

RC1 is superseded and must not be used for owner testing.

## What was confusing or visually weak

### Exact Duplicates

- The top table uses only part of the available width while large empty space remains.
- Physical-instance detail tables give excessive visual weight to long raw/current paths.
- Full SHA-256 values are too visually dominant for normal review.
- Technical labels such as `A:pending D:pending` are not owner-friendly.
- `ARCHIVAL — · DISPLAY —` is technically correct but not plain-language.
- Content IDs and instance IDs are more prominent than useful human-facing information.
- Preview captions are too long and visually dense.
- Preview images could be larger and more central to the workflow.
- Decision controls are crowded along the bottom.
- The context summary line contains too much technical information in one sentence.
- The UI should make the key exact-duplicate fact more obvious: these files are byte-for-byte identical.

### Similar Images

- `review_only` is backend-oriented wording.
- pHash/dHash values need plain-language explanation or tooltips.
- The similarity table is compressed to the left.
- Technical path/hash columns dominate detail views.
- Preview images are the most useful evidence and should receive greater visual emphasis.

### Preview viewer

- Filename and full SHA-256 dominate the metadata area.
- More useful owner-facing information should appear first: source, filename, size, date and represented-copy count.
- Technical IDs/hash could be secondary or collapsible.
- Archival/display state wording should be friendlier.

### Decision confirmation

- The confirmation dialog is safe and functionally clear.
- `Context: exact ####` and `Target instance: ####` are too technical.
- Full paths dominate the dialog.
- A friendlier primary question would be preferable, such as:
  `Nominate this copy as the preferred archival candidate?`
- Filename and/or thumbnail should be visually prominent before technical IDs.

### Overview

- Functionally correct but text-heavy.
- Could benefit from clearer grouping/cards for health, catalogue, duplicates, backups and decisions.

### Backups / Recovery

- Correct and safe.
- Very long hashes and manifest paths make the table harder to scan.

## What was slow

No serious performance problem was identified during the owner pass.

Initial health validation and some preview loading may take several seconds, but no release-blocking responsiveness issue was observed.

## Missing information / improvements

- Friendlier owner-facing terminology for canonical state and similarity evidence.
- Better visual prioritisation of previews over technical identifiers.
- Better column sizing/default widths.
- Clearer explanation of exact vs similar groups.
- Human-readable decision confirmation.
- Potential future visual grouping/cards on Overview.

## Decision workflow concerns

No unsafe write was performed during the owner pass.

The nomination confirmation was inspected and cancelled.

Nomination and approval remain correctly separate.

Decision history remained at zero during testing.

## Preview issues

RC1 stale preview binding was release-blocking and is fixed in RC2.

No remaining preview-binding defect was observed during the RC2 owner pass.

## Release/startup issues

RC2 launched successfully from a fresh extracted folder using the external production and independent-backup roots.

The release remains:
- unsigned;
- portable one-folder;
- without installer/updater;
- without custom icon.

These are not blockers for current personal/internal use.

## Must-fix before v0.1

- RC1 stale preview binding: FIXED in RC2.
- No other release-blocking defect identified during this owner pass.

## Nice-to-have / next milestone

Recommended next milestone:
M26 - Desktop UX Refinement

Focus on:
- clearer table sizing/layout;
- human-friendly terminology;
- better visual hierarchy;
- larger/more central previews;
- simpler metadata presentation;
- friendlier decision confirmation;
- pHash/dHash explanation;
- Overview grouping/cards;
- backup-table readability.

Do not broaden physical execution in M26.
