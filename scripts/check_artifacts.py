"""Smoke-test the wheel outside the source tree and without editable installs."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    wheels = list(Path(sys.argv[1]).resolve().glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("expected exactly one wheel in distribution directory")
    with tempfile.TemporaryDirectory(prefix="rk-wheel-") as directory:
        python = Path(directory) / "venv/bin/python"
        subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(python.parent.parent)], check=True
        )
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), str(wheels[0])], check=True
        )
        env = {**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1"}
        subprocess.run(
            [
                str(python),
                "-c",
                "import reasoning_kernel as rk; "
                "assert all(hasattr(rk, n) for n in rk.__all__); "
                "assert rk.RunLimits.operational().max_llm_calls == 32",
            ],
            cwd=directory,
            env=env,
            check=True,
        )
        subprocess.run(
            [str(python), "-m", "reasoning_kernel.demo.email_exfil"],
            cwd=directory,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                str(python.parent / "reasoning-kernel-conformance"),
                "reasoning_kernel.conformance.reference:reference_suite",
            ],
            cwd=directory,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    print("Wheel import, demo and conformance CLI passed in an isolated environment.")


if __name__ == "__main__":
    main()
