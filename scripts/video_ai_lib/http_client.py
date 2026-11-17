from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping

from .config import redact


@dataclass
class ApiError(RuntimeError):
    kind: str
    service: str
    message: str
    status: int | None = None
    detail: object | None = None

    def __str__(self) -> str:
        suffix = f" (HTTP {self.status})" if self.status else ""
        return f"{self.service}: {self.message}{suffix}"


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> object:
        if not self.body:
            return {}
        return json.loads(self.body.decode("utf-8"))


def _error_kind(status: int) -> str:
    if status == 401:
        return "authentication_refused"
    if status == 403:
        return "permission_insufficient"
    if status in {402, 409, 429}:
        return "usage_or_limit"
    if status >= 500:
        return "provider_unavailable"
    return "request_invalid"


def request(
    service: str,
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    json_body: object | None = None,
    raw_body: bytes | None = None,
    timeout: float = 30.0,
    secrets: tuple[str, ...] = (),
) -> Response:
    if json_body is not None and raw_body is not None:
        raise ValueError("json_body e raw_body são mutuamente exclusivos")
    body = raw_body
    request_headers = {"User-Agent": "criacao-de-video-ia/1.0"}
    if headers:
        request_headers.update(headers)
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return Response(
                status=res.status,
                headers={key.lower(): value for key, value in res.headers.items()},
                body=res.read(),
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        detail: object
        try:
            detail = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = raw.decode("utf-8", errors="replace")[:2000]
        detail = redact(detail, secrets)
        raise ApiError(
            _error_kind(exc.code),
            service,
            "requisição recusada",
            status=exc.code,
            detail=detail,
        ) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
        safe = redact(str(getattr(exc, "reason", exc)), secrets)
        raise ApiError("network_failure", service, f"falha de rede: {safe}") from None


def request_json(*args, **kwargs) -> tuple[Response, object]:
    response = request(*args, **kwargs)
    try:
        return response, response.json()
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError("invalid_response", str(args[0] if args else "API"), f"JSON inválido: {exc}") from None
