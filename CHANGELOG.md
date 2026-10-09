# Changelog

## 0.1.0 — unreleased

Dry-run tab checks, explicit closure, keep patterns and a last-page guard. Local
state holds digests only. Portable scheduling templates are opt-in and report-only.

- Unavailable endpoints skip quietly with exit 0; `--quiet` suppresses routine timer output.
- Transport failures preserve state; malformed CDP responses remain errors.
- Document observed-navigation grace and offline-observation limitations.
- Endpoint errors name the real cause; the state file path is checked before any page is listed or closed.
