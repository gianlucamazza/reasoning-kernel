"""Verify TestPyPI serves precisely the artifacts being promoted. Read-only and bounded."""

import hashlib
import json
import sys
import time
import tomllib
import urllib.request
from pathlib import Path


def main() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    endpoint = f"https://test.pypi.org/pypi/{project['name']}/{project['version']}/json"
    expected = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in Path(sys.argv[1]).iterdir()
        if p.is_file()
    }
    if len(expected) != 2:
        raise ValueError("expected one wheel and one sdist")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(endpoint, timeout=10) as response:
                files = json.load(response)["urls"]
            found = {f["filename"]: f for f in files}
            for name, checksum in expected.items():
                artifact = found[name]
                if artifact["digests"]["sha256"] != checksum:
                    raise ValueError("TestPyPI metadata checksum mismatch")
                url = artifact["url"]
                if not url.startswith("https://test-files.pythonhosted.org/"):
                    raise ValueError("unexpected TestPyPI artifact host")
                with urllib.request.urlopen(url, timeout=10) as response:
                    if hashlib.sha256(response.read()).hexdigest() != checksum:
                        raise ValueError("served TestPyPI artifact checksum mismatch")
            print("TestPyPI serves the exact wheel and sdist selected for promotion.")
            return
        except (OSError, KeyError):
            if attempt == 4:
                raise
            time.sleep(2)


if __name__ == "__main__":
    main()
