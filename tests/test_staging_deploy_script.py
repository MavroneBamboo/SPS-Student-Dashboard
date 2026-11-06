import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy-staging.sh"


def _fake_commands(tmp_path: Path) -> tuple[Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FAKE_DOCKER_LOG"\nprintf "APP_BUILD_SHA=%s\\n" "${APP_BUILD_SHA:-}" >> "$FAKE_DOCKER_LOG"\ncase "$*" in\n  *"ps --all --quiet db"*) printf "fake-db-container\\n" ;;\n  *"inspect --format {{.State.Health.Status}} fake-db-container"*) printf "healthy\\n" ;;\n  *"SHOW pg_tde.wal_encrypt"*) printf "on\\n" ;;\nesac\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text('#!/bin/sh\nprintf \'{"revision":"%s"}\\n\' "${FAKE_HEALTH_REVISION:-}"\n', encoding="utf-8")
    curl.chmod(0o755)
    sleep = fake_bin / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    return fake_bin, docker_log


def _environment(tmp_path: Path, fake_bin: Path, docker_log: Path) -> dict[str, str]:
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    env_file = tmp_path / "staging.env"
    env_file.write_text("APP_ENV=staging\n", encoding="utf-8")
    env_file.chmod(0o600)
    return {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "GITHUB_WORKSPACE": str(ROOT),
        "GITHUB_SHA": revision,
        "GITHUB_RUN_ID": "staging-test",
        "FAKE_HEALTH_REVISION": revision,
        "SPS_STAGING_DIR": str(tmp_path / "staging-root"),
        "SPS_STAGING_ENV_FILE": str(env_file),
        "FAKE_DOCKER_LOG": str(docker_log),
    }


def test_deploy_script_stages_exact_revision_and_runs_health_check(tmp_path: Path):
    fake_bin, docker_log = _fake_commands(tmp_path)
    env = _environment(tmp_path, fake_bin, docker_log)

    result = subprocess.run(["bash", str(DEPLOY_SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    release = Path(env["SPS_STAGING_DIR"]) / "releases" / env["GITHUB_SHA"]
    assert (release / "docker-compose.yml").is_file()
    assert (release / "deploy" / "nginx.conf").is_file()
    assert (release / "deploy" / "nginx.Dockerfile").is_file()
    assert (release / "deploy" / "nginx.Dockerfile.dockerignore").is_file()
    assert (release / "prototype" / "index.html").is_file()
    assert (release / "prototype" / "reports" / "active-breakdown-by-category.csv").is_file()
    assert not (release / ".git").exists()
    assert not (release / ".env").exists()
    calls = docker_log.read_text(encoding="utf-8")
    assert f"APP_BUILD_SHA={env['GITHUB_SHA']}" in calls
    assert "config --quiet" in calls
    assert "up --detach --build --remove-orphans" in calls
    assert "Staging revision" in result.stdout


def test_deploy_script_rejects_environment_file_readable_by_others(tmp_path: Path):
    fake_bin, docker_log = _fake_commands(tmp_path)
    env = _environment(tmp_path, fake_bin, docker_log)
    Path(env["SPS_STAGING_ENV_FILE"]).chmod(0o644)

    result = subprocess.run(["bash", str(DEPLOY_SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)

    assert result.returncode == 2
    assert "chmod 600" in result.stderr
    assert not docker_log.exists()


def test_deploy_script_rejects_a_healthy_but_wrong_revision(tmp_path: Path):
    fake_bin, docker_log = _fake_commands(tmp_path)
    env = _environment(tmp_path, fake_bin, docker_log)
    env["FAKE_HEALTH_REVISION"] = "old-revision"

    result = subprocess.run(["bash", str(DEPLOY_SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)

    assert result.returncode == 1
    assert "did not report the expected revision" in result.stderr


def test_deploy_script_rejects_release_path_inside_checkout(tmp_path: Path):
    fake_bin, docker_log = _fake_commands(tmp_path)
    env = _environment(tmp_path, fake_bin, docker_log)
    unsafe_root = ROOT / ".staging-deploy-test"
    env["SPS_STAGING_DIR"] = str(unsafe_root)

    result = subprocess.run(["bash", str(DEPLOY_SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)

    assert result.returncode == 2
    assert "outside the checked-out repository" in result.stderr
    assert not unsafe_root.exists()
    assert not docker_log.exists()
