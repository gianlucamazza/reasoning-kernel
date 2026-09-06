"""Require the release tag to match package metadata exactly."""

import os
import tomllib
from pathlib import Path


def validate(tag: str, version: str) -> None:
    if tag != f"v{version}":
        raise ValueError("release tag does not match project.version")


if __name__ == "__main__":
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    validate(os.environ["GITHUB_REF_NAME"], project["version"])
