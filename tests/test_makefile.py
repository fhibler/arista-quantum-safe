"""Tests for Makefile topology generation and lifecycle targets."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
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


def _run_make(
    *targets: str,
    env: dict[str, str] | None = None,
    check: bool = True,
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    cmd = ["make", "-C", str(cwd), *targets]
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


EXPECTED_TARGETS = {
    "help", "containerlab-check", "containerlab-gentopo", "containerlab-validate",
    "containerlab-deploy", "containerlab-destroy", "containerlab-redeploy", "containerlab-inspect",
    "deploy", "redeploy", "destroy", "inspect",
    "ceos-image-check", "ceos-image-import", "ceos-image-download", "ceos-image-help", "ceos-quadra-install",
    "images-build", "images-check", "images-kme-deploy", "images-kme-pool-wait",
    "ceos-cli", "test-runner-shell", "test-offline", "test-lab", "test-lab-runner",
    "test-ssh", "test-eapi", "test-radsec", "test-syslog", "test-openconfig", "test-kme",
    "test-macsec-dot1x", "test-macsec-dot1x-reauth", "test-macsec-qkd", "test-hosts",
    "docs-config-sync", "docs-build", "docs-export", "docs-publish", "clean", "reset",
}


def test_make_help_lists_only_supported_targets(tmp_path: Path) -> None:
    sections = [
        "General", "Containerlab", "cEOS image management", "Lab images",
        "Node access", "Tests", "Documentation", "Workspace",
    ]
    result = _run_make("--no-print-directory", "help")
    lines = result.stdout.splitlines()
    assert [line for line in lines if line and not line.startswith(" ")] == sections
    targets = [line.split()[0] for line in lines if line.startswith("  ")]
    assert set(targets) == EXPECTED_TARGETS
    assert len(targets) == len(EXPECTED_TARGETS)
    workspace_targets = re.findall(r"^  (\S+)", result.stdout.split("\nWorkspace\n", 1)[1], re.M)
    assert workspace_targets == ["deploy", "redeploy", "destroy", "inspect", "clean", "reset"]
    assert result.stdout.index("docs-config-sync") < result.stdout.index("docs-build") < result.stdout.index("Workspace")
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    public_help = _run_make("--no-print-directory", cwd=tmp_path)
    headings = [line for line in public_help.stdout.splitlines() if line and not line.startswith(" ")]
    assert headings == sections
    targets = {line.split()[0] for line in public_help.stdout.splitlines() if line.startswith("  ")}
    assert targets == EXPECTED_TARGETS - {"docs-build", "docs-export", "docs-publish"}


def test_documented_make_commands_use_supported_targets() -> None:
    paths = [
        REPO_ROOT / "README.md",
        *(REPO_ROOT / "docs").rglob("*.md"),
        *(REPO_ROOT / "internal" / "docs").rglob("*.md"),
    ]
    command = re.compile(
        r"(?:^\s*(?:VERBOSE=1\s+)?make[ \t]+|`(?:VERBOSE=1\s+)?make[ \t]+)"
        r"([A-Za-z][A-Za-z0-9_-]*)(?![\w=-])",
        re.M,
    )
    unknown = []
    for path in paths:
        for match in command.finditer(path.read_text(encoding="utf-8")):
            target = match[1]
            if target not in EXPECTED_TARGETS and target != "test-":
                unknown.append(f"{path.relative_to(REPO_ROOT)}: {match[0]}")
    assert not unknown, "Unsupported documented Make commands:\n" + "\n".join(unknown)


@pytest.fixture
def image_operations(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Run real Make recipes with external operations recorded instead of executed."""
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    log = tmp_path / "operations.jsonl"
    stub = tmp_path / "operation"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "kind = Path(sys.argv[0]).name\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['OPERATION_LOG'], 'a') as log:\n"
        "    log.write(json.dumps([kind, args, os.environ.get('SELECTED_IMAGE')]) + '\\n')\n"
        "if kind == 'phase-make':\n"
        "    sys.exit(1 if os.environ.get('FAIL_PHASE') in args else 0)\n"
        "image = next((arg for arg in args if arg.startswith('quantum-safe-')), '')\n"
        "if image and image == os.environ.get('FAIL_IMAGE'):\n"
        "    sys.exit(1)\n"
        "if '-tls-groups' in args:\n"
        "    print('X25519MLKEM768 MLKEM768 SecP256r1MLKEM768')\n"
        "elif args[:1] == ['inspect']:\n"
        "    print('healthy')\n"
        "elif '-d' in args:\n"
        "    print('test-syslog-container')\n"
        "else:\n"
        "    print('stub version output')\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    for command in ("docker", "phase-make"):
        (tmp_path / command).symlink_to(stub)
    return tmp_path, {"PATH": f"{tmp_path}:{os.environ['PATH']}", "OPERATION_LOG": str(log)}


def _image_operations(directory: Path) -> list[list]:
    log = directory / "operations.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


@pytest.mark.parametrize("image", ["", "radius", "syslog", "kme", "test-runner"])
def test_image_build_selects_bake_target_and_runs_verification(
    image_operations: tuple[Path, dict[str, str]], image: str
) -> None:
    directory, env = image_operations
    _run_make(
        "-j8", "images-build", f"IMAGE={image}", f"MAKE={directory / 'phase-make'}", "VERBOSE=1",
        cwd=directory, env=env,
    )
    operations = _image_operations(directory)
    if image != "test-runner":
        assert operations.pop(0) == ["phase-make", ["--no-print-directory", "containerlab-gentopo", "VERBOSE=1"], image]
    build, verify = operations
    assert build[0] == "docker"
    assert build[1][:4] == ["buildx", "bake", "-f", "docker-bake.hcl"]
    assert "--progress=plain" in build[1]
    assert build[1][-1] == (image or f"*.platform=linux/{os.uname().machine.replace('aarch64', 'arm64').replace('x86_64', 'amd64')}")
    assert verify == ["phase-make", ["--no-print-directory", "images-check", "VERBOSE=1"], image]


@pytest.mark.parametrize("image", ["", "radius", "syslog", "kme", "test-runner"])
def test_image_check_runs_only_selected_images(
    image_operations: tuple[Path, dict[str, str]], image: str
) -> None:
    directory, env = image_operations
    _run_make("images-check", f"IMAGE={image}", "PYTHON=true", cwd=directory, env=env)
    operations = _image_operations(directory)
    observed = {
        arg for kind, args, _ in operations if kind == "docker"
        for arg in args if arg.startswith("quantum-safe-") and arg.endswith(":latest")
    }
    expected = {image} if image else {"radius", "syslog", "kme", "test-runner"}
    assert observed == {f"quantum-safe-{selected}:latest" for selected in expected}
    assert all(args[:2] != ["buildx", "bake"] for _, args, _ in operations)


@pytest.mark.parametrize("target", ["images-build", "images-check"])
@pytest.mark.parametrize("image", ["unknown", "radius syslog", "radius; touch unexpected"])
def test_invalid_image_selector_fails_before_any_operation(
    image_operations: tuple[Path, dict[str, str]], target: str, image: str
) -> None:
    directory, env = image_operations
    result = _run_make(target, f"IMAGE={image}", cwd=directory, env=env, check=False)
    assert result.returncode != 0
    assert "Invalid IMAGE" in result.stderr
    assert _image_operations(directory) == []
    assert not (directory / "unexpected").exists()


def test_failed_config_generation_prevents_build(image_operations: tuple[Path, dict[str, str]]) -> None:
    directory, env = image_operations
    result = _run_make(
        "images-build", f"MAKE={directory / 'phase-make'}", cwd=directory,
        env={**env, "FAIL_PHASE": "containerlab-gentopo"}, check=False,
    )
    assert result.returncode != 0
    assert [kind for kind, _, _ in _image_operations(directory)] == ["phase-make"]


def test_failed_image_check_stops_before_later_images(image_operations: tuple[Path, dict[str, str]]) -> None:
    directory, env = image_operations
    result = _run_make(
        "images-check", "PYTHON=true", cwd=directory,
        env={**env, "FAIL_IMAGE": "quantum-safe-syslog:latest"}, check=False,
    )
    assert result.returncode != 0
    observed = {arg for _, args, _ in _image_operations(directory) for arg in args}
    assert "quantum-safe-radius:latest" in observed
    assert "quantum-safe-syslog:latest" in observed
    assert "quantum-safe-kme:latest" not in observed
    assert "quantum-safe-test-runner:latest" not in observed


@pytest.mark.parametrize("node", ["ceos1-both", "ceos2-pqc", "ceos3-qkd", "", "other", "ceos1-both; touch unexpected"])
def test_ceos_cli_requires_a_known_node(image_operations: tuple[Path, dict[str, str]], node: str) -> None:
    directory, env = image_operations
    result = _run_make("ceos-cli", f"NODE={node}", cwd=directory, env=env, check=False)
    if node in {"ceos1-both", "ceos2-pqc", "ceos3-qkd"}:
        assert result.returncode == 0
        assert _image_operations(directory) == [["docker", ["exec", "-it", f"arista-quantum-safe-{node}", "Cli"], None]]
    else:
        assert result.returncode != 0
        assert "Set NODE=" in result.stderr
        assert _image_operations(directory) == []
        assert not (directory / "unexpected").exists()


@pytest.mark.parametrize("target", ["containerlab-deploy", "deploy", "containerlab-redeploy", "redeploy"])
@pytest.mark.parametrize("fail_phase", ["", "containerlab-check", "containerlab-destroy", "images-kme-pool-wait"])
def test_lifecycle_phases_are_sequential_and_stop_on_failure(
    tmp_path: Path, target: str, fail_phase: str
) -> None:
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    log = tmp_path / "phases.log"
    fake_make = tmp_path / "phase-make"
    fake_make.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, time\n"
        "phase = sys.argv[2]\n"
        "with open(os.environ['PHASE_LOG'], 'a') as log:\n"
        "    log.write(f'start {phase} {sys.argv[3:]}\\n')\n"
        "time.sleep(0.02)\n"
        "if phase == os.environ.get('FAIL_PHASE'):\n"
        "    sys.exit(1)\n"
        "with open(os.environ['PHASE_LOG'], 'a') as log:\n"
        "    log.write(f'end {phase}\\n')\n",
        encoding="utf-8",
    )
    fake_make.chmod(0o755)
    fake_clab = tmp_path / "containerlab"
    fake_clab.write_text(
        '#!/bin/sh\nprintf "containerlab %s\\n" "$*" >> "$PHASE_LOG"\n', encoding="utf-8"
    )
    fake_clab.chmod(0o755)
    phases = (
        ["containerlab-gentopo", "containerlab-destroy", "containerlab-deploy"]
        if target.endswith("redeploy")
        else [
            "containerlab-gentopo",
            "containerlab-check",
            "images-build",
            "ceos-image-check",
            "images-kme-deploy",
            "images-kme-pool-wait",
        ]
    )
    failed = fail_phase in phases
    result = _run_make(
        "-j8", target, f"MAKE={fake_make}", "VERBOSE=1",
        cwd=tmp_path,
        env={
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "PHASE_LOG": str(log),
            "FAIL_PHASE": fail_phase,
        },
        check=False,
    )
    assert (result.returncode != 0) == failed, result.stdout + result.stderr
    expected = []
    for phase in phases:
        args = ["IMAGE=", "VERBOSE=1"] if phase == "images-build" else ["VERBOSE=1"]
        expected.append(f"start {phase} {args}")
        if phase == fail_phase:
            break
        expected.append(f"end {phase}")
    if not failed and not target.endswith("redeploy"):
        expected.append("containerlab deploy -t lab/.gen.quantum-safe.clab.yml -d")
    assert log.read_text(encoding="utf-8").splitlines() == expected


def test_gen_topo_default_image() -> None:
    _run_make("containerlab-gentopo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
    assert GEN_TOPOLOGY_PATH.is_file()
    data = load_topology(GEN_TOPOLOGY_PATH)
    image = data["topology"]["kinds"]["arista_ceos"]["image"]
    assert image == DEFAULT_CEOS_IMAGE
    assert data["mgmt"]["ipv4-subnet"] == DEFAULT_MGMT_SUBNET
    assert data["mgmt"]["ipv6-subnet"] == DEFAULT_MGMT_IPV6_SUBNET


def test_gen_topo_custom_ceos_image() -> None:
    custom = "ceos:5.0.0F"
    _run_make("containerlab-gentopo", f"CEOS_IMAGE={custom}")
    data = load_topology(GEN_TOPOLOGY_PATH)
    assert data["topology"]["kinds"]["arista_ceos"]["image"] == custom
    errors = validate_topology(data, ceos_image=custom)
    assert errors == []


def test_gen_topo_custom_mgmt_subnet() -> None:
    custom = "192.168.28.0/24"
    _run_make("containerlab-gentopo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={custom}")
    data = load_topology(GEN_TOPOLOGY_PATH)
    assert data["mgmt"]["ipv4-subnet"] == custom
    assert data["topology"]["nodes"]["radius"]["mgmt-ipv4"] == "192.168.28.50"
    errors = validate_topology(data, mgmt_subnet=custom)
    assert errors == []


def test_gen_topo_custom_mgmt_ipv6_subnet() -> None:
    custom = "2001:db8:99::/64"
    _run_make(
        "containerlab-gentopo",
        f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}",
        f"MGMT_IPV6_SUBNET={custom}",
    )
    data = load_topology(GEN_TOPOLOGY_PATH)
    assert data["mgmt"]["ipv6-subnet"] == custom
    assert data["topology"]["nodes"]["radius"]["mgmt-ipv6"] == "2001:db8:99::50"
    errors = validate_topology(data, mgmt_ipv6_subnet=custom)
    assert errors == []


def test_gen_topo_substitutes_placeholders() -> None:
    _run_make("containerlab-gentopo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
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
    _run_make("containerlab-gentopo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
    result = _run_make(
        "containerlab-validate",
        f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}",
        f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}",
        f"MGMT_IPV6_SUBNET={DEFAULT_MGMT_IPV6_SUBNET}",
    )
    assert result.returncode == 0
    assert GEN_TOPOLOGY_PATH.is_file()


def test_validate_topo_fails_on_contract_violation(tmp_path: Path) -> None:
    _run_make("containerlab-gentopo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
    broken = tmp_path / "broken.clab.yml"
    broken.write_text(GEN_TOPOLOGY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    data = yaml.safe_load(broken.read_text(encoding="utf-8"))
    data["topology"]["nodes"]["ceos1-both"]["mgmt-ipv4"] = "10.0.0.1"
    broken.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")

    errors = validate_topology(load_topology(broken))
    assert any("ceos1-both mgmt-ipv4" in err for err in errors)


def test_render_preserves_yaml_structure() -> None:
    _run_make("containerlab-gentopo", f"CEOS_IMAGE={DEFAULT_CEOS_IMAGE}", f"MGMT_SUBNET={DEFAULT_MGMT_SUBNET}")
    data = yaml.safe_load(GEN_TOPOLOGY_PATH.read_text(encoding="utf-8"))
    assert data["topology"]["nodes"]["radius"]["image"] == "quantum-safe-radius:latest"
    assert data["topology"]["kinds"]["arista_ceos"]["image"] == DEFAULT_CEOS_IMAGE


def test_ceos_image_help_covers_import_and_download() -> None:
    result = _run_make("ceos-image-help")
    assert "docker import download/cEOS64-lab-" in result.stdout
    assert "docker import download/cEOSarm-lab-" in result.stdout
    assert "make ceos-image-download" in result.stdout
    assert "make ceos-image-import" in result.stdout
    assert "ARISTA_TOKEN" in result.stdout
    assert "ardl get eos" in result.stdout
    assert ".env.example" in result.stdout


def test_download_ceos_fails_without_token(tmp_path: Path) -> None:
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    empty_download = tmp_path / "empty-download"
    empty_download.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "ARISTA_TOKEN"}
    env["CEOS_DOWNLOAD_DIR"] = str(empty_download)
    env["ARISTA_TOKEN"] = ""
    result = _run_make("ceos-image-download", cwd=tmp_path, env=env, check=False)
    assert result.returncode != 0
    assert "ARISTA_TOKEN not set" in result.stdout + result.stderr


def test_download_ceos_loads_dotenv(tmp_path: Path) -> None:
    """Token in .env satisfies check when shell env has no ARISTA_TOKEN."""
    shutil.copy(MAKEFILE, tmp_path / "Makefile")
    dotenv = tmp_path / ".env"
    dotenv.write_text("ARISTA_TOKEN=fake-token-from-dotenv\n", encoding="utf-8")
    empty_download = tmp_path / "empty-download"
    empty_download.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "ARISTA_TOKEN"}
    env["CEOS_DOWNLOAD_DIR"] = str(empty_download)
    # Stub the downloader interpreter so this check never installs or downloads anything.
    interpreter = tmp_path / ".venv" / "bin" / "python3"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$DOWNLOAD_LOG"\n', encoding="utf-8")
    interpreter.chmod(0o755)
    log = tmp_path / "download.log"
    result = _run_make("ceos-image-download", cwd=tmp_path, env={**env, "DOWNLOAD_LOG": str(log)})
    assert "ARISTA_TOKEN not set" not in result.stdout + result.stderr
    assert "--token fake-token-from-dotenv get eos" in log.read_text(encoding="utf-8")


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
    assert "make ceos-image-import" in content


def test_import_ceos_recipe_imports_local_tarball() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "ceos-image-import:" in content
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
    result = _run_make("ceos-image-check", f"CEOS_IMAGE={missing}", check=False)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "not found" in combined.lower()
    assert "docker import download/cEOS64-lab-" in combined
    assert "ceos-image-import" in _makefile_recipe("ceos-image-check")


def test_check_ceos_image_imports_when_missing() -> None:
    recipe = _makefile_recipe("ceos-image-check")
    assert "importing from" in recipe
    assert "SKIP_CEOS_IMPORT" in recipe
    assert "ceos-image-import" in recipe


@pytest.mark.parametrize("image", ["radius", "syslog", "kme", "test-runner"])
def test_image_checks_print_test_headers(image: str) -> None:
    result = _run_make("-n", "images-check", f"IMAGE={image}")
    assert "print_test_header" in result.stdout
    assert f"{image} image verification" in result.stdout
    for other in {"radius", "syslog", "kme", "test-runner"} - {image}:
        assert f"{other} image verification" not in result.stdout


def test_deploy_verbose_enables_plain_docker_build_and_debug_containerlab() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "BAKE_PROGRESS" in content
    assert "--progress=plain" in content
    assert "CLAB_DEPLOY_FLAGS" in content
    deploy = _makefile_recipe("containerlab-deploy")
    assert "CLAB_DEPLOY_FLAGS" in deploy
    assert "images-kme-deploy $(MAKE_VERBOSE)" in deploy
    assert "images-kme-pool-wait $(MAKE_VERBOSE)" in deploy
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
    result = _run_make("-n", "images-build")
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
    for image in ("radius", "syslog", "test-runner"):
        result = _run_make("-n", "images-check", f"IMAGE={image}")
        combined = result.stdout + result.stderr
        assert "openssl list -tls-groups" in combined
        for group in OPENSSL_PQC_TLS_GROUPS:
            assert group in combined


def test_makefile_defines_check_containerlab() -> None:
    content = MAKEFILE.read_text(encoding="utf-8")
    assert "CLAB_MIN_VERSION ?=" in content
    assert "CLAB_VERSION" not in content
    assert "containerlab-check:" in content
    assert "not installed" in content
    assert "images-kme-deploy: containerlab-check" in content
    assert "containerlab-destroy: containerlab-check" in content
    assert "containerlab-inspect: containerlab-check" in content


def test_check_containerlab_fails_when_not_installed(tmp_path: Path) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("make", "bash", "sed", "sort", "head"):
        src = shutil.which(name)
        if src:
            (bindir / name).symlink_to(src)
    env = {**os.environ, "PATH": str(bindir)}
    result = _run_make("containerlab-check", check=False, env=env)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "not installed" in combined.lower()


@pytest.mark.skipif(shutil.which("containerlab") is None, reason="containerlab not in PATH")
def test_check_containerlab_passes_when_version_ok() -> None:
    result = _run_make("containerlab-check", check=False)
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
    result = _run_make("containerlab-check", "CLAB_MIN_VERSION=99.99.0", check=False, env=env)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "too old" in combined.lower() or "need >=" in combined


def test_make_test_recipe_runs_pytest() -> None:
    result = _run_make("-n", "test-offline")
    assert "-m pytest" in result.stdout


def test_validate_topo_uses_cli_module() -> None:
    result = _run_make("-n", "containerlab-gentopo")
    assert "lab.render_topo" in result.stdout
    result = _run_make("-n", "containerlab-validate")
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
    assert "docs-export:" not in content
    assert "docs-publish:" not in content
    assert "docs-build:" not in content
    assert "include internal/export.mk" in content


def test_internal_export_mk_defines_export_targets() -> None:
    export_mk = REPO_ROOT / "internal" / "export.mk"
    assert export_mk.is_file()
    content = export_mk.read_text(encoding="utf-8")
    assert "docs-export:" in content
    assert "docs-publish:" in content
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
    result = _run_make("-n", "docs-export")
    assert "--branch '$(git branch --show-current)'" not in result.stdout
    assert "--branch '" in result.stdout


def test_make_help_lists_export_targets_from_internal_include() -> None:
    export_mk = REPO_ROOT / "internal" / "export.mk"
    if not export_mk.is_file():
        pytest.skip("internal/export.mk not present")
    result = _run_make("help")
    for target in ("docs-export", "docs-publish", "docs-build"):
        assert target in result.stdout
