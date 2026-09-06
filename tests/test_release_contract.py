"""A release tag must select exactly the version built and published."""

import runpy
import sys
import tomllib
from pathlib import Path

import pytest


@pytest.mark.parametrize("tag", ["v0.5.0", "0.5.0rc1", "v0.4.2", "v0.5.0rc1-extra"])
def test_release_rejects_mismatched_tag(tag):
    validate = runpy.run_path(str(Path(__file__).parent.parent / "scripts/check_version.py"))[
        "validate"
    ]
    with pytest.raises(ValueError):
        validate(tag, "0.5.0rc1")


def test_release_accepts_exact_candidate_tag():
    validate = runpy.run_path(str(Path(__file__).parent.parent / "scripts/check_version.py"))[
        "validate"
    ]
    validate("v0.5.0rc1", "0.5.0rc1")


def test_published_check_rejects_unknown_repository(monkeypatch):
    main = runpy.run_path(str(Path(__file__).parent.parent / "scripts/check_published.py"))["main"]
    monkeypatch.setattr(sys, "argv", ["check_published.py", "dist", "unknown"])
    with pytest.raises(ValueError, match="testpypi or pypi"):
        main()


def test_provider_sdk_ranges_exclude_untested_majors():
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert set(project["optional-dependencies"]["providers"]) == {
        "anthropic>=0.40,<2",
        "openai>=1.50,<4",
    }
    assert "httpx2>=2.12,<3" in project["optional-dependencies"]["dev"]


def test_published_check_selects_only_wheel_and_sdist(tmp_path):
    expected_artifacts = runpy.run_path(
        str(Path(__file__).parent.parent / "scripts/check_published.py")
    )["expected_artifacts"]
    (tmp_path / "package-0.5.0-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "package-0.5.0.tar.gz").write_bytes(b"sdist")
    (tmp_path / ".gitignore").write_text("*\n")

    assert set(expected_artifacts(tmp_path)) == {
        "package-0.5.0-py3-none-any.whl",
        "package-0.5.0.tar.gz",
    }


@pytest.mark.parametrize("suffix", [".whl", ".tar.gz"])
def test_published_check_rejects_duplicate_distribution_type(tmp_path, suffix):
    expected_artifacts = runpy.run_path(
        str(Path(__file__).parent.parent / "scripts/check_published.py")
    )["expected_artifacts"]
    (tmp_path / f"package-a{suffix}").write_bytes(b"a")
    (tmp_path / f"package-b{suffix}").write_bytes(b"b")
    other_suffix = ".tar.gz" if suffix == ".whl" else ".whl"
    (tmp_path / f"package{other_suffix}").write_bytes(b"other")

    with pytest.raises(ValueError, match="one wheel and one sdist"):
        expected_artifacts(tmp_path)


def test_workflows_pin_uv_and_release_requires_deepseek_live():
    root = Path(__file__).parent.parent
    workflows = [root / ".github/workflows/ci.yml", root / ".github/workflows/release.yml"]
    combined = "\n".join(path.read_text() for path in workflows)
    assert combined.count('version: "0.12.10"') == 3
    checksum = "173d95a0c32d18c896c46ba6fafbf3cf9c14ab74b033f81b76c883ef492a976b"
    assert combined.count(f'checksum: "{checksum}"') == 3
    release = workflows[1].read_text()
    assert "live_providers: deepseek" in release
    assert "DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}" in release
    assert "secrets: inherit" not in release
