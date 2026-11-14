# MCPtoAI Linux v0.3.0

Linux CLI and Docker release, versioned independently from MCPtoAI Desktop. No Desktop installer is included.

## Install the Linux CLI (Python 3.11+)

```bash
python3 -m pip install 'mcptoai==0.3.0'
mcptoai --version
mcptoai login
```

For an isolated installation, use `pipx install 'mcptoai==0.3.0'` instead.

## Install with Docker

```bash
docker pull ghcr.io/mcptoai/mcptoai:0.3.0
docker run -it --rm -v mcptoai-data:/data ghcr.io/mcptoai/mcptoai:0.3.0 login
docker run -d --name mcptoai --restart unless-stopped -v mcptoai-data:/data ghcr.io/mcptoai/mcptoai:0.3.0
```

The container runs as UID 1000. `/data` is the persistent configuration and identity location. Docker does not update itself through `mcptoai update`: pull a newer versioned image and recreate the container with the same `/data` volume.

## Upgrade from Docker 0.2.x: important `/data` migration

Previously, persistent configuration was mounted at `/home/mcptoai/.config`. Starting with 0.3.0, mount a **new empty** volume at `/data`. First stop the old container and back up its original volume. Assuming the old named volume is `mcptoai`:

```bash
docker stop mcptoai
docker rm mcptoai
# Back up the old named volume using your normal Docker volume backup procedure.
docker volume create mcptoai-data
docker run --rm \
  -v mcptoai:/home/mcptoai/.config \
  -v mcptoai-data:/data \
  ghcr.io/mcptoai/mcptoai:0.3.0 --help
# Check the migrated configuration before running the service.
docker run -d --name mcptoai --restart unless-stopped \
  -v mcptoai-data:/data ghcr.io/mcptoai/mcptoai:0.3.0
```

Replace `mcptoai` with the **actual** legacy volume name; inspect `docker inspect <old-container-name>` before removing the old container if unsure. The old volume is retained for rollback. The migration creates a `.legacy-volume-copied` marker; reruns do not copy again. A nonempty target without a migration marker fails closed rather than overwriting existing data. Keep the original volume backup until the new agent is confirmed paired and working. For a bind-mounted legacy directory, adapt the source mount accordingly.

## Release integrity

- Release source commit: `d06023d2c6bd9e91b722a13980857dad234aaea7`
- Signed Linux Git tag: `linux-v0.3.0`
- PyPI: https://pypi.org/project/mcptoai/0.3.0/
- GHCR: `ghcr.io/mcptoai/mcptoai:0.3.0`
- Immutable multi-platform image digest: `sha256:f6ee7d63558e882ab19fca2d6c3d2e1e425ebf05a700eba75eb0a845e94e460f`
- Image signature verified with Cosign using the exact GitHub Actions release workflow certificate identity. BuildKit SBOM and provenance are available within the signed OCI index; provenance source revision matches the release commit. Separately Cosign-signed SBOM/SLSA attestations are **not** claimed for this release.
- `latest` was not updated by this release. Recorded post-release `latest` baseline: `sha256:acaa4f7516ab1eca6373aee62d4495b53f4527b722b4182c921f585142cc5d06`.

Linux versioning is independent of Desktop v0.2.x. Docker 0.3.0 supports linux/amd64 and linux/arm64.
