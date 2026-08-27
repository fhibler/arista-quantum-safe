"""Tests for Makefile topology generation and lifecycle targets."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from lab.topology_contract import (
    ALPINE_VERSION,
    DEFAULT_CEOS_IMAGE,
    DEFAULT_MGMT_IPV6_SUBNET,
    DEFAULT_MGMT_SUBNET,
    GEN_TOPOLOGY_PATH,
    OPENSSL_PQC_TLS_GROUPS,
    TOPOLOGY_PATH,
    load_topology,
    validate_lab_image_pins,
    validate_topology,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"


def _run_make(*targets: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["make", "-C", str(REPO_ROOT), *targets]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=check,
    )


def _makefile_recipe(target: str) -> str:
    """Return one Makefile target's header and recipe lines (not neighbor-dependent)."""
    collected: list[str] = []
    capturing = False
    for line in MAKEFILE.read_text(encoding="utf-8").splitlines():
        if capturing:
            if line.startswith("\t"):
                collected.append(line)
                continue
            break
        if not line.startswith(f"{target}:"):
            continue
        rest = line[len(target) :]
        if rest.startswith(":") and (len(rest) == 1 or rest[1] in " \t#"):
            capturing = True
            collected.append(line)
    if not capturing:
        raise AssertionError(f"Makefile has no target {target!r}")
    return "\n".join(collected)


def test_makefile_exists() -> None:
    assert MAKEFILE.is_file()


@pytest.mark.parametrize(
    "target",
    [
        "help",
        "gen-topo",
        "validate-topo",
        "test",
        "check-ceos-image",
        "check-containerlab",
        "import-ceos",
        "import-ceos-help",
        "download-ceos",
        "download-ceos-help",
        "build-lab-images",
        "build-radius",
        "build-syslog",
        "build-kme",
        "build-test-runner",
        "test-radius-image",
        "test-syslog-image",
        "test-kme-image",
        "verify-test-runner-image",
        "deploy-kme",
        "wait-kme-pool",
        "deploy",
        "destroy",
        "clean",
        "reset",
        "redeploy",
        "inspect",
        "ssh-ceos1-both",
        "ssh-ceos2-pqc",
        "ssh-ceos3-qkd",
        "shell-test-runner",
        "install-quadra",
        "test-lab",
        "test-lab-runner",
        "test-radsec",
        "test-kme",
        "test-eapi",
        "test-ssh",
        "test-openconfig",
        "test-syslog",
        "test-macsec-dot1x",
        "test-macsec-dot1x-reauth",
        "test-macsec-qkd",
        "test-hosts",
    ],
)
def test_make_help_lists_target(target: str) -> None:
    result = _run_make("help")
    assert target in result.stdout


def test_gen_topo_default_image() -> None:
    _run_make("gen-topo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
    assert GEN_TOPOLOGY_PATH.is_file()
    data = load_topology(GEN_TOPOLOGY_PATH)
    image = data["topology"]["kinds"]["arista_ceos"]["image"]
    assert image == DEFAULT_CEOS_IMAGE
    assert data["mgmt"]["ipv4-subnet"] == DEFAULT_MGMT_SUBNET
    assert data["mgmt"]["ipv6-subnet"] == DEFAULT_MGMT_IPV6_SUBNET


def test_gen_topo_custom_ceos_image() -> None:
    custom = "ceos:5.0.0F"
    _run_make("gen-topo", f"CEOS_IMAGE={custom}")
    data = load_topology(GEN_TOPOLOGY_PATH)
    assert data["topology"]["kinds"]["arista_ceos"]["image"] == custom
    errors = validate_topology(data, ceos_image=custom)
    assert errors == []


def test_gen_topo_custom_mgmt_subnet() -> None:
    custom = "192.168.28.0/24"
    _run_make("gen-topo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={custom}")
    data = load_topology(GEN_TOPOLOGY_PATH)
    assert data["mgmt"]["ipv4-subnet"] == custom
    assert data["topology"]["nodes"]["radius"]["mgmt-ipv4"] == "192.168.28.50"
    errors = validate_topology(data, mgmt_subnet=custom)
    assert errors == []


def test_gen_topo_custom_mgmt_ipv6_subnet() -> None:
    custom = "2001:db8:99::/64"
    _run_make(
        "gen-topo",
        f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}",
        f"MGMT_IPV6_SUBNET={custom}",
    )
    data = load_topology(GEN_TOPOLOGY_PATH)
    assert data["mgmt"]["ipv6-subnet"] == custom
    assert data["topology"]["nodes"]["radius"]["mgmt-ipv6"] == "2001:db8:99::50"
    errors = validate_topology(data, mgmt_ipv6_subnet=custom)
    assert errors == []


def test_gen_topo_substitutes_placeholders() -> None:
    _run_make("gen-topo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
    src = TOPOLOGY_PATH.read_text(encoding="utf-8")
    gen = GEN_TOPOLOGY_PATH.read_text(encoding="utf-8")
    assert "${CEOS_IMAGE}" in src
    assert "${MGMT_SUBNET}" in src
    assert "${MGMT_IPV6_SUBNET}" in src
    assert "${CEOS_IMAGE}" not in gen
    assert "${MGMT_SUBNET}" not in gen
    assert "${MGMT_IPV6_SUBNET}" not in gen
    assert f"image: {DEFAULT_CEOS_IMAGE}" in gen
    assert f"ipv4-subnet: {DEFAULT_MGMT_SUBNET}" in gen
    assert f"ipv6-subnet: {DEFAULT_MGMT_IPV6_SUBNET}" in gen


def test_validate_topo_passes_via_make() -> None:
    _run_make("gen-topo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
    result = _run_make(
        "validate-topo",
        f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}",
        f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}",
        f"MGMT_IPV6_SUBNET={DEFAULT_MGMT_IPV6_SUBNET}",
    )
    assert result.returncode == 0
    assert GEN_TOPOLOGY_PATH.is_file()


def test_validate_topo_fails_on_contract_violation(tmp_path: Path) -> None:
    _run_make("gen-topo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
    broken = tmp_path / "broken.clab.yml"
    broken.write_text(GEN_TOPOLOGY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    data = yaml.safe_load(broken.read_text(encoding="utf-8"))
    data["topology"]["nodes"]["ceos1-both"]["mgmt-ipv4"] = "10.0.0.1"
    broken.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")

    errors = validate_topology(load_topology(broken))
    assert any("ceos1-both mgmt-ipv4" in err for err in errors)


def test_render_preserves_yaml_structure() -> None:
    _run_make("gen-topo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
    data = yaml.safe_load(GEN_TOPOLOGY_PATH.read_text(encoding="utf-8"))
    assert data["topology"]["nodes"]["radius"]["image"] == "quantum-safe-radius:latest"
    assert data["topology"]["kinds"]["arista_ceos"]["image"] == DEFAULT_CEOS_IMAGE


def test_import_ceos_help_output() -> None:
    result = _run_make("import-ceos-help")
    assert "docker import download/cEOS64-lab-" in result.stdout
    assert "docker import download/cEOSarm-lab-" in result.stdout
    assert "make download-ceos" in result.stdout


def test_download_ceos_help_output() -> None:
    result = _run_make("download-ceos-help")
    assert "ARISTA_TOKEN" in result.stdout
    assert "ardl get eos" in result.stdout
    assert ".env.example" in result.stdout


def test_download_ceos_fails_without_token(tmp_path: Path) -> None:
    dotenv = REPO_ROOT / ".env"
    had_dotenv = dotenv.exists()
    prior = dotenv.read_text(encoding="utf-8") if had_dotenv else None
    dotenv.unlink(missing_ok=True)
    empty_download = tmp_path / "empty-download"
    empty_download.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "ARISTA_TOKEN"}
    env["CEOS_DOWNLOAD_DIR"] = str(empty_download)
    env["ARISTA_TOKEN"] = ""
    try:
        result = _run_make("download-ceos", env=env, check=False)
        assert result.returncode != 0
        assert "ARISTA_TOKEN not set" in result.stdout + result.stderr
    finally:
        if had_dotenv and prior is not None:
            dotenv.write_text(prior, encoding="utf-8")


def test_download_ceos_loads_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Token in .env satisfies check when shell env has no ARISTA_TOKEN."""
    dotenv = REPO_ROOT / ".env"
    had_dotenv = dotenv.exists()
    prior = dotenv.read_text(encoding="utf-8") if had_dotenv else None
    dotenv.write_text("ARISTA_TOKEN=fake-token-from-dotenv\n", encoding="utf-8")
    empty_download = tmp_path / "empty-download"
    empty_download.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "ARISTA_TOKEN"}
    env["CEOS_DOWNLOAD_DIR"] = str(empty_download)
    try:
        result = _run_make("download-ceos", env=env, check=False)
        combined = result.stdout + result.stderr
        assert "ARISTA_TOKEN not set" not in combined
    finally:
        if had_dotenv and prior is not None:
            dotenv.write_text(prior, encoding="utf-8")
        else:
            dotenv.unlink(missing_ok=True)


def test_download_ceos_recipe_loads_dotenv_via_makefile() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "-include .env" in content


def test_download_ceos_recipe_uses_download_dir() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "CEOS_DOWNLOAD_DIR ?=" in content
    assert 'cd "$(CEOS_DOWNLOAD_DIR)"' in content
    assert '--output "."' in content
    assert 'import eos_downloader' in content
    assert "Tarball already present" in content
    assert "make import-ceos" in content


def test_import_ceos_recipe_imports_local_tarball() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "import-ceos:" in content
    assert 'docker import "$$CEOS_TAR" "$(CEOS_IMAGE)"' in content


def test_download_ceos_recipe_installs_eos_downloader_when_missing() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "eos-downloader>=0.16.0" in content
    assert "import eos_downloader" in content
    assert "rm -rf .venv && python3 -m venv .venv" in content
    assert 'PY="$$ROOT/.venv/bin/python3"' in content
    assert "! .venv/bin/ardl" not in content
    assert ".venv/bin/ardl" not in content
    assert "eos_downloader.cli.cli" in content


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_check_ceos_image_fails_when_missing() -> None:
    missing = "ceos:nonexistent-test-tag"
    result = _run_make("check-ceos-image", f"CEOS_IMAGE={missing}", check=False)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "not found" in combined.lower()
    assert "docker import download/cEOS64-lab-" in combined
    assert "import-ceos" in _makefile_recipe("check-ceos-image")


def test_check_ceos_image_imports_when_missing() -> None:
    recipe = _makefile_recipe("check-ceos-image")
    assert "importing from" in recipe
    assert "SKIP_CEOS_IMPORT" in recipe
    assert "import-ceos" in recipe


def test_image_verify_targets_print_test_headers() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "PRINT_VERIFY_HEADER" in content
    assert "print_test_header" in content
    titles = {
        "check-ceos-image": "cEOS image verification",
        "test-radius-image": "radius image verification",
        "test-syslog-image": "syslog image verification",
        "test-kme-image": "kme image verification",
        "verify-test-runner-image": "test-runner image verification",
    }
    for target, title in titles.items():
        recipe = _makefile_recipe(target)
        assert "$(PRINT_VERIFY_HEADER)" in recipe
        assert title in recipe


def test_deploy_verbose_enables_plain_docker_build_and_debug_containerlab() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "BAKE_PROGRESS" in content
    assert "--progress=plain" in content
    assert "CLAB_DEPLOY_FLAGS" in content
    assert "deploy: gen-topo check-containerlab build-lab-images check-ceos-image" in content
    deploy = _makefile_recipe("deploy")
    assert "CLAB_DEPLOY_FLAGS" in deploy
    assert "deploy-kme $(MAKE_VERBOSE)" in deploy
    assert "wait-kme-pool $(MAKE_VERBOSE)" in deploy
    assert "docker buildx bake" in content
    assert "BAKE" in content
    assert "docker buildx build --load" not in content


def test_source_openssl_path_removed() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "USE_SOURCE_OPENSSL" not in content
    assert "Dockerfile.source-openssl" not in content
    assert "docker/openssl/Dockerfile" not in content
    assert "quantum-safe-openssl" not in content
    assert "build-openssl" not in content
    assert "MGMT_IP_RADIUS" not in content
    assert not (REPO_ROOT / "docker" / "openssl").exists()
    assert not (REPO_ROOT / "docker" / "radius" / "Dockerfile.source-openssl").exists()
    assert not (REPO_ROOT / "docker" / "syslog" / "Dockerfile.source-openssl").exists()
    assert not (REPO_ROOT / "docker" / "test-runner" / "Dockerfile.source-openssl").exists()
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "USE_SOURCE_OPENSSL" not in env_example
    assert validate_lab_image_pins(REPO_ROOT) == []
    for doc in [REPO_ROOT / "README.md", *(REPO_ROOT / "docs").rglob("*.md")]:
        text = doc.read_text(encoding="utf-8")
        assert "USE_SOURCE_OPENSSL" not in text, doc
        assert "build-openssl" not in text, doc
    result = _run_make("-n", "build-lab-images")
    combined = result.stdout + result.stderr
    assert "docker buildx bake" in combined
    assert "docker-bake.hcl" in combined
    assert f"ALPINE_VERSION={ALPINE_VERSION}" in combined
    assert "--set '*.platform=linux/" in combined
    result = _run_make("help")
    assert "build-openssl" not in result.stdout


def test_makefile_shares_openssl_pqc_group_verify() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    expected = "OPENSSL_PQC_TLS_GROUPS := " + " ".join(OPENSSL_PQC_TLS_GROUPS)
    assert expected in content
    assert "verify_openssl_pqc_tls_groups" in content
    for target in ("test-radius-image", "test-syslog-image", "verify-test-runner-image"):
        result = _run_make("-n", target)
        combined = result.stdout + result.stderr
        assert "openssl list -tls-groups" in combined
        for group in OPENSSL_PQC_TLS_GROUPS:
            assert group in combined


def test_makefile_defines_check_containerlab() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "CLAB_MIN_VERSION ?=" in content
    assert "CLAB_VERSION" not in content
    assert "check-containerlab:" in content
    assert "not installed" in content
    assert "deploy-kme: check-containerlab" in content
    assert "destroy: check-containerlab" in content
    assert "inspect: check-containerlab" in content


def test_check_containerlab_fails_when_not_installed(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("make", "bash", "sed", "sort", "head"):
        src = shutil.which(name)
        if src:
            (bindir / name).symlink_to(src)
    env = {**os.environ, "PATH": str(bindir)}
    result = _run_make("check-containerlab", check=False, env=env)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "not installed" in combined.lower()


@pytest.mark.skipif(shutil.which("containerlab") is None, reason="containerlab not in PATH")
def test_check_containerlab_passes_when_version_ok() -> None:
    result = _run_make("check-containerlab", check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "Containerlab" in combined
    assert "installed" in combined.lower()


def test_check_containerlab_fails_when_version_too_old(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake_clab = bindir / "containerlab"
    fake_clab.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = version ]; then\n'
        '  printf "%s\\n" "    version: 0.79.0"\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_clab.chmod(0o755)
    for name in ("make", "bash", "sed", "sort", "head"):
        src = shutil.which(name)
        if src:
            (bindir / name).symlink_to(src)
    env = {**os.environ, "PATH": str(bindir)}
    result = _run_make("check-containerlab", "CLAB_MIN_VERSION=99.99.0", check=False, env=env)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "too old" in combined.lower() or "need >=" in combined


def test_make_test_recipe_runs_pytest() -> None:
    result = _run_make("-n", "test")
    assert "-m pytest" in result.stdout


def test_validate_topo_uses_cli_module() -> None:
    result = _run_make("-n", "gen-topo")
    assert "lab.render_topo" in result.stdout
    result = _run_make("-n", "validate-topo")
    assert "lab.validate_topo" in result.stdout
    assert "--mgmt-ipv6-subnet" in result.stdout


def test_makefile_defines_mgmt_subnet() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "MGMT_SUBNET   ?=" in content
    assert "172.20.127.0/24" in content
    assert "MGMT_IPV6_SUBNET ?=" in content
    assert "2001:db8:127::/64" in content
    assert "prepare-ceos-monitor" not in content
    assert "prepare-mgmt-net" not in content


@pytest.mark.parametrize(
    ("target", "module", "forbidden"),
    [
        ("test-radsec", "lab.test_radsec", None),
        ("test-kme", "lab.test_kme", "--section kme"),
        ("test-eapi", "lab.test_eapi", None),
        ("test-ssh", "lab.test_ssh", None),
        ("test-openconfig", "lab.test_openconfig", None),
        ("test-syslog", "lab.test_syslog", None),
        ("test-macsec-dot1x", "lab.test_macsec_dot1x", None),
        ("test-macsec-qkd", "lab.test_macsec_qkd", None),
        ("test-hosts", "lab.test_hosts", "lab.test_lab"),
    ],
)
def test_live_check_delegates_to_python_module(target: str, module: str, forbidden: str | None) -> None:
    result = _run_make("-n", target)
    combined = result.stdout + result.stderr
    assert module in combined
    assert "-u VERBOSE" in combined
    if forbidden:
        assert forbidden not in combined
    verbose = _run_make("-n", "VERBOSE=1", target)
    assert "VERBOSE=1" in verbose.stdout + verbose.stderr


def test_clean_recipe_removes_artifacts_and_images() -> None:
    result = _run_make("-n", "clean")
    clean = result.stdout + result.stderr
    assert "containerlab destroy" in clean
    assert "rm -rf lab/.gen lab/.gen.*" in clean
    assert 'rm -rf "$(CEOS_DOWNLOAD_DIR)"' not in clean
    assert "rm -rf .venv .pytest_cache" in clean
    assert "docker images" in clean
    assert "quantum-safe-openssl" not in clean
    assert "quantum-safe-builder" in clean
    assert "quantum-safe-runtime" in clean
    assert "quantum-safe-radius" in clean
    assert "quantum-safe-syslog" in clean
    assert "quantum-safe-kme" in clean
    assert "docker rmi" in clean
    assert "rm -f .env" not in clean
    assert "download/ and .env preserved" in clean
    assert "quantum-safe-mgmt" in clean
    assert "docker network rm" in clean
    assert "Cleaning lab logs" in clean
    assert "/logs/radius /logs/syslog" in clean
    assert clean.index("Cleaning lab logs") < clean.index("Removing Docker images")
    assert "buildx prune" not in clean


def test_reset_recipe_resets_git_worktree() -> None:
    result = _run_make("-n", "reset")
    reset = result.stdout + result.stderr
    assert "git reset --hard HEAD" in reset
    assert "git clean -fdx" in reset
    assert "buildx prune" in reset


def test_dockerignore_excludes_download_and_keeps_generated_pki() -> None:
    dockerignore = REPO_ROOT / ".dockerignore"
    assert dockerignore.is_file()
    patterns = [
        line.strip()
        for line in dockerignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "download/" in patterns
    assert "lab/.gen/" not in patterns
    assert "lab/.gen" not in patterns


def test_docker_bake_file_lists_apk_lab_images() -> None:
    bake = REPO_ROOT / "docker-bake.hcl"
    assert bake.is_file()
    content = bake.read_text(encoding="utf-8")
    for name in ("builder", "runtime", "radius", "syslog", "kme", "test-runner"):
        assert f'target "{name}"' in content
    assert 'group "default"' in content
    assert "docker/base/Dockerfile.builder" in content
    assert "docker/base/Dockerfile.runtime" in content
    test_runner = content.split('target "test-runner"')[-1].split("group ")[0]
    assert "ALPINE_VERSION = ALPINE_VERSION" in test_runner
    makefile = MAKEFILE.read_text(encoding="utf-8")
    assert f"ALPINE_VERSION ?= {ALPINE_VERSION}" in makefile
    assert "HOST_ARCH" not in content
    assert "platforms" not in content
    assert "--set '*.platform=linux/$(HOST_ARCH)'" in makefile


def test_root_makefile_has_no_export_targets() -> None:
    """Export/publish targets must not be defined in the public Makefile."""
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "export-public:" not in content
    assert "publish-public:" not in content
    assert "docs-build:" not in content
    assert "include internal/export.mk" in content


def test_internal_export_mk_defines_export_targets() -> None:
    export_mk = REPO_ROOT / "internal" / "export.mk"
    assert export_mk.is_file()
    content = export_mk.read_text(encoding="utf-8")
    assert "export-public:" in content
    assert "publish-public:" in content
    assert "docs-build:" in content
    assert "check_public_export.py" in content
    assert "export_public.py" in content


def test_internal_export_mk_resolves_git_branch() -> None:
    export_mk = REPO_ROOT / "internal" / "export.mk"
    content = export_mk.read_text(encoding="utf-8")
    assert "GIT_BRANCH ?=" in content
    assert "$(shell git branch --show-current)" in content
    assert "--branch '$(GIT_BRANCH)'" in content
    assert "'$$(git branch --show-current)'" not in content
    result = _run_make("-n", "export-public")
    assert "--branch '$(git branch --show-current)'" not in result.stdout
    assert "--branch '" in result.stdout


def test_make_help_lists_export_targets_from_internal_include() -> None:
    export_mk = REPO_ROOT / "internal" / "export.mk"
    if not export_mk.is_file():
        pytest.skip("internal/export.mk not present")
    result = _run_make("help")
    for target in ("export-public", "publish-public", "docs-build"):
        assert target in result.stdout
