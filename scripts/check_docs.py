"""Check documentation structure and release-contract parity without network access."""

from __future__ import annotations

import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_FILES = (ROOT / "README.md", ROOT / "SECURITY.md", *(ROOT / "docs").glob("*.md"))


class _LandingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if identifier := attributes.get("id"):
            self.ids.append(identifier)
        if tag in {"a", "link"} and (href := attributes.get("href")):
            self.hrefs.append(href)


def _local_target(source: Path, href: str) -> Path | None:
    target = href.split("#", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return None
    return (source.parent / target).resolve()


def documentation_errors() -> list[str]:
    errors: list[str] = []
    landing_path = ROOT / "docs/index.html"
    landing = landing_path.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    conformance = (ROOT / "docs/CONFORMANCE.md").read_text(encoding="utf-8")
    operations = (ROOT / "docs/OPERATIONS.md").read_text(encoding="utf-8")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]

    parser = _LandingParser()
    parser.feed(landing)
    duplicates = sorted(
        {identifier for identifier in parser.ids if parser.ids.count(identifier) > 1}
    )
    errors.extend(f"duplicate landing id: {identifier}" for identifier in duplicates)
    identifiers = set(parser.ids)
    for href in parser.hrefs:
        if href.startswith("#") and href[1:] not in identifiers:
            errors.append(f"missing landing anchor: {href}")
        elif (target := _local_target(landing_path, href)) is not None and not target.exists():
            errors.append(f"missing landing target: {href}")

    markdown_link = re.compile(r"\[[^]]+\]\(([^)]+)\)")
    for source in MARKDOWN_FILES:
        for href in markdown_link.findall(source.read_text(encoding="utf-8")):
            if (target := _local_target(source, href)) is not None and not target.exists():
                errors.append(f"missing Markdown target in {source.relative_to(ROOT)}: {href}")

    required_landing = {
        f"capability-reasoning-kernel=={version}",
        f'"softwareVersion": "{version}"',
        "RunSession",
        "gate-v1",
        "operational-v1",
    }
    errors.extend(
        f"landing missing release contract: {value}"
        for value in sorted(required_landing)
        if value not in landing
    )
    for profile in ("gate-v1", "operational-v1"):
        if profile not in conformance:
            errors.append(f"conformance guide missing profile: {profile}")

    stale_claims = {
        "can cannot": readme,
        "structurally harmless": landing,
        "The model never reads raw reality": landing,
        "There is no facade": landing,
        "A fixed operational profile": landing,
        "vetted skeleton": readme + landing,
    }
    errors.extend(
        f"stale documentation claim: {claim}"
        for claim, text in stale_claims.items()
        if claim in text
    )
    if operations.startswith("# Operational embedding and migration (0.5)"):
        errors.append("operations guide still identifies itself as 0.5")

    return errors


def main() -> int:
    errors = documentation_errors()
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Documentation links, anchors, claims and release metadata are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
