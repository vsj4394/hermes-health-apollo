from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    shutil.copytree(ROOT / ".githooks", repo / ".githooks")
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    install_script = repo / "scripts" / "install_git_hooks.sh"
    install_script.write_text(
        (ROOT / "scripts" / "install_git_hooks.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return repo


def test_install_git_hooks_installs_pre_commit_and_pre_push(tmp_path: Path):
    repo = _init_repo(tmp_path)

    subprocess.run(
        ["sh", "scripts/install_git_hooks.sh"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    hooks_dir = repo / ".git" / "hooks"
    pre_commit = hooks_dir / "pre-commit"
    pre_push = hooks_dir / "pre-push"

    assert pre_commit.exists()
    assert pre_push.exists()
    assert "scripts/secret_scan.py" in pre_commit.read_text(encoding="utf-8")
    assert "scripts/secret_scan.py" in pre_push.read_text(encoding="utf-8")
    assert "refs/heads/*|refs/tags/*" in pre_push.read_text(encoding="utf-8")


def test_pre_commit_blocks_staged_secret_like_file(tmp_path: Path):
    repo = _init_repo(tmp_path)
    subprocess.run(
        ["sh", "scripts/install_git_hooks.sh"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    fixture = repo / "google_token.json"
    fixture.write_text('{"access_token":"ya29.realSecretValueThatShouldBlock"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "google_token.json"], cwd=repo, check=True, capture_output=True, text=True)

    result = subprocess.run(
        ["git", "commit", "-m", "should be blocked"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Secret scan failed." in result.stderr


def test_install_git_hooks_overwrites_existing_managed_hooks(tmp_path: Path):
    repo = _init_repo(tmp_path)
    subprocess.run(
        ["sh", "scripts/install_git_hooks.sh"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    managed_pre_push = repo / ".git" / "hooks" / "pre-push"
    managed_pre_push.write_text(
        "#!/bin/sh\n# Managed by Hermes Health Apollo git hook installer.\nexit 99\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["sh", "scripts/install_git_hooks.sh"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "scripts/secret_scan.py" in managed_pre_push.read_text(encoding="utf-8")
