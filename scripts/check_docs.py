"""Check documentation structure and release-contract parity without network access."""

from __future__ import annotations

import json
import re
import tomllib
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_FILES = (
    ROOT / "README.md",
    ROOT / "SECURITY.md",
    *sorted((ROOT / "docs").rglob("*.md")),
)
WHITEPAPER_MD = ROOT / "docs/whitepaper/reasoning-kernel-whitepaper.md"
WHITEPAPER_PDF = ROOT / "docs/whitepaper/reasoning-kernel-whitepaper.pdf"
ZENODO_METADATA = ROOT / "docs/whitepaper/zenodo-metadata.json"
# Emotional-memory records may appear only as excluded identifiers, never as this paper's DOI.
EXCLUDED_ZENODO_DOIS = frozenset({"10.5281/zenodo.19972258", "10.5281/zenodo.22724258"})


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
        "structurally unable": readme + landing,
        "cannot bypass authorization": readme + landing,
        "cannot bypass deterministic authorization": readme + landing,
        "True by construction": landing,
        "The pattern guarantees": readme + landing,
        "Honest limits": readme + landing,
        "The model never reads raw reality": landing,
        "There is no facade": landing,
        "A fixed operational profile": landing,
        "vetted skeleton": readme + landing,
        "provably": readme + landing,
        "blocking proofs": readme + landing,
    }
    errors.extend(
        f"stale documentation claim: {claim}"
        for claim, text in stale_claims.items()
        if claim in text
    )
    if "Threat model & limits" not in readme:
        errors.append("README missing Threat model & limits section")
    if "Threat model" not in landing:
        errors.append("landing missing Threat model section")
    if operations.startswith("# Operational embedding and migration (0.5)"):
        errors.append("operations guide still identifies itself as 0.5")

    errors.extend(_whitepaper_errors(readme, landing))
    return errors


def _whitepaper_errors(readme: str, landing: str) -> list[str]:
    errors: list[str] = []
    for path in (WHITEPAPER_MD, WHITEPAPER_PDF, ZENODO_METADATA):
        if not path.exists():
            errors.append(f"missing whitepaper artifact: {path.relative_to(ROOT)}")
    if "docs/whitepaper/reasoning-kernel-whitepaper.md" not in readme:
        errors.append("README missing working-paper Markdown link")
    if "whitepaper/reasoning-kernel-whitepaper.pdf" not in landing:
        errors.append("landing missing working-paper PDF link")

    if not WHITEPAPER_MD.exists() or not ZENODO_METADATA.exists():
        return errors

    whitepaper = WHITEPAPER_MD.read_text(encoding="utf-8")
    if "No DOI is claimed" not in whitepaper:
        errors.append("whitepaper must state that no DOI is claimed")
    if "topology" not in whitepaper.lower():
        errors.append("whitepaper must describe the work as a topology")
    if "2503.18813" not in whitepaper:
        errors.append("whitepaper must cite CaMeL arXiv:2503.18813")
    if "capability-reasoning-kernel" not in whitepaper:
        errors.append("whitepaper must name the PyPI package capability-reasoning-kernel")
    if "peer-review" in whitepaper.lower() and "No peer-review" not in whitepaper:
        errors.append("whitepaper mentions peer review without an explicit non-claim")

    found_dois = set(re.findall(r"10\.5281/zenodo\.\d+", whitepaper))
    unexpected = sorted(found_dois - EXCLUDED_ZENODO_DOIS)
    if unexpected:
        errors.append(f"whitepaper claims unexpected Zenodo DOI: {', '.join(unexpected)}")
    for doi in sorted(found_dois & EXCLUDED_ZENODO_DOIS):
        idx = whitepaper.find(doi)
        window = whitepaper[max(0, idx - 160) : idx + 160].lower()
        if "do not" not in window and "different" not in window:
            errors.append(f"emotional-memory DOI {doi} must appear only as a non-identifier")

    metadata = json.loads(ZENODO_METADATA.read_text(encoding="utf-8"))
    if "doi" in metadata or "doi" in metadata.get("metadata", {}):
        errors.append("zenodo metadata draft must not include a DOI")
    deposit_status = str(metadata.get("deposit_status", ""))
    if "ON HOLD" not in deposit_status:
        errors.append("zenodo metadata draft must mark deposit as ON HOLD")
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
