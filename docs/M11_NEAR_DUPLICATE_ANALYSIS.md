# M11 - Near-Duplicate Analysis

Completed: 20 August 2026

## Purpose

M11 established a safe, review-only near-duplicate analysis layer for the Personal Librarian photo population.

The milestone did not delete, move, rename, consolidate or otherwise modify source media.

Exact SHA-256 duplicates remain a separate M10 classification.

## Input population

- Photo-extension files assessed: 67,937
- Successfully pHashed photos: 64,569
- Unique SHA-256 image contents analysed: 54,839
- Zero-byte placeholders excluded from visual analysis: 3,364
- Other unusable/non-image files identified: 3
- One valid image remained affected by a Unicode path-normalisation issue and was preserved unchanged

## Perceptual hashing

Primary signal:

- pHash

Secondary signal:

- dHash

Full dHash coverage:

- 54,839 / 54,839 unique image contents
- 0 dHash errors

## pHash discovery results

Initial search at pHash distance <= 6:

- Candidate pairs: 32,669

Distance distribution:

- Distance 0: 4,970
- Distance 1: 165
- Distance 2: 3,612
- Distance 3: 0
- Distance 4: 7,557
- Distance 5: 22
- Distance 6: 16,343

Distance 6 produced substantial structural false positives, particularly screenshots and visually similar layouts.

The working pHash review set was therefore restricted to distance <= 4:

- Candidate pairs: 16,304

## Dual-hash refinement

A second dHash signal was introduced after testing showed that pHash alone could create large screenshot/layout similarity chains.

Final review rule used for the M11 foundation:

- pHash distance <= 4
- AND dHash distance <= 4

Result:

- Input pHash review pairs: 16,304
- Dual-hash pairs retained: 9,403
- Pairs rejected by dHash: 6,901

Retained pairs by pHash distance:

- pHash 0: 4,823
- pHash 1: 154
- pHash 2: 2,177
- pHash 3: 0
- pHash 4: 2,249

## Dual-hash grouping

Connected review grouping produced:

- Candidate pairs: 9,403
- Review groups: 5,067
- Unique image contents represented: 11,325
- Largest connected group: 135 unique contents
- Groups over 20 contents: 12
- Groups over 50 contents: 1

Large clusters were inspected and shown to include structural-similarity cases such as generic screenshots and repeated screen layouts.

These groups are therefore review candidates only and must never be treated as automatic duplicate decisions.

## Safety conclusions

M11 establishes the following permanent principles:

1. Exact duplicates and near duplicates are separate classifications.
2. Perceptual similarity is evidence for review, not authority for deletion.
3. pHash alone is insufficient for reliable near-duplicate decisions.
4. Dual-hash analysis substantially reduces false positives but does not eliminate them.
5. Large structural-similarity clusters must remain low-confidence review material.
6. Source and path provenance must be preserved.
7. No automatic destructive action may result directly from M11 similarity scores.
8. Future organisation decisions must support review, quarantine and rollback.

## Durable outputs

Dual-hash manifest:

`H:\PersonalLibrary\Staging\_inventory\M11\hashes\m11_unique_content_dualhash.csv`

Dual-hash review candidates:

`H:\PersonalLibrary\Staging\_inventory\M11\reports\m11_dualhash_review_phash0_4_dhash0_4.csv`

Dual-hash grouped pairs:

`H:\PersonalLibrary\Staging\_inventory\M11\reports\m11_dualhash_groups.csv`

Dual-hash group summary:

`H:\PersonalLibrary\Staging\_inventory\M11\reports\m11_dualhash_group_summary.csv`

## Close-out

M11 - Near-Duplicate Analysis is COMPLETE.

The next milestone is:

M12 - Organisation & Canonical Copy Policy
