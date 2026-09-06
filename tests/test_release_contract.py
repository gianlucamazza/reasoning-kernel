"""A release tag must select exactly the version built and published."""

import runpy
import sys
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
