#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from video_ai_lib.config import ConfigurationError, default_models, prepare_env, project_root
from video_ai_lib.http_client import ApiError
from video_ai_lib.providers import (
    diagnose_all,
    download,
    elevenlabs_tts,
    fal_get,
    fal_price,
    fal_submit,
    media_urls,
    openrouter_generate_image,
    openrouter_get_video,
    openrouter_image_endpoints,
    openrouter_submit_video,
    openrouter_video_content,
    openrouter_video_models,
    sync_get,
    sync_submit,
    sync_upload_asset,
)
from video_ai_lib.state import (
    StateError,
    add_action,
    atomic_write_json,
    canonical_hash,
    initialize,
    locked_state,
    now_iso,
    project_dir,
    read_state,
    safe_output_path,
    update_action,
)


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def load_json_file(path: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"JSON inválido em {path}: {exc}") from exc


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return cleaned[:80] or "item"


def media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise StateError(f"ffprobe falhou para {path.name}: {result.stderr.strip()}")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise StateError(f"ffprobe não retornou duração para {path.name}") from exc


def require_gate(state: dict, gate: str) -> None:
    if not state.get("approvals", {}).get(gate, {}).get("approved"):
        raise StateError(f"Aprovação obrigatória ausente: {gate}")


def find_scene(state: dict, scene_id: str) -> dict | None:
    plan = state.get("plan") or {}
    for scene in plan.get("scenes", []):
        if scene.get("id") == scene_id:
            return scene
    return None


def cmd_prepare_env(_: argparse.Namespace) -> int:
    result = prepare_env()
    emit(result)
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    only = None if args.service == "all" else {args.service}
    results = diagnose_all(only)
    emit(results)
    required_fail = any(item["result"] != "authenticated" for item in results if item["service"] != "OpenRouter")
    return 1 if required_fail else 0


def _version(command: list[str]) -> dict:
    name = command[0]
    if not shutil.which(name):
        return {"available": False, "error": "not_found"}
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": str(exc)}
    first_line = (result.stdout or result.stderr).splitlines()
    return {"available": result.returncode == 0, "version": first_line[0] if first_line else "unknown"}


def cmd_check_deps(_: argparse.Namespace) -> int:
    deps = {
        "python": {"available": True, "version": sys.version.split()[0]},
        "node": _version(["node", "--version"]),
        "npm": _version(["npm", "--version"]),
        "npx": _version(["npx", "--version"]),
        "ffmpeg": _version(["ffmpeg", "-version"]),
        "ffprobe": _version(["ffprobe", "-version"]),
    }
    node_ok = deps["node"].get("available") and int(str(deps["node"]["version"]).lstrip("v").split(".")[0]) >= 22
    deps["node"]["meets_hyperframes_minimum"] = bool(node_ok)
    doctor_checks: dict[str, dict] = {}
    try:
        doctor = subprocess.run(
            ["npx", "hyperframes", "doctor", "--json"],
            cwd=project_root(),
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        doctor_data = json.loads(doctor.stdout)
        doctor_checks = {str(item.get("name")): item for item in doctor_data.get("checks", []) if isinstance(item, dict)}
        deps["hyperframes"] = {
            "available": bool(doctor_checks.get("CLI binary", {}).get("ok")),
            "version": (doctor_data.get("_meta") or {}).get("version"),
            "doctor_ok": doctor_data.get("ok"),
            "required_checks": {name: doctor_checks.get(name) for name in ("Node.js", "FFmpeg", "FFprobe", "Chrome")},
        }
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        deps["hyperframes"] = {"available": False, "error": str(exc)}
    essential_hf = all(doctor_checks.get(name, {}).get("ok") for name in ("Node.js", "FFmpeg", "FFprobe", "Chrome"))
    deps["local_render_ready"] = bool(node_ok and deps["ffmpeg"]["available"] and deps["ffprobe"]["available"] and essential_hf)
    emit(deps)
    return 0 if deps["local_render_ready"] else 1


def cmd_init(args: argparse.Namespace) -> int:
    idea = Path(args.idea_file).read_text(encoding="utf-8") if args.idea_file else args.idea
    if not idea:
        raise StateError("Forneça --idea ou --idea-file")
    path, _ = initialize(args.slug, args.title, idea)
    emit({"created": True, "state": str(path), "project_dir": str(path.parent)})
    return 0


def validate_plan(plan: object) -> dict:
    if not isinstance(plan, dict) or not isinstance(plan.get("visual_bible"), dict) or not isinstance(plan.get("scenes"), list):
        raise StateError("Plano precisa conter visual_bible e scenes")
    seen: set[str] = set()
    for scene in plan["scenes"]:
        if not isinstance(scene, dict) or not scene.get("id"):
            raise StateError("Toda cena precisa de id")
        scene_id = str(scene["id"])
        if scene_id in seen:
            raise StateError(f"ID de cena duplicado: {scene_id}")
        seen.add(scene_id)
        try:
            duration = float(scene["duration_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StateError(f"Duração inválida na cena {scene_id}") from exc
        if duration <= 0:
            raise StateError(f"Duração precisa ser positiva na cena {scene_id}")
    return plan


def cmd_set_plan(args: argparse.Namespace) -> int:
    plan = validate_plan(load_json_file(args.file))
    plan_path = safe_output_path(args.project, "plans/plan.json")
    atomic_write_json(plan_path, plan)
    with locked_state(args.project) as state:
        state["plan"] = plan
        state["plan_hash"] = canonical_hash(plan)
        state["approvals"] = {
            "references": {"approved": False},
            "script": {"approved": False},
            "review": {"approved": False},
        }
        state.setdefault("history", []).append({"at": now_iso(), "event": "plan_updated", "hash": state["plan_hash"]})
    emit({"saved": str(plan_path), "scenes": len(plan["scenes"])})
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    with locked_state(args.project) as state:
        state.setdefault("approvals", {})[args.gate] = {
            "approved": True,
            "at": now_iso(),
            "notes": args.notes or "",
        }
        state.setdefault("history", []).append({"at": now_iso(), "event": "approved", "gate": args.gate})
    emit({"project": args.project, "approved": args.gate})
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    state = read_state(args.project)
    actions = []
    for action in state.get("actions", {}).values():
        actions.append({key: action.get(key) for key in ("id", "provider", "kind", "scene", "model", "status", "request_id", "job_id", "outputs", "error") if key in action})
    emit({
        "project": state.get("slug"),
        "title": state.get("title"),
        "models": state.get("models"),
        "approvals": state.get("approvals"),
        "voice_map": state.get("voice_map"),
        "scenes": len((state.get("plan") or {}).get("scenes", [])),
        "actions": actions,
        "artifacts": state.get("artifacts", []),
        "evidence": state.get("evidence", {}),
    })
    return 0


def cmd_invalidate_scene(args: argparse.Namespace) -> int:
    invalidated = []
    with locked_state(args.project) as state:
        if not find_scene(state, args.scene):
            raise StateError(f"Cena desconhecida: {args.scene}")
        for action in state.get("actions", {}).values():
            if action.get("scene") == args.scene and action.get("status") not in {"stale", "failed"}:
                action["status"] = "stale"
                action["stale_reason"] = args.reason
                action["updated_at"] = now_iso()
                invalidated.append(action["id"])
        state["approvals"]["review"] = {"approved": False}
        state.setdefault("history", []).append({"at": now_iso(), "event": "scene_invalidated", "scene": args.scene, "actions": invalidated})
    emit({"scene": args.scene, "invalidated_actions": invalidated})
    return 0


def cmd_price(args: argparse.Namespace) -> int:
    emit(fal_price(args.model))
    return 0


def _openrouter_cost_summary(catalog: dict, resolution: str) -> dict:
    lines = []
    for endpoint in catalog.get("endpoints", []):
        if not isinstance(endpoint, dict):
            continue
        for price in endpoint.get("pricing", []):
            if isinstance(price, dict):
                lines.append({
                    "provider": endpoint.get("provider_name") or endpoint.get("provider_slug"),
                    "billable": price.get("billable"),
                    "unit": price.get("unit"),
                    "cost_usd": price.get("cost_usd"),
                })
    return {"resolution": resolution, "pricing": lines}


def paid_preview(service: str, kind: str, scene: str, model: str, cost: object) -> None:
    emit({
        "authorization_required": True,
        "service": service,
        "operation": kind,
        "scene": scene,
        "model": model,
        "cost_information": cost,
        "next_step": "Execute novamente com --yes-paid somente após autorização explícita.",
    })


def _expand_local_image_references(payload: dict) -> dict:
    expanded = dict(payload)
    local_references = expanded.pop("local_references", [])
    if not local_references:
        return expanded
    if not isinstance(local_references, list):
        raise StateError("local_references precisa ser uma lista de caminhos")
    expanded["input_references"] = list(expanded.get("input_references", [])) + [
        {"type": "image_url", "image_url": {"url": _data_url(str(path))}} for path in local_references
    ]
    return expanded


def cmd_openrouter_image(args: argparse.Namespace) -> int:
    payload = load_json_file(args.payload)
    if not isinstance(payload, dict) or not isinstance(payload.get("prompt"), str) or not payload["prompt"].strip():
        raise StateError("Payload OpenRouter precisa conter prompt")
    state = read_state(args.project)
    model = args.model or state.get("models", {}).get("openrouter_image") or "bytedance-seed/seedream-5-0-pro"
    catalog = openrouter_image_endpoints(model)
    cost = _openrouter_cost_summary(catalog, str(payload.get("resolution", "auto")))
    if not args.yes_paid:
        paid_preview("OpenRouter", "reference_image", args.scene, model, cost)
        return 3

    payload_hash = canonical_hash({"model": model, **payload})
    with locked_state(args.project) as mutable:
        for existing in mutable.get("actions", {}).values():
            if existing.get("provider") == "OpenRouter" and existing.get("kind") == "reference_image" and existing.get("scene") == args.scene and existing.get("payload_hash") == payload_hash and existing.get("status") in {"prepared", "completed", "submission_unknown"}:
                emit({"reused": True, "action": existing["id"], "status": existing["status"]})
                return 0
        action = add_action(mutable, provider="OpenRouter", kind="reference_image", scene=args.scene, model=model, payload={"model": model, **payload})
        action_id = action["id"]
        mutable.setdefault("models", {})["openrouter_image"] = model
        mutable["reference_provider"] = "OpenRouter"

    try:
        result = openrouter_generate_image(model, _expand_local_image_references(payload))
    except ApiError as exc:
        status = "submission_unknown" if exc.kind == "network_failure" else "failed"
        with locked_state(args.project) as mutable:
            update_action(mutable, action_id, status=status, error={"kind": exc.kind, "message": str(exc), "http_status": exc.status, "detail": exc.detail})
        raise

    outputs = []
    image_metadata = []
    for index, image in enumerate(result.get("data", []), 1):
        if not isinstance(image, dict) or not image.get("b64_json"):
            raise StateError("OpenRouter retornou item de imagem sem b64_json")
        try:
            raw = base64.b64decode(image["b64_json"], validate=True)
        except (ValueError, TypeError) as exc:
            raise StateError("OpenRouter retornou base64 de imagem inválido") from exc
        media_type = str(image.get("media_type") or "image/png").split(";", 1)[0]
        extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(media_type, ".bin")
        output = safe_output_path(args.project, f"references/{safe_name(args.scene)}-{action_id}-{index}{extension}")
        if output.exists():
            raise StateError(f"Saída existente não foi sobrescrita: {output}")
        output.write_bytes(raw)
        outputs.append(str(output))
        image_metadata.append({"path": str(output), "media_type": media_type, "bytes": len(raw)})

    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    with locked_state(args.project) as mutable:
        update_action(mutable, action_id, status="completed", outputs=outputs, images=image_metadata, usage=usage, completed_at=now_iso())
        mutable.setdefault("artifacts", []).extend({"action": action_id, "path": path, "kind": "reference_image"} for path in outputs)
        mutable.setdefault("evidence", {})["OpenRouter Images"] = {"authenticated": True, "generation_tested": True, "last_action": action_id, "model": model}
    emit({"action": action_id, "status": "completed", "model": model, "outputs": outputs, "cost": usage.get("cost")})
    return 0


def _data_url(path_text: str) -> str:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        raise StateError(f"Referência local não encontrada: {path}")
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower())
    if not media_type:
        raise StateError(f"Formato de referência local não suportado: {path.suffix}")
    return f"data:{media_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _expand_local_video_references(payload: dict) -> dict:
    expanded = dict(payload)
    local_references = expanded.pop("local_references", [])
    local_frames = expanded.pop("local_frame_images", [])
    if local_references:
        if not isinstance(local_references, list):
            raise StateError("local_references precisa ser uma lista de caminhos")
        expanded["input_references"] = list(expanded.get("input_references", [])) + [
            {"type": "image_url", "image_url": {"url": _data_url(str(path))}} for path in local_references
        ]
    if local_frames:
        if not isinstance(local_frames, list):
            raise StateError("local_frame_images precisa ser uma lista")
        items = list(expanded.get("frame_images", []))
        for item in local_frames:
            if not isinstance(item, dict) or item.get("frame_type") not in {"first_frame", "last_frame"} or not item.get("path"):
                raise StateError("Cada local_frame_images precisa de path e frame_type válido")
            items.append({"type": "image_url", "image_url": {"url": _data_url(str(item["path"]))}, "frame_type": item["frame_type"]})
        expanded["frame_images"] = items
    return expanded


def _openrouter_video_model(catalog: dict, model: str) -> dict:
    for item in catalog.get("data", []):
        if isinstance(item, dict) and item.get("id") == model:
            return item
    raise StateError(f"Modelo de vídeo OpenRouter não encontrado: {model}")


def cmd_openrouter_video_submit(args: argparse.Namespace) -> int:
    payload = load_json_file(args.payload)
    if not isinstance(payload, dict) or not isinstance(payload.get("prompt"), str) or not payload["prompt"].strip():
        raise StateError("Payload OpenRouter Video precisa conter prompt")
    state = read_state(args.project)
    require_gate(state, "script")
    model = args.model or state.get("models", {}).get("openrouter_video") or "bytedance/seedance-2.5"
    model_info = _openrouter_video_model(openrouter_video_models(), model)
    duration = payload.get("duration")
    resolution = payload.get("resolution")
    aspect_ratio = payload.get("aspect_ratio")
    if duration not in (model_info.get("supported_durations") or []):
        raise StateError(f"Duração {duration} não suportada por {model}")
    if resolution not in (model_info.get("supported_resolutions") or []):
        raise StateError(f"Resolução {resolution} não suportada por {model}")
    if aspect_ratio not in (model_info.get("supported_aspect_ratios") or []):
        raise StateError(f"Proporção {aspect_ratio} não suportada por {model}")
    cost = {"pricing_skus": model_info.get("pricing_skus"), "duration": duration, "resolution": resolution, "aspect_ratio": aspect_ratio}
    if not args.yes_paid:
        paid_preview("OpenRouter", "scene_video", args.scene, model, cost)
        return 3

    payload_hash = canonical_hash({"model": model, **payload})
    with locked_state(args.project) as mutable:
        for existing in mutable.get("actions", {}).values():
            if existing.get("provider") == "OpenRouter" and existing.get("kind") == "scene_video" and existing.get("scene") == args.scene and existing.get("payload_hash") == payload_hash and existing.get("status") in {"prepared", "submitted", "in_progress", "completed", "submission_unknown"}:
                emit({"reused": True, "action": existing["id"], "status": existing["status"]})
                return 0
        action = add_action(mutable, provider="OpenRouter", kind="scene_video", scene=args.scene, model=model, payload={"model": model, **payload})
        action_id = action["id"]
        mutable.setdefault("models", {})["openrouter_video"] = model

    try:
        result = openrouter_submit_video(model, _expand_local_video_references(payload))
    except ApiError as exc:
        status = "submission_unknown" if exc.kind == "network_failure" else "failed"
        with locked_state(args.project) as mutable:
            update_action(mutable, action_id, status=status, error={"kind": exc.kind, "message": str(exc), "http_status": exc.status, "detail": exc.detail})
        raise

    provider_status = str(result.get("status") or "pending")
    local_status = "in_progress" if provider_status == "in_progress" else "submitted"
    with locked_state(args.project) as mutable:
        update_action(mutable, action_id, status=local_status, provider_status=provider_status, job_id=result["id"], polling_url=result["polling_url"], generation_id=result.get("generation_id"), submitted_at=now_iso())
    emit({"action": action_id, "status": result.get("status"), "job_id": result["id"], "model": model})
    return 0


def cmd_openrouter_video_poll(args: argparse.Namespace) -> int:
    state = read_state(args.project)
    action = state.get("actions", {}).get(args.action)
    if not action or action.get("provider") != "OpenRouter" or action.get("kind") != "scene_video":
        raise StateError("Ação OpenRouter Video não encontrada")
    if action.get("status") == "completed":
        emit({"action": args.action, "status": "completed", "outputs": action.get("outputs", []), "reused": True})
        return 0
    if not action.get("polling_url"):
        raise StateError("Ação não possui polling_url; não reenvie automaticamente")
    result = openrouter_get_video(str(action["polling_url"]))
    status = str(result.get("status"))
    if status in {"failed", "cancelled", "expired"}:
        with locked_state(args.project) as mutable:
            update_action(mutable, args.action, status="failed", provider_status=status, error=result.get("error"), polled_at=now_iso())
        emit({"action": args.action, "status": "failed", "provider_status": status, "error": result.get("error")})
        return 1
    if status != "completed":
        with locked_state(args.project) as mutable:
            update_action(mutable, args.action, status="in_progress" if status == "in_progress" else "submitted", provider_status=status, polled_at=now_iso())
        emit({"action": args.action, "status": status})
        return 0

    response = openrouter_video_content(str(action.get("job_id") or result.get("id")))
    media_type = response.headers.get("content-type", "video/mp4").split(";", 1)[0]
    extension = ".webm" if media_type == "video/webm" else ".mp4"
    output = safe_output_path(args.project, f"scenes/{safe_name(str(action['scene']))}-{args.action}{extension}")
    if output.exists():
        raise StateError(f"Saída existente não foi sobrescrita: {output}")
    output.write_bytes(response.body)
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    with locked_state(args.project) as mutable:
        update_action(mutable, args.action, status="completed", outputs=[str(output)], usage=usage, completed_at=now_iso())
        mutable.setdefault("artifacts", []).append({"action": args.action, "path": str(output), "kind": "scene_video"})
        mutable.setdefault("evidence", {})["OpenRouter Videos"] = {"authenticated": True, "generation_tested": True, "last_action": args.action, "model": action.get("model")}
    emit({"action": args.action, "status": "completed", "outputs": [str(output)], "cost": usage.get("cost")})
    return 0


def _expand_local_fal_media(payload: dict) -> dict:
    expanded = dict(payload)
    local_video = expanded.pop("local_video", None)
    if local_video is None:
        return expanded
    path = Path(str(local_video)).expanduser().resolve()
    if not path.is_file():
        raise StateError(f"Vídeo local não encontrado: {path}")
    if path.suffix.lower() not in {".mp4", ".mov", ".webm", ".m4v", ".gif"}:
        raise StateError(f"Formato de vídeo local não suportado: {path.suffix}")
    media_type = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".m4v": "video/x-m4v",
        ".gif": "image/gif",
    }[path.suffix.lower()]
    if path.stat().st_size > 8 * 1024 * 1024:
        raise StateError("Vídeo local excede o limite de 8 MB para data URI do Mirelo")
    expanded["video_url"] = f"data:{media_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    return expanded


def cmd_fal_submit(args: argparse.Namespace) -> int:
    payload = load_json_file(args.payload)
    if not isinstance(payload, dict):
        raise StateError("Payload fal.ai precisa ser um objeto JSON")
    state = read_state(args.project)
    if args.kind in {"seedance", "mirelo"}:
        require_gate(state, "script")
    model = args.model or state.get("models", {}).get(args.kind)
    if not model:
        raise StateError(f"Modelo não configurado para {args.kind}")
    try:
        cost = fal_price(model)
    except ApiError as exc:
        cost = {"available": False, "error": str(exc)}
    if not args.yes_paid:
        paid_preview("fal.ai", args.kind, args.scene, model, cost)
        return 3

    payload_hash = canonical_hash(payload)
    with locked_state(args.project) as mutable:
        for existing in mutable.get("actions", {}).values():
            if existing.get("provider") == "fal.ai" and existing.get("kind") == args.kind and existing.get("scene") == args.scene and existing.get("payload_hash") == payload_hash and existing.get("status") in {"prepared", "submitted", "in_progress", "completed", "submission_unknown"}:
                emit({"reused": True, "action": existing["id"], "status": existing["status"]})
                return 0
        action = add_action(mutable, provider="fal.ai", kind=args.kind, scene=args.scene, model=model, payload=payload)
        action_id = action["id"]

    try:
        result = fal_submit(model, _expand_local_fal_media(payload))
    except ApiError as exc:
        status = "submission_unknown" if exc.kind == "network_failure" else "failed"
        with locked_state(args.project) as mutable:
            update_action(mutable, action_id, status=status, error={"kind": exc.kind, "message": str(exc), "http_status": exc.status, "detail": exc.detail})
        raise

    with locked_state(args.project) as mutable:
        update_action(
            mutable,
            action_id,
            status="submitted",
            request_id=result.get("request_id"),
            status_url=result.get("status_url"),
            response_url=result.get("response_url"),
            cancel_url=result.get("cancel_url"),
            submitted_at=now_iso(),
        )
        mutable.setdefault("evidence", {})["fal.ai"] = {"authenticated": True, "generation_tested": False, "last_action": action_id}
    emit({"submitted": True, "action": action_id, "request_id": result.get("request_id"), "model": model})
    return 0


def cmd_fal_poll(args: argparse.Namespace) -> int:
    state = read_state(args.project)
    try:
        action = state["actions"][args.action]
    except KeyError as exc:
        raise StateError(f"Ação desconhecida: {args.action}") from exc
    if action.get("provider") != "fal.ai" or not action.get("status_url"):
        raise StateError("Ação não possui consulta fal.ai disponível")
    status_data = fal_get(action["status_url"])
    provider_status = str(status_data.get("status", "UNKNOWN")).upper()
    if provider_status not in {"COMPLETED", "FAILED"}:
        with locked_state(args.project) as mutable:
            update_action(mutable, args.action, status="in_progress", provider_status=provider_status)
        emit({"action": args.action, "status": provider_status})
        return 0
    if provider_status == "FAILED":
        with locked_state(args.project) as mutable:
            update_action(mutable, args.action, status="failed", provider_status=provider_status, error=status_data)
        emit({"action": args.action, "status": "failed", "error": status_data})
        return 1

    result = fal_get(action["response_url"])
    urls = media_urls(result)
    output_group = {"seedream": "references", "seedance": "clips", "mirelo": "sfx"}.get(action["kind"], "clips")
    outputs = []
    for index, url in enumerate(urls, 1):
        base = safe_output_path(args.project, f"{output_group}/{safe_name(action.get('scene') or 'global')}-{args.action}-{index}")
        outputs.append(str(download(url, base)))
    with locked_state(args.project) as mutable:
        update_action(mutable, args.action, status="completed", provider_status=provider_status, outputs=outputs, response=result, completed_at=now_iso())
        mutable.setdefault("artifacts", []).extend({"action": args.action, "path": path, "kind": action["kind"]} for path in outputs)
        mutable.setdefault("evidence", {})["fal.ai"] = {"authenticated": True, "generation_tested": True, "last_action": args.action}
    emit({"action": args.action, "status": "completed", "outputs": outputs})
    return 0


def cmd_tts(args: argparse.Namespace) -> int:
    state = read_state(args.project)
    require_gate(state, "script")
    text = Path(args.text_file).read_text(encoding="utf-8").strip()
    if not text:
        raise StateError("Texto de fala vazio")
    model = args.model or state.get("models", {}).get("elevenlabs", "eleven_v4")
    current_voice = state.get("voice_map", {}).get(args.character)
    if current_voice and current_voice != args.voice_id and not args.replace_voice:
        raise StateError(f"Personagem {args.character} já usa outro voice_id; use --replace-voice após aprovação")
    if not args.yes_paid:
        paid_preview("ElevenLabs", "tts", args.scene, model, {"available": False, "basis": "plano/créditos da conta"})
        return 3
    payload = {"scene": args.scene, "character": args.character, "voice_id": args.voice_id, "model": model, "text": text, "output_format": args.output_format}
    payload_hash = canonical_hash(payload)
    with locked_state(args.project) as mutable:
        for existing in mutable.get("actions", {}).values():
            if existing.get("provider") == "ElevenLabs" and existing.get("payload_hash") == payload_hash and existing.get("status") in {"prepared", "completed", "submission_unknown"}:
                emit({"reused": True, "action": existing["id"], "status": existing["status"]})
                return 0
        mutable.setdefault("voice_map", {})[args.character] = args.voice_id
        action = add_action(mutable, provider="ElevenLabs", kind="tts", scene=args.scene, model=model, payload=payload)
        action_id = action["id"]
    try:
        response = elevenlabs_tts(voice_id=args.voice_id, text=text, model=model, output_format=args.output_format)
    except ApiError as exc:
        status = "submission_unknown" if exc.kind == "network_failure" else "failed"
        with locked_state(args.project) as mutable:
            update_action(mutable, action_id, status=status, error={"kind": exc.kind, "message": str(exc), "http_status": exc.status, "detail": exc.detail})
        raise
    extension = ".mp3" if args.output_format.startswith("mp3") else ".wav"
    output = safe_output_path(args.project, f"voices/{safe_name(args.scene)}-{safe_name(args.character)}-{action_id}{extension}")
    if output.exists():
        raise StateError(f"Saída existente não foi sobrescrita: {output}")
    output.write_bytes(response.body)
    duration = media_duration(output)
    with locked_state(args.project) as mutable:
        update_action(mutable, action_id, status="completed", output=str(output), duration_seconds=duration, request_id=response.headers.get("request-id"), completed_at=now_iso())
        mutable.setdefault("artifacts", []).append({"action": action_id, "path": str(output), "kind": "voice", "duration_seconds": duration})
        mutable.setdefault("evidence", {})["ElevenLabs"] = {"authenticated": True, "generation_tested": True, "last_action": action_id}
    emit({"action": action_id, "status": "completed", "output": str(output), "duration_seconds": duration})
    return 0


def cmd_sync_upload(args: argparse.Namespace) -> int:
    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        raise StateError(f"Arquivo para asset Sync não encontrado: {path}")
    expected = "video/" if args.type == "VIDEO" else "audio/"
    if not args.content_type.startswith(expected):
        raise StateError(f"Content-Type incompatível com {args.type}: {args.content_type}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {"path": str(path), "sha256": digest, "bytes": path.stat().st_size, "asset_type": args.type, "content_type": args.content_type, "role": args.role}
    payload_hash = canonical_hash(payload)
    with locked_state(args.project) as mutable:
        for existing in mutable.get("actions", {}).values():
            if existing.get("provider") == "Sync Labs" and existing.get("kind") == "asset_upload" and existing.get("payload_hash") == payload_hash and existing.get("status") in {"completed", "submission_unknown"}:
                emit({"reused": True, "action": existing["id"], "status": existing["status"], "asset_id": existing.get("asset_id")})
                return 0
        action = add_action(mutable, provider="Sync Labs", kind="asset_upload", scene=args.scene, model="assets-v2", payload=payload)
        action_id = action["id"]
    try:
        result = sync_upload_asset(path, args.type, args.content_type)
    except ApiError as exc:
        status = "submission_unknown" if exc.kind in {"network_failure", "provider_unavailable"} else "failed"
        with locked_state(args.project) as mutable:
            update_action(mutable, action_id, status=status, error={"kind": exc.kind, "message": str(exc), "http_status": exc.status, "detail": exc.detail})
        raise
    with locked_state(args.project) as mutable:
        update_action(mutable, action_id, status="completed", asset_id=result["id"], asset_type=result["type"], bytes=result["size"], completed_at=now_iso())
    emit({"action": action_id, "status": "completed", "asset_id": result["id"], "asset_type": result["type"], "bytes": result["size"]})
    return 0


def cmd_sync_submit(args: argparse.Namespace) -> int:
    state = read_state(args.project)
    require_gate(state, "script")
    scene = find_scene(state, args.scene)
    if scene is not None and not scene.get("visible_speech", False):
        raise StateError("Cena não está marcada com fala visível; Sync não deve ser aplicado")
    model = args.model or state.get("models", {}).get("sync", "sync-3")
    if bool(args.video_url) == bool(args.video_asset):
        raise StateError("Forneça exatamente um de --video-url ou --video-asset")
    if bool(args.audio_url) == bool(args.audio_asset):
        raise StateError("Forneça exatamente um de --audio-url ou --audio-asset")
    video_input = {"type": "video", "url": args.video_url} if args.video_url else {"type": "video", "assetId": args.video_asset}
    audio_input = {"type": "audio", "url": args.audio_url} if args.audio_url else {"type": "audio", "assetId": args.audio_asset}
    payload = {
        "model": model,
        "input": [video_input, audio_input],
        "options": {"sync_mode": args.sync_mode},
        "outputFileName": safe_name(f"{args.project}-{args.scene}"),
    }
    if not args.yes_paid:
        paid_preview("Sync Labs", "lip_sync", args.scene, model, {"available": False, "basis": "plano/créditos da conta"})
        return 3
    payload_hash = canonical_hash(payload)
    with locked_state(args.project) as mutable:
        for existing in mutable.get("actions", {}).values():
            if existing.get("provider") == "Sync Labs" and existing.get("payload_hash") == payload_hash and existing.get("status") in {"prepared", "submitted", "in_progress", "completed", "submission_unknown"}:
                emit({"reused": True, "action": existing["id"], "status": existing["status"]})
                return 0
        action = add_action(mutable, provider="Sync Labs", kind="lip_sync", scene=args.scene, model=model, payload=payload)
        action["idempotency_key"] = str(uuid.uuid4())
        action_id = action["id"]
        idem = action["idempotency_key"]
    try:
        result = sync_submit(payload, idem)
    except ApiError as exc:
        status = "submission_unknown" if exc.kind in {"network_failure", "provider_unavailable"} else "failed"
        with locked_state(args.project) as mutable:
            update_action(mutable, action_id, status=status, error={"kind": exc.kind, "message": str(exc), "http_status": exc.status, "detail": exc.detail})
        raise
    with locked_state(args.project) as mutable:
        update_action(mutable, action_id, status="submitted", job_id=result["id"], provider_status=result.get("status"), submitted_at=now_iso())
        mutable.setdefault("evidence", {})["Sync Labs"] = {"authenticated": True, "generation_tested": False, "last_action": action_id}
    emit({"submitted": True, "action": action_id, "job_id": result["id"], "model": model})
    return 0


def cmd_sync_poll(args: argparse.Namespace) -> int:
    state = read_state(args.project)
    try:
        action = state["actions"][args.action]
    except KeyError as exc:
        raise StateError(f"Ação desconhecida: {args.action}") from exc
    if action.get("provider") != "Sync Labs" or not action.get("job_id"):
        raise StateError("Ação não possui job Sync consultável")
    result = sync_get(action["job_id"])
    provider_status = str(result.get("status", "UNKNOWN")).upper()
    if provider_status in {"FAILED", "REJECTED"}:
        with locked_state(args.project) as mutable:
            update_action(mutable, args.action, status="failed", provider_status=provider_status, error=result)
        emit({"action": args.action, "status": "failed", "error": result.get("error") or result.get("errorCode")})
        return 1
    if provider_status != "COMPLETED":
        with locked_state(args.project) as mutable:
            update_action(mutable, args.action, status="in_progress", provider_status=provider_status)
        emit({"action": args.action, "status": provider_status})
        return 0
    output_url = result.get("outputUrl")
    if not output_url:
        raise StateError("Sync marcou COMPLETED sem outputUrl")
    base = safe_output_path(args.project, f"lipsync/{safe_name(action.get('scene') or 'scene')}-{args.action}")
    output = download(output_url, base)
    with locked_state(args.project) as mutable:
        update_action(mutable, args.action, status="completed", provider_status=provider_status, output=str(output), response=result, completed_at=now_iso())
        mutable.setdefault("artifacts", []).append({"action": args.action, "path": str(output), "kind": "lip_sync"})
        mutable.setdefault("evidence", {})["Sync Labs"] = {"authenticated": True, "generation_tested": True, "last_action": args.action}
    emit({"action": args.action, "status": "completed", "output": str(output)})
    return 0


def cmd_media_duration(args: argparse.Namespace) -> int:
    path = Path(args.file).expanduser().resolve()
    emit({"file": str(path), "duration_seconds": media_duration(path)})
    return 0


def cmd_hyperframes(args: argparse.Namespace) -> int:
    state = read_state(args.project)
    directory = project_dir(args.project) / "hyperframes"
    if not (directory / "package.json").is_file():
        raise StateError(f"Projeto Hyperframes ainda não foi criado: {directory}")
    if args.operation in {"review", "preview"}:
        require_gate(state, "script")
    if args.operation == "final":
        require_gate(state, "review")
    commands: list[list[str]]
    output: Path | None = None
    if args.operation == "check":
        commands = [["npx", "hyperframes", "check"]]
    elif args.operation == "preview":
        commands = [["npx", "hyperframes", "check"], ["npx", "hyperframes", "preview", "--background"]]
    else:
        quality = "looks" if args.operation == "review" else "delivery"
        group = "review" if args.operation == "review" else "final"
        output = safe_output_path(args.project, f"{group}/{args.project}-{args.operation}-{now_iso().replace(':', '-')}.mp4")
        commands = [["npx", "hyperframes", "check"], ["npx", "hyperframes", "render", "--quality", quality, "--output", str(output)]]
    for command in commands:
        result = subprocess.run(command, cwd=directory, check=False)
        if result.returncode != 0:
            raise StateError(f"Hyperframes falhou com código {result.returncode}: {' '.join(command[2:])}")
    result_data: dict[str, object] = {"operation": args.operation, "project_dir": str(directory), "success": True}
    if output:
        if not output.is_file() or output.stat().st_size == 0:
            raise StateError("Render terminou sem arquivo válido")
        result_data["output"] = str(output)
        result_data["duration_seconds"] = media_duration(output)
        with locked_state(args.project) as mutable:
            mutable.setdefault("artifacts", []).append({"path": str(output), "kind": f"hyperframes_{args.operation}"})
    emit(result_data)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Executor seguro da skill criacao-de-video-ia")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prepare-env", help="Cria apenas campos ausentes no .env").set_defaults(func=cmd_prepare_env)
    diagnose = sub.add_parser("diagnose", help="Testa autenticação sem gerar mídia")
    diagnose.add_argument("--service", choices=("all", "openrouter", "elevenlabs", "fal", "sync"), default="all")
    diagnose.set_defaults(func=cmd_diagnose)
    sub.add_parser("check-deps", help="Verifica dependências locais").set_defaults(func=cmd_check_deps)

    init = sub.add_parser("init", help="Inicializa estado persistente")
    init.add_argument("--slug", required=True)
    init.add_argument("--title", required=True)
    idea_group = init.add_mutually_exclusive_group()
    idea_group.add_argument("--idea")
    idea_group.add_argument("--idea-file")
    init.set_defaults(func=cmd_init)

    plan = sub.add_parser("set-plan", help="Valida e salva o plano")
    plan.add_argument("--project", required=True)
    plan.add_argument("--file", required=True)
    plan.set_defaults(func=cmd_set_plan)

    approve = sub.add_parser("approve", help="Registra uma aprovação")
    approve.add_argument("--project", required=True)
    approve.add_argument("--gate", required=True, choices=("references", "script", "review"))
    approve.add_argument("--notes")
    approve.set_defaults(func=cmd_approve)

    show = sub.add_parser("show", help="Mostra estado sem payloads/prompts")
    show.add_argument("--project", required=True)
    show.set_defaults(func=cmd_show)

    invalidate = sub.add_parser("invalidate-scene", help="Invalida somente derivados de uma cena")
    invalidate.add_argument("--project", required=True)
    invalidate.add_argument("--scene", required=True)
    invalidate.add_argument("--reason", required=True)
    invalidate.set_defaults(func=cmd_invalidate_scene)

    price = sub.add_parser("price", help="Consulta preço oficial fal.ai")
    price.add_argument("--model", required=True)
    price.set_defaults(func=cmd_price)

    openrouter_image = sub.add_parser("openrouter-image", help="Prepara ou gera uma referência pela OpenRouter Image API")
    openrouter_image.add_argument("--project", required=True)
    openrouter_image.add_argument("--scene", required=True)
    openrouter_image.add_argument("--payload", required=True)
    openrouter_image.add_argument("--model")
    openrouter_image.add_argument("--yes-paid", action="store_true")
    openrouter_image.set_defaults(func=cmd_openrouter_image)

    openrouter_video = sub.add_parser("openrouter-video-submit", help="Prepara ou submete um vídeo pela OpenRouter")
    openrouter_video.add_argument("--project", required=True)
    openrouter_video.add_argument("--scene", required=True)
    openrouter_video.add_argument("--payload", required=True)
    openrouter_video.add_argument("--model")
    openrouter_video.add_argument("--yes-paid", action="store_true")
    openrouter_video.set_defaults(func=cmd_openrouter_video_submit)

    openrouter_video_poll = sub.add_parser("openrouter-video-poll", help="Consulta e baixa um vídeo OpenRouter")
    openrouter_video_poll.add_argument("--project", required=True)
    openrouter_video_poll.add_argument("--action", required=True)
    openrouter_video_poll.set_defaults(func=cmd_openrouter_video_poll)

    fal_submit_parser = sub.add_parser("fal-submit", help="Prepara ou submete uma geração fal.ai")
    fal_submit_parser.add_argument("--project", required=True)
    fal_submit_parser.add_argument("--scene", required=True)
    fal_submit_parser.add_argument("--kind", required=True, choices=("seedream", "seedance", "mirelo"))
    fal_submit_parser.add_argument("--payload", required=True)
    fal_submit_parser.add_argument("--model")
    fal_submit_parser.add_argument("--yes-paid", action="store_true")
    fal_submit_parser.set_defaults(func=cmd_fal_submit)

    fal_poll = sub.add_parser("fal-poll", help="Consulta e baixa um job fal.ai")
    fal_poll.add_argument("--project", required=True)
    fal_poll.add_argument("--action", required=True)
    fal_poll.set_defaults(func=cmd_fal_poll)

    tts = sub.add_parser("tts", help="Gera uma fala ElevenLabs")
    tts.add_argument("--project", required=True)
    tts.add_argument("--scene", required=True)
    tts.add_argument("--character", required=True)
    tts.add_argument("--voice-id", required=True)
    tts.add_argument("--text-file", required=True)
    tts.add_argument("--model")
    tts.add_argument("--output-format", default="mp3_44100_128")
    tts.add_argument("--replace-voice", action="store_true")
    tts.add_argument("--yes-paid", action="store_true")
    tts.set_defaults(func=cmd_tts)

    sync_upload = sub.add_parser("sync-upload", help="Envia arquivo local como asset reutilizável da Sync")
    sync_upload.add_argument("--project", required=True)
    sync_upload.add_argument("--scene", required=True)
    sync_upload.add_argument("--role", required=True, choices=("video", "audio"))
    sync_upload.add_argument("--file", required=True)
    sync_upload.add_argument("--type", required=True, choices=("VIDEO", "AUDIO"))
    sync_upload.add_argument("--content-type", required=True)
    sync_upload.set_defaults(func=cmd_sync_upload)

    sync_parser = sub.add_parser("sync-submit", help="Prepara ou submete lip sync")
    sync_parser.add_argument("--project", required=True)
    sync_parser.add_argument("--scene", required=True)
    sync_parser.add_argument("--video-url")
    sync_parser.add_argument("--audio-url")
    sync_parser.add_argument("--video-asset")
    sync_parser.add_argument("--audio-asset")
    sync_parser.add_argument("--sync-mode", default="silence", choices=("silence", "cut_off", "loop", "bounce", "remap"))
    sync_parser.add_argument("--model")
    sync_parser.add_argument("--yes-paid", action="store_true")
    sync_parser.set_defaults(func=cmd_sync_submit)

    sync_poll = sub.add_parser("sync-poll", help="Consulta e baixa um job Sync")
    sync_poll.add_argument("--project", required=True)
    sync_poll.add_argument("--action", required=True)
    sync_poll.set_defaults(func=cmd_sync_poll)

    duration = sub.add_parser("media-duration", help="Mede duração real com ffprobe")
    duration.add_argument("--file", required=True)
    duration.set_defaults(func=cmd_media_duration)

    hyperframes = sub.add_parser("hyperframes", help="Executa gates de check, preview e render")
    hyperframes.add_argument("--project", required=True)
    hyperframes.add_argument("--operation", required=True, choices=("check", "preview", "review", "final"))
    hyperframes.set_defaults(func=cmd_hyperframes)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (ConfigurationError, StateError, ApiError, OSError, subprocess.SubprocessError) as exc:
        error: dict[str, object] = {"ok": False, "error": str(exc)}
        if isinstance(exc, ApiError):
            error.update({"kind": exc.kind, "service": exc.service, "http_status": exc.status, "detail": exc.detail})
        emit(error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
