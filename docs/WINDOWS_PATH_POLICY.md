# Supported Windows path syntax

All common catalogue, configuration, import, production-root and desktop-state
entry points use the non-I/O `PathSafetyPolicy`. Device namespaces are rejected
before UNC handling. Relative-path bases receive the same classification.
Supported ordinary drive-absolute and UNC paths remain available; operation-specific
maintenance and state-writing contracts may impose stricter filesystem requirements.

Validation is lexical, not proof of physical containment. It does not authorise
access to retired storage or replace reparse/identity checks at the I/O boundary.
Unsupported namespaces, ambiguous drive-relative paths, malformed shares and
invalid Windows components fail closed. No namespace target is probed to classify it.

Tests cover the syntax matrix, relative bases and no-I/O spies at configuration,
catalogue, import and application-state entry points. Supplementary native tests
use only temporary synthetic roots. Detailed baseline reproductions remain private.
