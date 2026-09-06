"""Documentation contract tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from reasoning_kernel import (
    PLLM,
    QLLM,
    FakeProvider,
    RunContext,
    RunId,
    RunSession,
    SQLiteTraceSink,
    TrustedQuery,
)
from reasoning_kernel.demo.email_exfil import CLEAN_BODY, benign_plan, make_world
from reasoning_kernel.tools.demo_mail import (
    DEMO_GRANT,
    Q_SCHEMAS,
    EmailSummary,
    RecipientIsUserPolicy,
    build_registry,
)

ROOT = Path(__file__).resolve().parents[1]


def test_documentation_contract() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/check_docs.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_landing_operational_example(tmp_path: Path) -> None:
    ctx = RunContext(
        run_id=RunId("documented-operational-example"),
        user="user@example.com",
        query=TrustedQuery(text="Summarize my latest email and send it to me"),
    )
    provider = FakeProvider(
        {
            "Plan": benign_plan(ctx.run_id),
            "EmailSummary": EmailSummary(text="OK"),
        }
    )

    with SQLiteTraceSink(tmp_path / "audit.sqlite") as sink:
        session = RunSession(
            ctx=ctx,
            registry=build_registry(make_world(CLEAN_BODY)),
            grant=DEMO_GRANT,
            declass=RecipientIsUserPolicy(),
            planner=PLLM(provider, grant=DEMO_GRANT),
            quarantine=QLLM(provider),
            q_schemas=Q_SCHEMAS,
            sink=sink,
        )
        result = session.run()

    assert result.status == "succeeded"
    assert [(effect.tool, effect.status) for effect in result.effects] == [
        ("read_inbox", "completed"),
        ("send_email", "completed"),
    ]
