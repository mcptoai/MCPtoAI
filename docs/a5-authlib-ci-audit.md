# A5 — Authlib / CI warning audit

## Reproduced (2026-11-02)

The Device Agent's existing environment (`fastmcp==2.14.7`, `Authlib==1.8.0`,
`joserfc==1.7.5`) emits an `AuthlibDeprecationWarning` on import from
`fastmcp/server/auth/providers/jwt.py`: FastMCP imports `authlib.jose`, which
Authlib deprecates in favor of `joserfc`. No first-party `authlib.jose`
imports were found in agent source.

Device Agent suite: **458 passed, 6 skipped, 56 subtests passed, 1 warning**.
The warning originates in a third-party package. Simply adding `joserfc` does
not fix FastMCP's import, and globally suppressing deprecation warnings would
hide future regressions. No dependency major-version upgrade should be shipped
without testing Mac, Windows, Linux, package builds and authentication flows.

## Follow-up

1. Evaluate a FastMCP release that migrates its imports to `joserfc` while
   preserving the supported FastMCP/MCP APIs and all supported Python versions.
2. Run full Device Agent and Linux Agent CI and packaging smoke tests.
3. If upstream has not migrated, track the warning and consider a **narrow**
   third-party-only filter with an explicit expiry/revisit condition; do not
   suppress unrelated warnings.
4. Investigate any separate CI warnings against actual job logs before making
   changes. This audit does not claim those warnings are resolved.

## Latest release investigation (2026-11-02)

PyPI exposes FastMCP **4.1.5** as latest, versus installed **2.14.7**.
Inspected official PyPI wheel archives for `fastmcp==4.1.5` and
`fastmcp-slim==4.1.5`: the current auth provider source imports `joserfc`,
not `authlib.jose`. Thus the upstream deprecation appears resolved in 4.1.5.
However, 4.x introduces a package split (`fastmcp` depends on `fastmcp-slim`)
and crosses two major versions; this is **not** a safe automatic update.
No release-notes-based compatibility guarantee or full suite on 4.1.5 has yet
been established. Retain the current 2.x dependency until a separately tested
upgrade PR. Do not patch vendored FastMCP or suppress CI warnings.
