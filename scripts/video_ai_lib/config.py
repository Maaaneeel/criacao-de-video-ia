from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable


SKILL_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_FILE = SKILL_ROOT / "project.json"
ENV_NAMES = (
    "OPENROUTER_API_KEY",
    "ELEVENLABS_API_KEY",
    "FAL_KEY",
    "SYNC_API_KEY",
)


class ConfigurationError(RuntimeError):
    pass


def settings() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Configuração inválida em {SETTINGS_FILE}: {exc}") from exc
    if not isinstance(data, dict) or not data.get("project_root"):
        raise ConfigurationError("project.json não contém project_root")
    return data


def project_root() -> Path:
    root = Path(settings()["project_root"]).expanduser().resolve()
    if not root.is_dir():
        raise ConfigurationError(f"Pasta do projeto não existe: {root}")
    return root


def env_path() -> Path:
    cfg = settings()
    candidate = (project_root() / cfg.get("env_file", ".env")).resolve()
    try:
        candidate.relative_to(project_root())
    except ValueError as exc:
        raise ConfigurationError("env_file precisa ficar dentro da pasta do projeto") from exc
    return candidate


def state_root() -> Path:
    cfg = settings()
    root = (project_root() / cfg.get("state_dir", ".video-ai/projects")).resolve()
    try:
        root.relative_to(project_root())
    except ValueError as exc:
        raise ConfigurationError("state_dir precisa ficar dentro da pasta do projeto") from exc
    return root


def default_models() -> dict[str, str]:
    models = settings().get("models", {})
    if not isinstance(models, dict):
        raise ConfigurationError("models precisa ser um objeto em project.json")
    return {str(key): str(value) for key, value in models.items()}


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_env(required: Iterable[str] = ()) -> dict[str, str]:
    """Load only known keys from the configured .env without executing its contents."""
    path = env_path()
    if not path.is_file():
        raise ConfigurationError(f"Arquivo .env não encontrado: {path}")
    values = {name: "" for name in ENV_NAMES}
    name_re = re.compile(r"^[A-Z][A-Z0-9_]*$")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigurationError(f"Não foi possível ler {path}: {exc}") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, value = line.split("=", 1)
        name = name.strip()
        if not name_re.fullmatch(name) or name not in values:
            continue
        values[name] = _unquote(value.strip())
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise ConfigurationError("Credencial ausente: " + ", ".join(missing))
    return values


def prepare_env() -> dict:
    """Add missing fields without touching existing lines or values."""
    root = project_root()
    path = env_path()
    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    present: set[str] = set()
    for raw in existing_text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" in line and not line.startswith("#"):
            present.add(line.split("=", 1)[0].strip())
    missing = [name for name in ENV_NAMES if name not in present]
    if missing:
        separator = "" if not existing_text or existing_text.endswith("\n") else "\n"
        addition = separator + "".join(f"{name}=\n" for name in missing)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(addition)
    os.chmod(path, 0o600)

    gitignore = root / ".gitignore"
    ignore_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    ignore_lines = {line.strip() for line in ignore_text.splitlines()}
    if ".env" not in ignore_lines:
        separator = "" if not ignore_text or ignore_text.endswith("\n") else "\n"
        with gitignore.open("a", encoding="utf-8") as handle:
            handle.write(separator + ".env\n")
    return {"env_path": str(path), "added": missing, "preserved": sorted(present & set(ENV_NAMES))}


def redact(value: object, secrets: Iterable[str]) -> object:
    secret_values = [item for item in secrets if item]
    if isinstance(value, str):
        text = value
        for secret in secret_values:
            text = text.replace(secret, "[REDACTED]")
        return text
    if isinstance(value, list):
        return [redact(item, secret_values) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, secret_values) for key, item in value.items()}
    return value
