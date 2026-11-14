# MCPtoAI Linux 0.3.0 — release candidate notes (not yet published)

First separately versioned Linux release. Linux Git tags use `linux-vX.Y.Z`,
independent of Desktop `vX.Y.Z` tags. PyPI distribution: `mcptoai` 0.3.0;
container: `ghcr.io/mcptoai/mcptoai:0.3.0` (only after explicit approval).

- Persistent Docker profile is now mounted at `/data` rather than
  `/home/mcptoai/.config`. The container runs as non-root UID 1000.
- New installation: `docker run -it --rm -v mcptoai-data:/data ghcr.io/mcptoai/mcptoai:0.3.0 login`
  followed by `docker run -d --name mcptoai --restart unless-stopped -v mcptoai-data:/data ghcr.io/mcptoai/mcptoai:0.3.0`.
- Legacy migration: stop the old container, back up its volume, then run
  `docker run --rm -v mcptoai:/home/mcptoai/.config -v mcptoai-data:/data ghcr.io/mcptoai/mcptoai:0.3.0 --help`
  with an empty `mcptoai-data` volume. Replace `mcptoai` with the actual old
  volume name. The original volume remains unchanged for rollback.
- A migration marker prevents repeat copies. A nonempty target with legacy
  data and no marker fails closed instead of overwriting existing state.
- Upgrades and rollback preserve pairing and activity state in regression
  tests. Restore a backup if a future data schema is not backward compatible.
- Docker images are immutable: update by pulling and recreating the container.
  `mcptoai update` inside Docker does not update the image.

This is a release candidate document; no tag, PyPI upload or GHCR push is
performed by CI dry runs. See `linux-agent/README.md` for full commands.

## GHCR latest baseline (read-only)

Recorded from the independent Ubuntu verification run on 2026-11-14 (GitHub Actions run `43532724754`):

- `ghcr.io/mcptoai/mcptoai:latest` manifest-list digest: `sha256:acaa4f7516ab1eca6373aee62d4495b53f4527b722b4182c921f585142cc5d06`
- `ghcr.io/mcptoai/mcptoai:0.3.0` manifest-list digest: `sha256:f6ee7d63558e882ab19fca2d6c3d2e1e425ebf05a700eba75eb0a845e94e460f`

This is a post-publication snapshot, **not proof of the pre-release latest digest**. Future release checks must compare the read-only `latest` digest against this recorded baseline before and after publishing.
