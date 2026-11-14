# Linux lifecycle and rollback

The systemd user unit runs without root, uses `Restart=on-failure` and `RestartSec=5`, and does not create an additional watchdog. If the service must start before login, the administrator must explicitly enable user lingering.

For systemd upgrades, record the existing installed version, back up local configuration and the credential vault securely, and upgrade as the owning user. `mcptoai update` verifies the installed version before restarting an active service. On failure it does not restart. To roll back, reinstall the previous verified package version through the original pipx/pip mechanism and restart the user service. If a newer data schema is incompatible, stop the service and restore the pre-upgrade backup first. Do not delete the user profile.

For Docker, mount a persistent named volume at `/data`. Run the image as its built-in non-root UID 1000, use the container runtime restart policy, and pin image digests. Back up the volume before upgrading. Recreate the container with the new image using the same volume. For rollback, stop the new container and recreate using the previous verified image digest. If state was migrated incompatibly, restore the pre-upgrade volume snapshot first. Never run two agents against the same volume. The CLI package self-updater is not supported inside Docker.

The CI lifecycle smoke test recreates containers against one volume and verifies identity, settings, activity metadata and file permissions across a simulated image rollback. It does not claim to test an actual data migration or external runtime crash.

## Historical release regression (PR-G)

`linux-upgrade-regression.yml` builds source from immutable Git tags
`v0.2.6` and `v0.2.7` and compares each with the current PR checkout.
Historical `v0.2.7` actually declares Python package version **0.2.6**;
the matrix labels are source tags, not necessarily PyPI package versions.
The pip test installs historical/current/historical wheels in the same virtual
environment and verifies the same XDG configuration and paired-device vault.
Docker builds historical/current images and reuses a named volume. Historical
images mount it at `/home/mcptoai/.config`; current images default to `/data`.
The current Docker entrypoint detects explicit `/data` mounts. If both the
legacy volume (`/home/mcptoai/.config`) and a new empty `/data` volume are
mounted, it **copies** the legacy `mcptoai/` contents into `/data`, preserving
file modes and leaving the original untouched for rollback. It writes
`/data/.legacy-volume-copied` and logs the copy; subsequent starts do not
repeat it. If only the old volume is mounted, it continues to use the legacy
path and logs a warning. A nonempty `/data` is never overwritten; when legacy data is also present
and no marker exists, startup fails closed rather than silently mixing profiles.

Docker file tools require a separate host bind mount at `/workspace`.
Create the host folder first with `mkdir -p "$HOME/mcptoai-workspace"`.
The old container-local Desktop/Documents/Downloads defaults were not persistent
host folders. Without a mounted `/workspace` (or explicit `MCP_ALLOWED_ROOTS`),
filesystem access fails closed and `mcptoai doctor` warns. `/data` is for
persistent agent state, **not** for user file access.

Recommended new run (replace the version with the approved digest/tag):

```sh
docker run -d --name mcptoai --restart unless-stopped \
  -v mcptoai-data:/data \
  -v "$HOME/mcptoai-workspace:/workspace" \
  ghcr.io/mcptoai/mcptoai:VERSION
```

For a one-time legacy migration, additionally mount the **original** legacy
volume at `/home/mcptoai/.config` while keeping the new `/data` mount.
Remove that legacy mount only after validating the copy and pairing.
Do not attach both old and new containers simultaneously to the same volume.
The tests are offline: they verify stored pairing state, not a live OAuth
exchange or relay handshake. Historical source tag `v0.2.7` still declares
Python package version `0.2.6`.
