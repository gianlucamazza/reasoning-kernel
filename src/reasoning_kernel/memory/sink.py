"""Durable, payload-free audit. Incomplete invocations are never replayed automatically."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from reasoning_kernel.schemas.ids import RunId
from reasoning_kernel.schemas.trace import AuditEvent

_SCHEMA_VERSION = 1


class TraceStorageError(RuntimeError):
    """Audit could not be recorded. Contains no backend error text."""


class TraceSink(Protocol):
    def start(self, run_id: RunId) -> None: ...
    def append(self, root_run_id: RunId, event: AuditEvent) -> None: ...


class MemoryTraceSink:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[RunId, list[AuditEvent]] = {}

    def start(self, run_id: RunId) -> None:
        with self._lock:
            if run_id in self._runs:
                raise TraceStorageError("run already exists")
            self._runs[run_id] = []

    def append(self, root_run_id: RunId, event: AuditEvent) -> None:
        with self._lock:
            events = self._runs[root_run_id]
            if event.seq != len(events):
                raise TraceStorageError("invalid audit sequence")
            events.append(event.model_copy(deep=True))

    def read(self, run_id: RunId) -> list[AuditEvent]:
        with self._lock:
            return [e.model_copy(deep=True) for e in self._runs[run_id]]


class SQLiteTraceSink:
    """Serialized connection, WAL and FULL sync. Host owns permissions and retention.

    Use a local filesystem. Existing root ids, including crashed runs, cannot be restarted.
    """

    def __init__(self, path: str | Path) -> None:
        self._lock = threading.Lock()
        try:
            self._db = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
        except sqlite3.Error:
            raise TraceStorageError("cannot open audit database") from None
        try:
            self._initialize()
        except TraceStorageError:
            self._db.close()
            raise
        except sqlite3.Error:
            self._db.close()
            raise TraceStorageError("cannot initialize audit database") from None

    def _initialize(self) -> None:
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version > _SCHEMA_VERSION:
            raise TraceStorageError("audit database schema is newer than this package")
        if version not in (0, _SCHEMA_VERSION):
            raise TraceStorageError("unsupported audit database schema")
        with self._db:
            self._db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY)")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "root_run_id TEXT NOT NULL REFERENCES runs(run_id),"
                " seq INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(root_run_id, seq))"
            )
            self._validate_layout()
            if version == 0:
                # Version zero is the schema shipped by the first 0.5 candidate implementation.
                self._db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def _validate_layout(self) -> None:
        expected = {
            "runs": ["run_id"],
            "events": ["root_run_id", "seq", "payload"],
        }
        for table, columns in expected.items():
            actual = [row[1] for row in self._db.execute(f"PRAGMA table_info({table})")]
            if actual != columns:
                raise TraceStorageError("unsupported audit database layout")

    def start(self, run_id: RunId) -> None:
        try:
            with self._lock, self._db:
                self._db.execute("INSERT INTO runs VALUES (?)", (run_id,))
        except sqlite3.Error:
            raise TraceStorageError("cannot reserve audit run") from None

    def append(self, root_run_id: RunId, event: AuditEvent) -> None:
        try:
            with self._lock, self._db:
                self._db.execute("BEGIN IMMEDIATE")
                count = self._db.execute(
                    "SELECT COUNT(*) FROM events WHERE root_run_id = ?", (root_run_id,)
                ).fetchone()[0]
                if event.seq != count:
                    raise TraceStorageError("invalid audit sequence")
                self._db.execute(
                    "INSERT INTO events VALUES (?, ?, ?)",
                    (root_run_id, event.seq, event.model_dump_json()),
                )
        except sqlite3.Error:
            raise TraceStorageError("cannot append audit event") from None

    def read(self, run_id: RunId) -> list[AuditEvent]:
        try:
            with self._lock:
                rows = self._db.execute(
                    "SELECT payload FROM events WHERE root_run_id = ? ORDER BY seq", (run_id,)
                ).fetchall()
        except sqlite3.Error:
            raise TraceStorageError("cannot read audit events") from None
        try:
            return [AuditEvent.model_validate_json(row[0]) for row in rows]
        except ValidationError:
            raise TraceStorageError("invalid audit event payload") from None

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def __enter__(self) -> SQLiteTraceSink:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
