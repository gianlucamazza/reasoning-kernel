"""Opaque id newtypes used across the kernel."""

from __future__ import annotations

from typing import NewType

StepId = NewType("StepId", str)
RunId = NewType("RunId", str)
