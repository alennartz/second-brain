from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SOURCE = REPOSITORY_ROOT / "deploy"


@dataclass(frozen=True)
class DeploymentWorkspace:
    root: Path
    deploy: Path
    data: Path
    backup: Path
    app_env: Path
    fake_bin: Path
    logs: Path
    env: dict[str, str]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(f"#!/usr/bin/env bash\nset -u\n{content}")
    path.chmod(0o755)


def _make_fake_commands(fake_bin: Path) -> None:
    _write_executable(
        fake_bin / "systemctl",
        """
mkdir -p "$FAKE_LOG_DIR"
printf '%s\\n' "$*" >> "$FAKE_LOG_DIR/systemctl.log"
if [[ "${SYSTEMCTL_FAIL:-0}" == "1" ]]; then
  exit 1
fi
if [[ "$*" == *" is-active "* ]]; then
  [[ "${SERVICE_ACTIVE:-active}" == "active" ]]
  exit $?
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "docker",
        """
mkdir -p "$FAKE_LOG_DIR"
printf '%s\\n' "$*" >> "$FAKE_LOG_DIR/docker.log"
for argument in "$@"; do
  if [[ "$argument" == "build" && "${DOCKER_BUILD_FAIL:-0}" == "1" ]]; then
    exit 1
  fi
  if [[ "$argument" == "inspect" && "${DOCKER_IMAGE_MISSING:-0}" == "1" ]]; then
    exit 1
  fi
done
exit 0
""",
    )
    _write_executable(
        fake_bin / "curl",
        """
if [[ "${CURL_FAIL:-0}" == "1" ]]; then
  exit 1
fi
printf '%s\\n' "${CURL_RESPONSE:-{\"ready\":0,\"leased\":0,\"retry_wait\":0,\"paused\":0}}"
""",
    )
    _write_executable(
        fake_bin / "jq",
        """
cat
if [[ "${JQ_FAIL:-0}" == "1" ]]; then
  exit 1
fi
""",
    )
    _write_executable(
        fake_bin / "tar",
        """
mkdir -p "$FAKE_LOG_DIR"
printf '%s\\n' "$*" >> "$FAKE_LOG_DIR/tar.log"
for argument in "$@"; do
  if [[ "$argument" == *c* && "${TAR_CREATE_FAIL:-0}" == "1" ]]; then
    exit 1
  fi
  if [[ "$argument" == *x* && "${TAR_EXTRACT_FAIL:-0}" == "1" ]]; then
    exit 1
  fi
done
exec /usr/bin/tar "$@"
""",
    )
    _write_executable(
        fake_bin / "gzip",
        """
mkdir -p "$FAKE_LOG_DIR"
printf '%s\\n' "$*" >> "$FAKE_LOG_DIR/gzip.log"
exec /usr/bin/gzip "$@"
""",
    )


@pytest.fixture
def deployment_workspace(tmp_path: Path) -> DeploymentWorkspace:
    root = tmp_path / "workspace"
    deploy = root / "deploy"
    shutil.copytree(DEPLOY_SOURCE, deploy)

    data = root / "data"
    active_db = data / "brain.db"
    (active_db / "state").mkdir(parents=True)
    (active_db / "state" / "records.json").write_text("active database")
    experiment_db = data / "experiments" / "trial.db"
    experiment_db.parent.mkdir(parents=True)
    experiment_db.write_text("experiment database")

    backup = root / "backups"
    backup.mkdir(parents=True)
    app_env = root / "app.env"
    app_env.write_text("BRAIN_TEST_MODE=true\n")
    app_env.chmod(0o600)

    (deploy / "deploy.env").write_text(
        "\n".join(
            [
                "BRAIN_IMAGE=second-brain:local",
                "BRAIN_DEPLOY_NAME=second-brain",
                "BRAIN_DEPLOY_PORT=8100",
                f"BRAIN_DEPLOY_ENV_FILE={app_env}",
                f"BRAIN_DEPLOY_DATA_DIR={data}",
                f"BRAIN_DEPLOY_BACKUP_DIR={backup}",
                "BRAIN_DEPLOY_DB_NAME=brain.db",
                "",
            ]
        )
    )

    fake_bin = root / "fake-bin"
    fake_bin.mkdir(parents=True)
    logs = root / "logs"
    logs.mkdir()
    _make_fake_commands(fake_bin)

    config_home = root / "config"
    env = os.environ.copy()
    env.update(
        {
            "FAKE_LOG_DIR": str(logs),
            "HOME": str(root / "home"),
            "XDG_CONFIG_HOME": str(config_home),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "CURL_RESPONSE": '{"ready":0,"leased":0,"retry_wait":0,"paused":0}',
        }
    )
    return DeploymentWorkspace(root, deploy, data, backup, app_env, fake_bin, logs, env)


def _run(
    workspace: DeploymentWorkspace,
    script: str,
    *arguments: str,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = workspace.env.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(workspace.deploy / script), *arguments],
        cwd=workspace.root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _log_lines(workspace: DeploymentWorkspace, name: str) -> list[str]:
    path = workspace.logs / name
    return path.read_text().splitlines() if path.exists() else []


def _archives(workspace: DeploymentWorkspace, prefix: str) -> list[Path]:
    return sorted(workspace.backup.glob(f"{prefix}-*.tar.gz"))


def _assert_archive_contains_active_database(archive: Path) -> None:
    with tarfile.open(archive, mode="r:gz") as stream:
        names = stream.getnames()
    assert names
    assert all(name == "brain.db" or name.startswith("brain.db/") for name in names)
    assert not any("experiment" in name for name in names)


def test_daily_backup_defers_when_intake_work_is_pending(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    result = _run(
        deployment_workspace,
        "backup.sh",
        "daily",
        env_overrides={
            "CURL_RESPONSE": '{"ready":1,"leased":0,"retry_wait":0,"paused":0}'
        },
    )

    assert result.returncode == 0, result.stderr
    assert "deferred" in result.stdout.lower()
    assert not any(
        " stop " in line for line in _log_lines(deployment_workspace, "systemctl.log")
    )
    assert _archives(deployment_workspace, "daily") == []


def test_daily_backup_archives_only_the_active_database_and_restarts_service(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    result = _run(deployment_workspace, "backup.sh", "daily")

    assert result.returncode == 0, result.stderr
    archives = _archives(deployment_workspace, "daily")
    assert len(archives) == 1
    assert stat.S_IMODE(archives[0].stat().st_mode) == 0o600
    _assert_archive_contains_active_database(archives[0])

    service_log = _log_lines(deployment_workspace, "systemctl.log")
    stop_index = next(
        i for i, line in enumerate(service_log) if "stop second-brain.service" in line
    )
    start_index = next(
        i for i, line in enumerate(service_log) if "start second-brain.service" in line
    )
    assert stop_index < start_index


def test_daily_backup_recovers_the_service_when_archive_creation_fails(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    result = _run(
        deployment_workspace,
        "backup.sh",
        "daily",
        env_overrides={"TAR_CREATE_FAIL": "1"},
    )

    assert result.returncode != 0
    assert "archive" in result.stderr.lower()
    service_log = _log_lines(deployment_workspace, "systemctl.log")
    assert any("stop second-brain.service" in line for line in service_log)
    assert any("start second-brain.service" in line for line in service_log)


def test_pre_update_backup_refuses_non_idle_intake_without_stopping_service(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    result = _run(
        deployment_workspace,
        "backup.sh",
        "pre-update",
        env_overrides={
            "CURL_RESPONSE": '{"ready":0,"leased":1,"retry_wait":0,"paused":0}'
        },
    )

    assert result.returncode != 0
    assert "intake" in result.stderr.lower()
    assert not any(
        " stop " in line for line in _log_lines(deployment_workspace, "systemctl.log")
    )
    assert _archives(deployment_workspace, "pre-update") == []


def test_pre_update_backup_archives_after_intake_becomes_idle(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    result = _run(deployment_workspace, "backup.sh", "pre-update")

    assert result.returncode == 0, result.stderr
    archives = _archives(deployment_workspace, "pre-update")
    assert len(archives) == 1
    _assert_archive_contains_active_database(archives[0])


def test_restore_rejects_an_archive_outside_the_configured_backup_directory(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    outside_archive = deployment_workspace.root / "outside.tar.gz"
    outside_archive.write_bytes(b"not a configured backup")

    result = _run(deployment_workspace, "backup.sh", "restore", str(outside_archive))

    assert result.returncode != 0
    assert "backup directory" in result.stderr.lower()
    assert (deployment_workspace.data / "brain.db").exists()


def test_restore_moves_active_database_to_safety_and_restores_selected_archive(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    archive = deployment_workspace.backup / "daily-2026-01-01T030000Z.tar.gz"
    source = deployment_workspace.root / "restore-source"
    (source / "brain.db" / "state").mkdir(parents=True)
    (source / "brain.db" / "state" / "records.json").write_text("restored database")
    with tarfile.open(archive, mode="w:gz") as stream:
        stream.add(source / "brain.db", arcname="brain.db")

    result = _run(deployment_workspace, "backup.sh", "restore", str(archive))

    assert result.returncode == 0, result.stderr
    restored = deployment_workspace.data / "brain.db" / "state" / "records.json"
    assert restored.read_text() == "restored database"
    safety_copies = sorted(deployment_workspace.data.glob("brain.db.safety-*"))
    assert len(safety_copies) == 1
    assert (
        safety_copies[0] / "state" / "records.json"
    ).read_text() == "active database"
    assert (
        deployment_workspace.data / "experiments" / "trial.db"
    ).read_text() == "experiment database"

    service_log = _log_lines(deployment_workspace, "systemctl.log")
    assert any("stop second-brain.service" in line for line in service_log)
    assert any("start second-brain.service" in line for line in service_log)


def test_restore_keeps_safety_copy_when_extraction_fails(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    archive = deployment_workspace.backup / "daily-2026-01-01T030000Z.tar.gz"
    with tarfile.open(archive, mode="w:gz") as stream:
        stream.add(deployment_workspace.data / "brain.db", arcname="brain.db")

    result = _run(
        deployment_workspace,
        "backup.sh",
        "restore",
        str(archive),
        env_overrides={"TAR_EXTRACT_FAIL": "1"},
    )

    assert result.returncode != 0
    assert "restore" in result.stderr.lower()
    safety_copies = sorted(deployment_workspace.data.glob("brain.db.safety-*"))
    assert len(safety_copies) == 1
    assert (
        safety_copies[0] / "state" / "records.json"
    ).read_text() == "active database"


def test_update_builds_local_image_and_archives_before_restarting(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    result = _run(deployment_workspace, "update.sh")

    assert result.returncode == 0, result.stderr
    docker_log = _log_lines(deployment_workspace, "docker.log")
    assert any("build" in line and "second-brain:local" in line for line in docker_log)
    assert not any(" pull " in f" {line} " for line in docker_log)
    assert _archives(deployment_workspace, "pre-update")
    service_log = _log_lines(deployment_workspace, "systemctl.log")
    assert any("restart second-brain.service" in line for line in service_log)


def test_update_leaves_running_service_untouched_when_image_build_fails(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    result = _run(
        deployment_workspace,
        "update.sh",
        env_overrides={"DOCKER_BUILD_FAIL": "1"},
    )

    assert result.returncode != 0
    assert "build" in result.stderr.lower()
    assert _archives(deployment_workspace, "pre-update") == []
    assert not any(
        " stop " in line for line in _log_lines(deployment_workspace, "systemctl.log")
    )


def test_install_renders_loopback_service_and_daily_backup_timer(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    result = _run(deployment_workspace, "install.sh")

    assert result.returncode == 0, result.stderr
    unit_dir = deployment_workspace.env["XDG_CONFIG_HOME"]
    unit_path = Path(unit_dir) / "systemd" / "user" / "second-brain.service"
    backup_service = Path(unit_dir) / "systemd" / "user" / "second-brain-backup.service"
    backup_timer = Path(unit_dir) / "systemd" / "user" / "second-brain-backup.timer"
    unit_text = unit_path.read_text()
    timer_text = backup_timer.read_text()
    assert "127.0.0.1:8100:8000" in unit_text
    assert "--pull never" in unit_text
    assert "TimeoutStopSec=" in unit_text
    assert backup_service.exists()
    assert "OnCalendar=*-*-* 03:00:00" in timer_text
    assert "Persistent=true" in timer_text
    assert any(
        "enable --now second-brain-backup.timer" in line
        for line in _log_lines(deployment_workspace, "systemctl.log")
    )


def test_install_sets_application_environment_permissions_to_owner_only(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    deployment_workspace.app_env.chmod(0o644)

    result = _run(deployment_workspace, "install.sh")

    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(deployment_workspace.app_env.stat().st_mode) == 0o600


def test_install_rejects_a_missing_local_image(
    deployment_workspace: DeploymentWorkspace,
) -> None:
    result = _run(
        deployment_workspace,
        "install.sh",
        env_overrides={"DOCKER_IMAGE_MISSING": "1"},
    )

    assert result.returncode != 0
    assert "image" in result.stderr.lower()
    assert not any(
        "enable --now" in line
        for line in _log_lines(deployment_workspace, "systemctl.log")
    )


def test_make_exposes_backup_and_restore_command_boundaries() -> None:
    backup = subprocess.run(
        ["make", "-n", "deploy-backup", "MODE=daily"],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert backup.returncode == 0, backup.stderr
    assert "backup.sh daily" in backup.stdout

    restore = subprocess.run(
        ["make", "-n", "deploy-restore", "ARCHIVE=/tmp/archive.tar.gz"],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert restore.returncode == 0, restore.stderr
    assert "backup.sh restore /tmp/archive.tar.gz" in restore.stdout
