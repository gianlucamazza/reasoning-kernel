"""Verify an index serves precisely the built artifacts. Read-only and bounded."""

import hashlib
import json
import sys
import time
import tomllib
import urllib.request
from pathlib import Path


def expected_artifacts(directory: Path) -> dict[str, str]:
    """Return checksums for exactly one wheel and one source distribution."""
    wheels = list(directory.glob("*.whl"))
    sdists = list(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("expected one wheel and one sdist")
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (*wheels, *sdists)}


def main() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    repository = sys.argv[2] if len(sys.argv) > 2 else "testpypi"
    indexes = {
        "testpypi": ("https://test.pypi.org", "https://test-files.pythonhosted.org/"),
        "pypi": ("https://pypi.org", "https://files.pythonhosted.org/"),
    }
    if repository not in indexes:
        raise ValueError("repository must be testpypi or pypi")
    index, artifact_host = indexes[repository]
    endpoint = f"{index}/pypi/{project['name']}/{project['version']}/json"
    expected = expected_artifacts(Path(sys.argv[1]))
    for attempt in range(5):
        try:
            with urllib.request.urlopen(endpoint, timeout=10) as response:
                files = json.load(response)["urls"]
            found = {f["filename"]: f for f in files}
            for name, checksum in expected.items():
                artifact = found[name]
                if artifact["digests"]["sha256"] != checksum:
                    raise ValueError(f"{repository} metadata checksum mismatch")
                url = artifact["url"]
                if not url.startswith(artifact_host):
                    raise ValueError(f"unexpected {repository} artifact host")
                with urllib.request.urlopen(url, timeout=10) as response:
                    if hashlib.sha256(response.read()).hexdigest() != checksum:
                        raise ValueError(f"served {repository} artifact checksum mismatch")
            print(f"{repository} serves the exact wheel and sdist selected for promotion.")
            return
        except (OSError, KeyError):
            if attempt == 4:
                raise
            time.sleep(2)


if __name__ == "__main__":
    main()
