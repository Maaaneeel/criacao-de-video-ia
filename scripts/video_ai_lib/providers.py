from __future__ import annotations

import json
import mimetypes
import os
import re
import urllib.parse
from pathlib import Path
from typing import Callable

from .config import default_models, load_env, redact
from .http_client import ApiError, Response, request, request_json


def _diagnostic(name: str, key_name: str, call: Callable[[str], tuple[Response, object]], *, optional: bool = False) -> dict:
    env = load_env()
    key = env.get(key_name, "")
    if not key:
        return {
            "service": name,
            "result": "not_configured_optional" if optional else "key_missing",
            "authenticated": False,
        }
    try:
        response, _ = call(key)
        return {"service": name, "result": "authenticated", "authenticated": True, "http_status": response.status}
    except ApiError as exc:
        return {
            "service": name,
            "result": exc.kind,
            "authenticated": False,
            "http_status": exc.status,
            "error": str(exc),
            "detail": redact(exc.detail, (key,)),
        }


def fal_price(model: str, key: str | None = None) -> dict:
    if key is None:
        key = load_env(required=("FAL_KEY",))["FAL_KEY"]
    query = urllib.parse.urlencode({"endpoint_id": model})
    _, data = request_json(
        "fal.ai",
        f"https://api.fal.ai/v1/models/pricing?{query}",
        headers={"Authorization": f"Key {key}"},
        secrets=(key,),
    )
    if not isinstance(data, dict):
        raise ApiError("invalid_response", "fal.ai", "resposta de preço inválida")
    return data


def diagnose_all(only: set[str] | None = None) -> list[dict]:
    models = default_models()
    checks = {
        "openrouter": lambda: _diagnostic(
            "OpenRouter",
            "OPENROUTER_API_KEY",
            lambda key: request_json(
                "OpenRouter",
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {key}"},
                secrets=(key,),
            ),
            optional=True,
        ),
        "elevenlabs": lambda: _diagnostic(
            "ElevenLabs",
            "ELEVENLABS_API_KEY",
            lambda key: request_json(
                "ElevenLabs",
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": key},
                secrets=(key,),
            ),
        ),
        "fal": lambda: _diagnostic(
            "fal.ai",
            "FAL_KEY",
            lambda key: (
                Response(200, {}, b""),
                fal_price(models["seedream"], key),
            ),
        ),
        "sync": lambda: _diagnostic(
            "Sync Labs",
            "SYNC_API_KEY",
            lambda key: request_json(
                "Sync Labs",
                "https://api.sync.so/v2/account",
                headers={"x-api-key": key},
                secrets=(key,),
            ),
        ),
    }
    selected = checks.keys() if not only else (name for name in checks if name in only)
    return [checks[name]() for name in selected]


def openrouter_image_endpoints(model: str) -> dict:
    key = load_env(required=("OPENROUTER_API_KEY",))["OPENROUTER_API_KEY"]
    parts = model.split("/", 1)
    if len(parts) != 2 or not all(parts):
        raise ApiError("request_invalid", "OpenRouter", "slug de modelo inválido")
    author = urllib.parse.quote(parts[0], safe="")
    slug = urllib.parse.quote(parts[1], safe="")
    _, data = request_json(
        "OpenRouter",
        f"https://openrouter.ai/api/v1/images/models/{author}/{slug}/endpoints",
        headers={"Authorization": f"Bearer {key}"},
        secrets=(key,),
    )
    if not isinstance(data, dict) or not isinstance(data.get("endpoints"), list):
        raise ApiError("invalid_response", "OpenRouter", "catálogo de endpoints inválido")
    return data


def openrouter_generate_image(model: str, payload: dict) -> dict:
    key = load_env(required=("OPENROUTER_API_KEY",))["OPENROUTER_API_KEY"]
    body = {"model": model, **payload}
    _, data = request_json(
        "OpenRouter",
        "https://openrouter.ai/api/v1/images",
        method="POST",
        headers={"Authorization": f"Bearer {key}"},
        json_body=body,
        timeout=300,
        secrets=(key,),
    )
    if not isinstance(data, dict) or not isinstance(data.get("data"), list) or not data["data"]:
        raise ApiError("invalid_response", "OpenRouter", "geração não retornou imagens")
    return data


def openrouter_video_models() -> dict:
    key = load_env(required=("OPENROUTER_API_KEY",))["OPENROUTER_API_KEY"]
    _, data = request_json(
        "OpenRouter",
        "https://openrouter.ai/api/v1/videos/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
        secrets=(key,),
    )
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ApiError("invalid_response", "OpenRouter", "catálogo de vídeo inválido")
    return data


def openrouter_submit_video(model: str, payload: dict) -> dict:
    key = load_env(required=("OPENROUTER_API_KEY",))["OPENROUTER_API_KEY"]
    _, data = request_json(
        "OpenRouter",
        "https://openrouter.ai/api/v1/videos",
        method="POST",
        headers={"Authorization": f"Bearer {key}"},
        json_body={"model": model, **payload},
        timeout=120,
        secrets=(key,),
    )
    if not isinstance(data, dict) or not data.get("id") or not data.get("polling_url"):
        raise ApiError("invalid_response", "OpenRouter", "submissão de vídeo não retornou job e polling_url")
    return data


def _trusted_openrouter_video_url(url: str) -> str:
    absolute = urllib.parse.urljoin("https://openrouter.ai", url)
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme != "https" or parsed.hostname != "openrouter.ai" or not parsed.path.startswith("/api/v1/videos/"):
        raise ApiError("invalid_response", "OpenRouter", "URL de job de vídeo não confiável")
    return absolute


def openrouter_get_video(url: str) -> dict:
    key = load_env(required=("OPENROUTER_API_KEY",))["OPENROUTER_API_KEY"]
    _, data = request_json(
        "OpenRouter",
        _trusted_openrouter_video_url(url),
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
        secrets=(key,),
    )
    if not isinstance(data, dict) or not data.get("status"):
        raise ApiError("invalid_response", "OpenRouter", "consulta de vídeo inválida")
    return data


def openrouter_video_content(job_id: str, index: int = 0) -> Response:
    key = load_env(required=("OPENROUTER_API_KEY",))["OPENROUTER_API_KEY"]
    safe_id = urllib.parse.quote(job_id, safe="")
    return request(
        "OpenRouter",
        f"https://openrouter.ai/api/v1/videos/{safe_id}/content?index={int(index)}",
        headers={"Authorization": f"Bearer {key}"},
        timeout=600,
        secrets=(key,),
    )


def fal_submit(model: str, payload: dict) -> dict:
    key = load_env(required=("FAL_KEY",))["FAL_KEY"]
    encoded_model = urllib.parse.quote(model, safe="/")
    _, data = request_json(
        "fal.ai",
        f"https://queue.fal.run/{encoded_model}",
        method="POST",
        headers={"Authorization": f"Key {key}"},
        json_body=payload,
        timeout=60,
        secrets=(key,),
    )
    if not isinstance(data, dict) or not data.get("request_id"):
        raise ApiError("invalid_response", "fal.ai", "submissão não retornou request_id")
    return data


def _trusted_fal_queue_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"queue.fal.run", "fal.run"}:
        raise ApiError("invalid_response", "fal.ai", "URL de fila não confiável")
    return url


def fal_get(url: str) -> dict:
    key = load_env(required=("FAL_KEY",))["FAL_KEY"]
    _, data = request_json(
        "fal.ai",
        _trusted_fal_queue_url(url),
        headers={"Authorization": f"Key {key}"},
        timeout=60,
        secrets=(key,),
    )
    if not isinstance(data, dict):
        raise ApiError("invalid_response", "fal.ai", "resposta de fila inválida")
    return data


def elevenlabs_tts(*, voice_id: str, text: str, model: str, output_format: str = "mp3_44100_128") -> Response:
    key = load_env(required=("ELEVENLABS_API_KEY",))["ELEVENLABS_API_KEY"]
    voice = urllib.parse.quote(voice_id, safe="")
    fmt = urllib.parse.quote(output_format, safe="_")
    return request(
        "ElevenLabs",
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format={fmt}",
        method="POST",
        headers={"xi-api-key": key, "Accept": "audio/mpeg"},
        json_body={"text": text, "model_id": model},
        timeout=180,
        secrets=(key,),
    )


def sync_submit(payload: dict, idempotency_key: str) -> dict:
    key = load_env(required=("SYNC_API_KEY",))["SYNC_API_KEY"]
    _, data = request_json(
        "Sync Labs",
        "https://api.sync.so/v2/generate",
        method="POST",
        headers={"x-api-key": key, "Idempotency-Key": idempotency_key},
        json_body=payload,
        timeout=120,
        secrets=(key,),
    )
    if not isinstance(data, dict) or not data.get("id"):
        raise ApiError("invalid_response", "Sync Labs", "submissão não retornou id")
    return data


def sync_upload_asset(path: Path, asset_type: str, content_type: str) -> dict:
    key = load_env(required=("SYNC_API_KEY",))["SYNC_API_KEY"]
    raw = path.read_bytes()
    headers = {"x-api-key": key}
    _, upload = request_json(
        "Sync Labs",
        "https://api.sync.so/v2/assets/upload",
        method="POST",
        headers=headers,
        json_body={"fileName": path.name, "contentType": content_type, "size": len(raw)},
        timeout=60,
        secrets=(key,),
    )
    if not isinstance(upload, dict) or not upload.get("uploadUrl") or not upload.get("url"):
        raise ApiError("invalid_response", "Sync Labs", "presign de asset inválido")
    upload_url = str(upload["uploadUrl"])
    public_url = str(upload["url"])
    request(
        "Sync Labs upload",
        upload_url,
        method="PUT",
        headers={"Content-Type": content_type},
        raw_body=raw,
        timeout=600,
        secrets=(upload_url,),
    )
    _, asset = request_json(
        "Sync Labs",
        "https://api.sync.so/v2/assets",
        method="POST",
        headers=headers,
        json_body={"url": public_url, "type": asset_type, "name": path.name},
        timeout=120,
        secrets=(key, upload_url),
    )
    if not isinstance(asset, dict) or not asset.get("id"):
        raise ApiError("invalid_response", "Sync Labs", "registro de asset não retornou id")
    return {"id": asset["id"], "type": asset.get("type") or asset_type, "size": asset.get("size") or len(raw)}


def sync_get(generation_id: str) -> dict:
    key = load_env(required=("SYNC_API_KEY",))["SYNC_API_KEY"]
    safe_id = urllib.parse.quote(generation_id, safe="")
    _, data = request_json(
        "Sync Labs",
        f"https://api.sync.so/v2/generate/{safe_id}",
        headers={"x-api-key": key},
        timeout=60,
        secrets=(key,),
    )
    if not isinstance(data, dict):
        raise ApiError("invalid_response", "Sync Labs", "resposta de geração inválida")
    return data


def _extension(headers: dict[str, str], url: str, fallback: str = ".bin") -> str:
    name = Path(urllib.parse.urlparse(url).path).name
    suffix = Path(name).suffix
    if suffix and re.fullmatch(r"\.[A-Za-z0-9]{1,6}", suffix):
        return suffix.lower()
    content_type = headers.get("content-type", "").split(";", 1)[0]
    return mimetypes.guess_extension(content_type) or fallback


def download(url: str, destination_without_extension: Path) -> Path:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ApiError("invalid_response", "download", "URL de resultado inválida")
    response = request("download", url, timeout=300)
    suffix = destination_without_extension.suffix or _extension(response.headers, url)
    destination = destination_without_extension if destination_without_extension.suffix else destination_without_extension.with_suffix(suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Resultado existente não foi sobrescrito: {destination}")
    temp = destination.with_name(f".{destination.name}.part-{os.getpid()}")
    try:
        with temp.open("xb") as handle:
            handle.write(response.body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, destination)
    finally:
        if temp.exists():
            temp.unlink()
    return destination


def media_urls(value: object) -> list[str]:
    urls: list[str] = []

    def visit(item: object, key_hint: str = "") -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                visit(nested, str(key).lower())
        elif isinstance(item, list):
            for nested in item:
                visit(nested, key_hint)
        elif isinstance(item, str) and item.startswith("https://"):
            host = urllib.parse.urlparse(item).hostname or ""
            queue_metadata = host == "queue.fal.run" or key_hint in {"status_url", "response_url", "cancel_url"}
            media_hint = key_hint in {"url", "outputurl", "output_url", "video", "audio", "image"}
            if media_hint and not queue_metadata and item not in urls:
                urls.append(item)

    visit(value)
    return urls
