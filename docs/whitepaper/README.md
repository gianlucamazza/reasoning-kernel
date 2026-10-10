# Working paper

Technical note for the Reasoning Kernel **topology** (capability-mediated architecture;
strong, CaMeL-like form). This is a reference-implementation write-up, not a peer-reviewed
paper, a safety certificate, or a proof that prompt injection cannot cause an unauthorized
effect. Claims are scoped in the README *Threat model & limits*.

| Artifact | Role |
| --- | --- |
| [reasoning-kernel-whitepaper.md](reasoning-kernel-whitepaper.md) | Canonical source (Markdown) |
| [reasoning-kernel-whitepaper.pdf](reasoning-kernel-whitepaper.pdf) | Typeset snapshot (2026-10-07; Markdown is canonical for later claim-scope edits) |
| [zenodo-metadata.json](zenodo-metadata.json) | Draft deposit metadata only |

**Status.** In-repository draft. MIT, matching the software. Software line:
[`capability-reasoning-kernel`](https://pypi.org/project/capability-reasoning-kernel/)
on PyPI. Primary scientific reference: CaMeL, [arXiv:2503.18813](https://arxiv.org/abs/2503.18813).

**No DOI is claimed.** A Zenodo deposit is **on hold** pending Owner instructions. Do not
invent a `10.5281/zenodo.*` identifier for this paper, and do not reuse the separate
emotional-memory Zenodo records.

## Regenerating the PDF

This repository does not run a PDF build in CI. The committed PDF is the review snapshot
copied from the 2026-10-07 artifact pack. After Markdown edits, regenerate locally with any
Pandoc-compatible toolchain, for example:

```bash
pandoc docs/whitepaper/reasoning-kernel-whitepaper.md \
  -o docs/whitepaper/reasoning-kernel-whitepaper.pdf
```

Keep the Markdown and PDF in lockstep before review or a future deposit.
