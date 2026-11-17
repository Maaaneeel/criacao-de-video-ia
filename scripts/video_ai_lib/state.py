from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import default_models, state_root


class StateError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_slug(slug: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", slug):
        raise StateError("Slug inválido; use letras minúsculas, números e hífens")
    return slug


def project_dir(slug: str) -> Path:
    return state_root() / validate_slug(slug)


def state_file(slug: str) -> Path:
    return project_dir(slug) / "state.json"


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def atomic_write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def read_state(slug: str) -> dict:
    path = state_file(slug)
    if not path.is_file():
        raise StateError(f"Projeto não inicializado: {slug}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"Estado inválido em {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StateError("Estado precisa ser um objeto JSON")
    return value


@contextlib.contextmanager
def locked_state(slug: str) -> Iterator[dict]:
    directory = project_dir(slug)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".state.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state = read_state(slug)
        yield state
        state["updated_at"] = now_iso()
        atomic_write_json(state_file(slug), state)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def initialize(slug: str, title: str, idea: str) -> tuple[Path, dict]:
    directory = project_dir(slug)
    path = state_file(slug)
    if path.exists():
        raise StateError(f"Estado já existe e não foi sobrescrito: {path}")
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("plans", "references", "voices", "clips", "sfx", "lipsync", "hyperframes", "review", "final"):
        (directory / name).mkdir(exist_ok=True)
    timestamp = now_iso()
    state = {
        "schema_version": 1,
        "project_id": str(uuid.uuid4()),
        "slug": slug,
        "title": title,
        "idea": idea,
        "created_at": timestamp,
        "updated_at": timestamp,
        "models": default_models(),
        "approvals": {
            "references": {"approved": False},
            "script": {"approved": False},
            "review": {"approved": False},
        },
        "voice_map": {},
        "plan": None,
        "actions": {},
        "artifacts": [],
        "history": [{"at": timestamp, "event": "project_initialized"}],
        "evidence": {},
    }
    atomic_write_json(path, state)
    return path, state


def add_action(state: dict, *, provider: str, kind: str, scene: str | None, model: str, payload: object) -> dict:
    action_id = f"{kind}-{uuid.uuid4().hex[:12]}"
    action = {
        "id": action_id,
        "provider": provider,
        "kind": kind,
        "scene": scene,
        "model": model,
        "payload": payload,
        "payload_hash": canonical_hash(payload),
        "status": "prepared",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    state.setdefault("actions", {})[action_id] = action
    state.setdefault("history", []).append({"at": now_iso(), "event": "action_prepared", "action": action_id})
    return action


def update_action(state: dict, action_id: str, **changes) -> dict:
    try:
        action = state["actions"][action_id]
    except KeyError as exc:
        raise StateError(f"Ação desconhecida: {action_id}") from exc
    action.update(changes)
    action["updated_at"] = now_iso()
    return action


def safe_output_path(slug: str, relative: str) -> Path:
    base = project_dir(slug).resolve()
    result = (base / relative).resolve()
    try:
        result.relative_to(base)
    except ValueError as exc:
        raise StateError("Caminho de saída fora do projeto") from exc
    result.parent.mkdir(parents=True, exist_ok=True)
    return result
