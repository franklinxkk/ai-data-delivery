"""Shared local contract utilities. No network calls or business decisions."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

import yaml


def load(path):
    with open(path, encoding="utf-8-sig") as stream:
        return yaml.safe_load(stream)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     default=str).encode()).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write(path, value):
    """Atomic replacement of one artifact, including Unicode paths on Windows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
               if path.suffix == ".json" else
               yaml.safe_dump(value, allow_unicode=True, sort_keys=False))
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".delivery-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def quote(name):
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError("invalid SQL identifier")
    return '"' + name.replace('"', '""') + '"'


def readonly(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only=ON")
    return conn


def snapshot(path):
    """Read a consistent SQLite snapshot (including committed WAL contents)."""
    source = readonly(path)
    conn = sqlite3.connect(":memory:")
    try:
        source.backup(conn)
    finally:
        source.close()
    conn.execute("PRAGMA query_only=ON")
    fingerprint = hashlib.sha256()
    for statement in conn.iterdump():
        fingerprint.update(statement.encode("utf-8"))
        fingerprint.update(b"\n")
    return conn, fingerprint.hexdigest()


def evidence(model, cases=None, mode="static", **extra):
    return {"schema_version": "1.0", "created_at": now(), "mode": mode,
            "model_sha256": digest(model) if model else None,
            "cases_sha256": digest(cases) if cases else None, **extra}


def fields(ds):
    return {field["name"] for field in ds.get("fields", [])}


def keys(value):
    return [value] if isinstance(value, str) else list(value or [])


def relation_keys(rel):
    left = keys(rel.get("from_columns", rel.get("join_key")))
    right = keys(rel.get("to_columns", rel.get("join_key")))
    if not left or len(left) != len(right) or len(set(left)) != len(left) or len(set(right)) != len(right):
        raise ValueError("关系需等长、不重复的 from_columns/to_columns（或同名 join_key）")
    return left, right


def relation_id(rel):
    return rel.get("id") or f"{rel.get('from')}->{rel.get('to')}:{','.join(keys(rel.get('join_key')))}"


def binding_errors(report, model, cases=None, max_age_hours=24):
    ev = report.get("evidence", {})
    errors = []
    if ev.get("model_sha256") != digest(model):
        errors.append("missing/stale model binding")
    if cases and ev.get("cases_sha256") != digest(cases):
        errors.append("missing/stale cases binding")
    try:
        age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(ev["created_at"])
        if not 0 <= age.total_seconds() <= max_age_hours * 3600:
            errors.append("expired/future evidence")
    except (KeyError, ValueError, TypeError):
        errors.append("missing/invalid evidence timestamp")
    return errors
