"""A release tag must select exactly the version built and published."""

import runpy
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
