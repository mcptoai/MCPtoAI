"""Build contracts for shared-core packaging without changing public release dependencies."""
from pathlib import Path


def test_shared_core_has_no_runtime_mcp_sdk_dependency():
    import mcptoai_core.persistence as persistence
    import mcptoai_core.session_state as session_state
    assert persistence.load_receipt_payload({"items": {"a": {}}})["a"] == {}
    assert callable(session_state.begin_turn)


def test_desktop_pyinstaller_explicitly_collects_shared_core():
    root = Path(__file__).resolve().parents[2]
    spec = (root / "device-agent" / "mcptoai-agent.spec").read_text()
    assert "collect_all('mcptoai_core')" in spec


def test_linux_docker_builds_from_repository_context_without_core_pypi_dependency():
    root = Path(__file__).resolve().parents[2]
    docker = (root / "linux-agent" / "Dockerfile").read_text()
    assert "pip wheel" in docker
    assert "COPY shared-core/mcptoai_core" in docker
    # A private shared-core package must not be added to the published Linux
    # dependency list until its distribution and container wheelhouse are ready.
    import tomllib
    with (root / "linux-agent" / "pyproject.toml").open("rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]
    assert not any(dep.startswith("mcptoai-core") for dep in deps)


def test_desktop_build_installs_checked_out_shared_core():
    root = Path(__file__).resolve().parents[2]
    setup = (root / "device-agent" / "scripts" / "setup-build-env.py").read_text()
    assert "ROOT.parent / 'shared-core'" in setup
    assert "'--no-deps', '-e'" in setup


def test_linux_docker_smoke_job_is_path_gated():
    root = Path(__file__).resolve().parents[2]
    ci = (root / '.github/workflows/client-ci.yml').read_text()
    assert 'linux-docker-smoke:' in ci
    assert "- 'linux-agent/**'" in ci
    assert "- 'shared-core/**'" in ci
    assert 'docker build -f linux-agent/Dockerfile' in ci
    assert 'import mcptoai_core' in ci
