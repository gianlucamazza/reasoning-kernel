"""The ValueStore is write-once and navigates paths fail-closed, preserving the value's label."""

from __future__ import annotations

import pytest
from conftest import tainted, trusted
from pydantic import BaseModel

from reasoning_kernel.memory.store import ValueStore, _navigate
from reasoning_kernel.schemas.ids import StepId
from reasoning_kernel.schemas.plan import ArgRef


class _Inner(BaseModel):
    text: str


class _Outer(BaseModel):
    summary: _Inner


def test_put_is_write_once() -> None:
    store = ValueStore()
    store.put(StepId("a"), trusted("x"))
    with pytest.raises(ValueError, match="already stored"):
        store.put(StepId("a"), trusted("y"))


def test_navigate_missing_model_field_fails_closed() -> None:
    with pytest.raises(ValueError, match="has no field"):
        _navigate(_Inner(text="hi"), "nope")


def test_navigate_into_dict_key() -> None:
    assert _navigate({"a": {"b": 7}}, "a.b") == 7


def test_navigate_missing_dict_key_fails_closed() -> None:
    with pytest.raises(ValueError, match="not in dict"):
        _navigate({"a": 1}, "b")


def test_navigate_into_scalar_fails_closed() -> None:
    with pytest.raises(ValueError, match="has no"):
        _navigate(42, "x")


def test_resolve_inline_literal_is_trusted() -> None:
    tv = ValueStore().resolve("hello")
    assert tv.value == "hello"
    assert not tv.label.is_tainted


def test_resolve_ref_with_path_preserves_label() -> None:
    src = tainted(_Outer(summary=_Inner(text="body")))
    store = ValueStore()
    store.put(StepId("a"), src)
    out = store.resolve(ArgRef(ref=StepId("a"), path="summary.text"))
    assert out.value == "body"
    assert out.label == src.label  # object-level taint: navigation keeps the whole label
