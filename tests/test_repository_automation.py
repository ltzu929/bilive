from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_matches_supported_runtime_and_deploy_checks() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(
        encoding="utf-8"
    )

    assert "windows-latest" in workflow
    assert "python-version: '3.13'" in workflow
    assert "requirements/dev.txt" in workflow
    assert "python -m pytest" in workflow
    assert "python -m compileall" in workflow
    assert "ubuntu-latest" in workflow
    assert "bash -n" in workflow
    assert "systemd-analyze verify" in workflow


def test_stale_repository_templates_are_removed() -> None:
    assert not (ROOT / ".github" / "workflows" / "deploy.yml").exists()
    assert not (ROOT / ".github" / "dependbot.yml").exists()
    assert not (ROOT / ".devcontainer" / "devcontainer.json").exists()

    dependabot = ROOT / ".github" / "dependabot.yml"
    assert dependabot.exists()
    text = dependabot.read_text(encoding="utf-8")
    assert 'package-ecosystem: "pip"' in text
    assert 'directory: "/requirements"' in text
    assert 'package-ecosystem: "github-actions"' in text


def test_runtime_paths_only_expose_project_root() -> None:
    shell_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in ROOT.glob("*.sh")
    )
    assert "PYTHONPATH=.:./src" not in shell_text

    for package in ("autoslice", "burn", "log", "upload"):
        init_text = (ROOT / "src" / package / "__init__.py").read_text(
            encoding="utf-8"
        )
        assert "sys.path" not in init_text
