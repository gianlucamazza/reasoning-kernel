"""The demo tools fail closed on malformed world state instead of raising a raw IndexError.

``read_inbox`` returning ``inbox[-1]`` would ``IndexError`` on an empty inbox; the kernel must see
a semantic error it can record and fail the run closed, not an opaque crash.
"""

from __future__ import annotations

import pytest

from reasoning_kernel.tools.demo_mail import MailWorld, ReadInboxIn, build_registry


def test_read_inbox_on_empty_inbox_raises_value_error() -> None:
    registry = build_registry(MailWorld(inbox=[], contacts=[]))
    read_inbox = registry.get("read_inbox").callable
    with pytest.raises(ValueError, match="inbox is empty"):
        read_inbox(ReadInboxIn())
