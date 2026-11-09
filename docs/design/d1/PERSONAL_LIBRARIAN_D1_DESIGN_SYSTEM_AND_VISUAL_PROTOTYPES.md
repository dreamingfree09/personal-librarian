# PERSONAL LIBRARIAN D1 DESIGN SYSTEM AND VISUAL PROTOTYPES

6 November 2026 · Design-only · Issue #21 · Owner and Aether review required

**D1 DESIGN DELIVERY: PASS. Product implementation/interactive usability acceptance: NOT PERFORMED.**

Recommend **Direction A — Quiet Archive**: a warm, light, year-first library with large previews and restrained teal emphasis. It best reflects the owner's accepted mental model and reduces the engineering-console feeling. Direction B — Light Table — is a credible dark, comparison-first alternative for sustained image review. Borrow its optional two-up comparison pattern only after owner approval; do not turn the entire library into a specialist image editor.

Every image is a **source-derived concept using synthetic data**, not a screenshot of the application. Geometric landscapes were drawn locally; no personal images, paths, hashes or owner catalogue content were used. All counters and names in the mockups are fictional. The app has not been redesigned or modified.

## Reviewed source

Source anchor: `ad26c9b3c2d8d33188b1e97b4bbb38c368100bef`; tree `a3cb664fbb32d2c2894fb0ad7ce4b33716ae08e9`. Work began from the equivalent preceding implementation state and finished against the adopted accepted main. `source-evidence.json` records final file hashes; the table below supplies line anchors. Current source overrides older milestone records.

| Source | Design consequence |
|---|---|
| `desktop/main_window.py:135` OverviewPage; `:1067` MainWindow | Eight sections remain present. Group navigation visually, without replacing the canonical page routing or numeric preference identity. Overview separates catalogue health, library counts, reviews, decisions and backup readiness. |
| `desktop/main_window.py:73` PreviewBinding; `:761` decision enablement; `:1238` closeEvent | Keep stable context/generation/instance/path bindings, health-enabled actions, explicit actor, nomination vs approval and existing close/lifecycle behavior. |
| `desktop/library_page.py:35`, `:274`, `:336`, `:391` | 50-item mutation cap; four actual tabs Years, Collections, Tags, History. Albums are nested under Years, not a fifth canonical tab. Separate Needs review and Unknown-only filters. |
| `desktop/library_page.py:866–905`, `:1120–1142` | Preserve request-generation and album UUID checks; visual card position must never become selection identity. Clear stale selections before loading. |
| `desktop/library_page.py:654–685` | Schema-9 compatibility cannot fabricate Collections or preferred-date capability. Show an explanation instead of an automatic migration action. |
| `desktop/startup.py:24`, `:52` | Connect only to an existing validated application-data root. Cancellation must stay harmless; no silent bootstrap or scan. |
| `desktop/viewer.py:21` | Read-only viewer retains Fit, 100%, zoom, pan, Escape; technical details remain available but secondary. |
| `desktop/preferences.py:14–35`, `:82` | Page sizes 25/50/100 are separate from the 50-item mutation cap. Thumbnail choices 128–320; geometry/splitters/actor preferences remain recoverable, not authoritative decisions. |
| `desktop/ui_helpers.py` | Reuse owner-facing scope/state formatting and confirmation semantics. Perceptual similarity never means byte identity. |
| `M23_DESKTOP_REVIEW_INTERFACE_FOUNDATION.md` | Exact and Similar remain distinct; no automatic keeper; Plans, Quarantine and backup/recovery remain read-only. Existing preview cap and bounded services remain. |
| `M25_OWNER_USABILITY_FEEDBACK.md` | Address dense paths/hashes, crowded actions, weak preview priority and confusing technical labels; never regress the historic stale-preview fix. |
| `M26_DESKTOP_UX_REFINEMENT.md` | Keep exact/similar splitters, plain-language confirmation, accessible names and keyboard shortcuts. |
| `M29_YEAR_CENTRED_DESKTOP_ORGANISATION.md` | Owner endorsed Year as bookshelf, Album as meaningful logical grouping, no Windows folders/copies. |
| `M30_PREFERRED_DATE_COLLECTIONS.md` | Collections contain content directly, not Albums. Preserve partial date precision, evidence authority, owner overrides and provenance. |

The earlier docs describe earlier schemas and implementation stages. The concepts are grounded in current schema-10 behavior and its schema-9 fallback, not in unimplemented future semantic/search features.

## Information architecture and owner-language mapping

| Canonical section | Proposed location and presentation | Retained behavior |
|---|---|---|
| Overview | Browse / Overview | Health, identity/physical-copy counts, exact/similar group counts, decisions, plans, recovery-required state and operational/independent backups. Technical UUID/schema/size in an expandable detail view. |
| Library | Browse / Library | Year-first shelf → album cards → bounded item grid; All Photos & Videos and Unsorted retained. Collections, Tags, History remain explicit tabs. |
| Exact Duplicates | Review / Exact Duplicates | Verified identical content, all copies inspectable; archival and display/export scopes independent. Explicit nomination, approval/reject/supersede/abstain states retained. |
| Similar Images | Review / Similar Images | Visually related but distinct identities; distances and threshold explanation; no preferred-copy or physical-action controls. |
| Decisions | Records & Safety / Decisions | Append-only actor, reason, scope and event lineage; no edit/delete. |
| Plans | Records & Safety / Plans | Read-only plan, items and preflight history; no Execute. |
| Quarantine | Records & Safety / Quarantine | Read-only location/event history and recovery information; no restore/reconcile/delete controls. |
| Backups / Recovery | Records & Safety / Backups / Recovery | Operational and independent classes, verification time/hash/manifest, health and current availability kept distinct. No production restore. |

The sidebar names remain familiar. Section grouping is presentation only. Do not reorder stored section indexes without an explicit compatibility map. Library album/card UUIDs and selected content IDs remain authoritative, never filenames or row indexes. Tags remain manually created labels, not AI categories, people, events or substitute Collections.

The quieter cards omit toolbar clutter, not capabilities. Album create/rename/archive/restore/add/remove and history remain available through contextual controls; Collections retain their own direct-member lifecycle and Active/Archived/All filter. Tags retain create/add/remove. Date evidence and owner-set/replace controls remain behind explicit item selection. History retains domain filtering and event details. Every logical write still requests actor, optional reason and confirmation; the generic visual design must not turn those into silent shortcuts.

## Direction A — Quiet Archive (recommended)

Light canvas `#F5F6F3`, white panels, deep-green ink `#203C3A`, muted text `#5D6F6C`, teal accent `#126557`, pale selection `#E4F2EB`. Warm surfaces feel like a library rather than an administration console. Year context stays first; images are large enough to judge; bounded actions sit beside relevant evidence.

Optional dark counterpart: canvas `#182522`, surface `#22332E`, ink `#ECF2E9`, muted `#BDC9C0`, accent `#80C9AE`. This is a palette proposal, not a rendered or implemented dark-mode guarantee. Keep the same information structure and semantic colors.

Overview uses an actionable hierarchy: collection size → browse year → genuine review needs → backup confidence. Exact review uses a large selected preview, an inspectable copy strip and a persistent owner-choice/evidence panel. Selection highlights inspection only, not a keeper. The blank actor field leaves nomination visually disabled.

## Direction B — Light Table (alternative)

Graphite canvas `#141A25`, blue-gray panels `#202938`, cool ink `#F0F4FD`, muted `#B4C1D3`, restrained blue accent `#8DB8FF`. The review concept gives two related images equal side-by-side space and moves supporting evidence below them. This is an alternative review composition, not only a dark stylesheet.

Optional light counterpart: canvas `#F2F5FC`, surface `#FFFFFF`, ink `#1F2D45`, muted `#52627D`, accent `#2857A7`. Light mode should preserve comparative emphasis and not change evidence meaning.

Strength: large image comparison and low surrounding luminance. Tradeoff: more specialist/editor-like, less welcoming for catalogue browsing and mixed material. The two-up mode must stay a bounded presentation of existing members; it must not invent pairwise relations, rank a keeper or change the Similar contract.

## High-fidelity concepts

Open `index.html` for the complete local gallery; every image also has a scalable SVG master.

1. `00-direction-archive.png` — Quiet Archive board.
2. `00-direction-table.png` — Light Table board.
3. `01-overview-archive-1280.png` — recommended Overview.
4. `02-library-years-1280.png` — Years with nested Albums and distinct date filters.
5. `02-library-album-1280.png` — explicit selected Album, logical membership.
6. `02-library-collections-1280.png` — cross-year direct-content Collections.
7. `03-review-exact-archive-1280.png` — large preview, copy strip, evidence and gated nomination.
8. `03-review-similar-archive-1280.png` — same visual language with review-only authority.
9. `03-review-similar-table-1280.png` — alternative two-up Light Table.
10. `04-backups-1280.png` — recovery readiness separated from catalogue health.
11. `05-component-states.png` — loading, empty, unavailable, date conflict, Unknown and keyboard-focus/selection concepts.

Additional 1920×1080 Overview/Library and 1040×840 Overview / 1040×900 Library renders demonstrate wider and narrower layouts. Dark Overview is also supplied. Mockups show only visible rows from a bounded page; they do not imply loading the whole library. No search bar, AI function, physical execution control or new backend capability was invented.

## Component and state contract

Spacing: 4/8/12/16/24/32 logical pixels. Sidebar 192px at standard/wide, 176px at narrow. Main padding 28px. Cards 14px corner radius, controls 8px. Standard controls 38–44px high; dense table rows at least 40px. Typography: Segoe UI Variable where available, otherwise Segoe UI; page 30–32px, section 20–24px, body 14px, metadata 12–13px. Tiny 10–11px text in the boards is ancillary labeling, not a model for required input or safety text.

Icons: small consistent outline glyphs paired with text, never the only source of meaning. No decorative AI sparkle or red destructive CTA. Full paths/hashes/UUIDs remain copyable in technical evidence with middle elision and full tooltip/copy access; action labels must not be elided. Dates retain precision: a year is shown as a year, never an invented day/month.

| State | Presentation and behavior |
|---|---|
| Loading | Skeleton placeholders and “Loading this page…”; retain prior navigation context, clear stale actionable selection, announce completion without focus theft. |
| Empty | Distinguish zero matching results from no Albums created. Explain safe next step; never imply files are missing. |
| Unavailable preview | Placeholder plus reason; source unchanged; no automatic hydration, scan or retry storm. |
| Error | Keep context; explain failed operation; explicit retry/details; never silently create or migrate a catalogue. |
| Unknown Date | Honest umbrella shelf includes unresolved items. Unknown-only excludes conflict cases. |
| Needs review | Material evidence conflict; amber text/icon and reason, preserved provenance. Never silently set a date. |
| Focus | 2px high-contrast blue outline with offset; focus separate from selected, nominated and approved state. |
| Selection | Stable logical identity; selected counter and 50-item mutation maximum; changing Album/Collection clears stale actionability. |
| Owner write | Actor required, optional reason, scope explicit, confirmation shows affected identity/count and logical-only effect. No hidden defaults or automatic decisions. |
| Health-gated action | Disabled with an accessible explanation; page may stay readable. Differentiate catalogue failure from absent independent backup. |

The mockup's single “Nominate selected…” entry represents the un-nominated state, not removal of later approval/reject/supersede/abstain controls. Those appear only when canonical state and health permit them. Archival/display scope selector and the existing actor/reason/confirmation contract are retained in implementation planning. No generic Undo is invented for append-only records; use the existing reversible membership or superseding-event operation where supported.

## Accessibility and layout validation

`layout-checks.json` records valid SVG rendering at all 16 concept sizes and font-measured bounds. `contrast-checks.json` measures token pairs; body/status/focus pairs meet the stated 4.5:1 text / 3:1 non-text targets. Decorative separators are not the sole control boundary. Disabled controls still carry text and explanation.

Visual QA inspected both boards, four main recommended screens, selected Album/Collections, dark Similar, and 1040/1920 layouts. Findings corrected before delivery: missing symbol glyphs, an unnecessarily truncated action label, insufficiently distinct alternative direction, and unused wide-screen height. No overlapping or off-canvas text was observed in the final reviewed renders. These are static layout checks, not Windows assistive-technology certification.

Proposed keyboard path: sidebar → page tabs/filter controls → bounded list/grid → detail/evidence → relevant actions → page navigation. Preserve F5, Alt+Up/Down, Ctrl+PageUp/Down, Enter/double-click, viewer Fit/100%/zoom/Escape. Use roving focus in item grids; announce row label/source/date, selection count and loading status. AccessibleName and accessibleDescription must expose full elided content. Never map Delete to physical removal. At narrow widths keep labels visible, use two/three-column grids and a deliberate detail drawer rather than overlaying controls. 1040px is demonstrated conceptually, not a newly promised supported product minimum. 200% text scaling, high-contrast Windows theme, screen readers and real keyboard traversal still require implementation-stage native tests.

## Staged Qt architecture — no backend rewrite

1. **Owner direction gate.** Review the boards, major flows, vocabulary and density. Agree the preferred direction and acceptance checklist before application-wide implementation.
2. **Presentation primitives.** Introduce scoped palette/spacing/type tokens, status label, evidence disclosure, action bar, empty/error/loading panels, bounded thumbnail delegate and navigation styling. Continue PySide6/Shiboken 6.11.2. Preserve native focus/accessibility behavior; avoid blanket styles that erase disabled/focus indicators.
3. **Read-only surfaces first.** Restyle Overview and Backups using the same `DesktopDataService` results and health gates. Keep existing schema/backup/device distinctions. Test displayed values and empty/unavailable states.
4. **Library composition.** Recompose Years/Album/Collection layouts using existing IDs, request tokens and services. Preserve four-tab preference mapping. Changes stay logical, explicit actor/confirmation, max 50 mutations, no folder effects. Keep schema-9 fallback and status filters. Add native rapid-selection/reload/stale-response tests before visual acceptance.
5. **Review composition.** Preserve `PreviewBinding` and `LibraryPreviewBinding`, canonical context/generation/physical ID/path matching and bounded decode limits. Load visible previews lazily, invalidate prior generations immediately and do not reconstruct worker ownership. Keep the established Worker and `_Worker` lifetime contracts and shutdown code unchanged. Nomination and approval remain separate.
6. **Measured acceptance and packaging gate.** Test 1280×840, 1920×1080, narrow layout and high-DPI/200% text; native keyboard/accessibility, rapid switching, long names, duplicate names, empty/failed data, separate exact/similar rules, actual frozen GUI normal close and restart. Run full native/hosted regression and original process-exit diagnostics. Package only under separate authority. C2 must pass independently; mockups never satisfy it.

Use QListView/QTableView delegates and bounded models only if separately implemented with parity tests; this design does not authorise wholesale replacement of validated widgets. Preserve pagination (25/50/100) and existing preview limits; do not make 50-item mutation cap an excuse to truncate read-only history. No whole-year preload, gratuitous animation or decorative blur/shadow work on the UI thread. Any proposed 120ms transition must respect reduced-motion and be removed if measured responsiveness regresses.

## Status and review boundary

| Check | Result |
|---|---|
| Source/feature/owner-feedback mapping | PASS |
| Two coherent visual directions and recommendation | PASS |
| High-fidelity four-screen minimum, SVG/PNG output | PASS — 16 concept renders |
| Static bounds, token contrast, visual inspection | PASS within recorded scope |
| Real application screenshot / native interaction evidence | BLOCKED in C2; none claimed here |
| Backend/runtime/authority contracts changed | NO |
| Application-wide implementation or merge | NOT PERFORMED |

G3/G4 historical audit criteria remain unavailable. Issue #9 and Qt 6.12 native shutdown remain unresolved. Design work makes no change to their verdicts, production state, branch protections, existing packages or release policy. Stop for Aether and owner review. Recommended next authority is a bounded presentation-only implementation stage after the owner selects a direction; it must explicitly preserve all reviewed safety and lifecycle contracts.
