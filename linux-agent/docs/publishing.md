# Linux release publishing — manual linux-v* tag dispatch

Only `.github/workflows/publish-linux-artifacts.yml` publishes Linux artifacts.
It runs by **manual workflow_dispatch only**; a tag push, PR merge or branch
push does not publish. In GitHub Actions select **Run workflow**, then set
**Use workflow from** to the intended existing `linux-vX.Y.Z` tag (not `main`).
Enter `version=X.Y.Z` and the literal `confirmation=PUBLISH`. The workflow
requires the selected ref to be a tag, requires the tag to equal `linux-v` plus the
input version, and verifies `linux-agent/pyproject.toml` has that version.
The tag must contain the workflow itself. The Linux release gate checks the Linux source version and metadata-derived runtime version; Desktop version gates remain independent. Create the release tag only after
this workflow has merged and the desired version has been committed.

Both publishing jobs use the GitHub Actions environment
`linux-production-publish`, whose deployment branch/tag policy allows `linux-v*`
tags. Configure the **PyPI Trusted Publisher** for repository
`mcptoai/MCPtoAI_Core`, workflow `publish-linux-artifacts.yml`, and environment
**`linux-production-publish`** (exact spelling). Its environment identity
must match the workflow's OIDC claim; do not leave this field blank.

**GitHub Team private repository limitation:** environment required reviewers
are unavailable. The `linux-v*` environment policy limits allowed refs, but it is
**not a human approval gate**. `PUBLISH` is a deliberate operator confirmation,
not independent authorization; anyone permitted to dispatch workflows against
the release tag can supply it. Restrict Actions and tag creation permissions,
and obtain project-owner approval before every manual release run.

The workflow builds the `mcptoai` wheel and sdist, publishes to PyPI using
OIDC, then builds `linux/amd64` and `linux/arm64` GHCR images with BuildKit
provenance and SBOM, signs the digest using cosign and verifies the keyless
signature against the selected `linux-vX.Y.Z` tag identity. It does not update
`latest`.

PyPI and GHCR publishing are sequential, **not atomic**: if GHCR fails after
PyPI succeeds, the PyPI version cannot be republished. Investigate and recover
with an explicitly authorized procedure; never overwrite an existing image
version tag. Verify digest, signature and both architectures before announcing
any release. Merging this PR alone does not publish anything.

**Release preparation:** the GitHub environment currently allows `v*`; after this PR merges, change its custom deployment tag rule to `linux-v*` before any publishing dispatch. Do not change the live rule before merge. Desktop tags remain `vX.Y.Z` and are not Linux release refs.
