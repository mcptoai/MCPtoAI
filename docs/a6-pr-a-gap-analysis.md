# A6 — PR A outstanding items and A2 gap analysis

PR #12 (A2) was scoped in its merged diff to signed agent integrity,
updater manifests/blockmaps, backup scanning and CI packaging checks. Its PR
body explicitly listed **Linux build-info as pending**. It did not change the
Windows developer-path regular expression or add its single-backslash test.
Consequently the user-requested items 8 and 9 were **not implemented in A2**;
the earlier scope/merge review treated pending work as completed. This is a
tracking/acceptance failure, not evidence of a later code regression.

A6 adds Windows path coverage and Linux CLI build-info. For reproducible
Linux wheel/sdist releases, run `python linux-agent/scripts/write-build-info.py`
from the checked-out source **before packaging**; the package-data declaration
includes the resulting JSON. In source checkouts without metadata, the CLI
falls back to the Git commit and working-tree dirty state; without either,
it reports `unknown` rather than inventing provenance.

The 404 answer-sync stop list is **per running journal instance**, and is
reset when the agent process restarts. Transient non-404 errors still retry.
A successful turn is defined as a `done` event preceded by a `text` event for
the same turn; this avoids clearing prior errors for failed or interrupted turns.

No installers, OTA metadata or server deployment are changed in this PR.
