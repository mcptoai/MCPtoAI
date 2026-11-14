# Linux 0.3.1 release plan — approval gate

Status: **draft, not released**. PR #91 consolidates issues #85–#89.

## Pre-release verification

- CI on final PR head: Linux, shared-core, Desktop agent source, Docker smoke/lifecycle, historical upgrade, release dry-run and security checks green.
- Docker isolated live test (never touch production service): `docker build --build-arg SOURCE_COMMIT=<full-frozen-sha> ...`; run with no mount (roots empty and doctor warns), then `-v ~/folder:/workspace` (root becomes `/workspace` and doctor OK). Check model system prompt roots, no `.` path preflight refusal, default provider with zero/one/many keys, and no key values in logs.
- Check `mcptoai --version` includes the **full frozen commit** (not `unknown`); compare to image provenance. Test Docker login with a disposable test account; verify hostname is shown instead of account subject and no systemd guidance. Inspect `/data/mcp-discovery.json` as UID 1000: mode `0600` after creation and replacement with umask 022. Test persistence and migration/rollback.
- Run secret scan on exported files, compare `linux-agent/` and `shared-core/` source trees byte-for-byte between Core frozen commit and public export.

## Mandatory publishing order

1. Freeze Core source SHA after CI and code review. Update package version to 0.3.1 before freeze, validate all version references and changelog.
2. Open **separate public export PR** for exact frozen `linux-agent/` + `shared-core/`. Scan secrets and pass public CI. **Merge public export first**; verify public source content identical to Core frozen commit.
3. Only then create signed `linux-v0.3.1` tags in both public and Core on commits containing matching Linux source. Verify tag content, provenance and signing. Never retroactively move a published tag.
4. Publish signed PyPI `mcptoai==0.3.1`, GHCR `ghcr.io/mcptoai/mcptoai:0.3.1` (amd64/arm64, embedded commit, SBOM, provenance) and public GitHub Release. Do not mark Linux Latest; Desktop remains Latest.
5. Verify public download pages and documentation only after approved deployment. Web #90 is separate PR and **must not deploy without explicit approval**, whether alongside 0.3.1 or a later web release.

## Rollback

Retain immutable 0.3.0 artifacts and old config volume; no tag mutation or `latest` rewrite. Roll back by pinning the previous image and preserving `/data` backups. Verify migration compatibility before switching.
