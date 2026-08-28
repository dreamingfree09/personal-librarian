## Summary

Describe the focused change and why it is needed.

## Validation

List the checks run and their results.

## Checklist

- [ ] The change has a focused scope.
- [ ] Tests were added or updated where behaviour changed.
- [ ] Privacy, preservation, and non-destructive safety boundaries were considered.
- [ ] No personal data, private paths, credentials, production databases, backups, or media are included.
- [ ] Documentation was updated where needed.
- [ ] `PROJECT_TRUTH.md` was considered if architecture or safety boundaries changed.
- [ ] `python -m unittest discover -s tests -v` passed, or an exception is explained above.
- [ ] `git -c core.whitespace=cr-at-eol diff --check` passed.
