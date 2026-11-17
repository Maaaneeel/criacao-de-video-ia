#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import video_ai
from video_ai_lib import config, state


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="video-ai-self-test-") as temp:
        root = Path(temp)
        original_settings = config.settings
        config.settings = lambda: {
            "project_root": str(root),
            "env_file": ".env",
            "state_dir": ".video-ai/projects",
            "models": {
                "seedream": "test/seedream",
                "seedance": "test/seedance",
                "mirelo": "test/mirelo",
                "elevenlabs": "test-eleven",
                "sync": "test-sync",
            },
        }
        try:
            sentinel = "kept-secret-value"
            (root / ".env").write_text(f"OPENROUTER_API_KEY={sentinel}\n", encoding="utf-8")
            prepared = config.prepare_env()
            loaded = config.load_env()
            assert loaded["OPENROUTER_API_KEY"] == sentinel
            assert set(prepared["added"]) == {"ELEVENLABS_API_KEY", "FAL_KEY", "SYNC_API_KEY"}
            assert (root / ".env").stat().st_mode & 0o777 == 0o600
            assert ".env" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()

            path, created = state.initialize("test-project", "Teste", "Ideia")
            assert path.is_file() and created["models"]["seedream"] == "test/seedream"
            with state.locked_state("test-project") as mutable:
                action = state.add_action(
                    mutable,
                    provider="fal.ai",
                    kind="seedream",
                    scene="scene-001",
                    model="test/seedream",
                    payload={"prompt": "internal"},
                )
                state.update_action(mutable, action["id"], status="completed", request_id="request-test")
            restored = state.read_state("test-project")
            assert restored["actions"][action["id"]]["request_id"] == "request-test"
            assert state.safe_output_path("test-project", "clips/result").is_relative_to(state.project_dir("test-project"))

            plan = {
                "visual_bible": {},
                "scenes": [
                    {
                        "id": "scene-001",
                        "duration_seconds": 5,
                        "action": "original",
                        "dialogue": [{"character_id": "hero", "text": "hello"}],
                        "references": ["hero.png"],
                        "sound": "room tone",
                    },
                    {"id": "scene-002", "duration_seconds": 4, "action": "untouched"},
                ],
            }
            plan_file = root / "plan.json"
            plan_file.write_text(json.dumps(plan), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                video_ai.cmd_set_plan(SimpleNamespace(project="test-project", file=str(plan_file)))
            with state.locked_state("test-project") as mutable:
                mutable["approvals"] = {
                    "references": {"approved": True},
                    "script": {"approved": True},
                    "review": {"approved": True},
                }
                generated = state.add_action(
                    mutable,
                    provider="OpenRouter",
                    kind="reference_image",
                    scene="scene-001",
                    model="test-image",
                    payload={"prompt": "original"},
                )
                state.update_action(mutable, generated["id"], status="completed")
                voice = state.add_action(
                    mutable,
                    provider="ElevenLabs",
                    kind="tts",
                    scene="scene-001",
                    model="test-voice",
                    payload={"text": "hello"},
                )
                state.update_action(mutable, voice["id"], status="completed")
                uncertain = state.add_action(
                    mutable,
                    provider="OpenRouter",
                    kind="reference_image",
                    scene="scene-001",
                    model="test-image",
                    payload={"prompt": "uncertain"},
                )
                state.update_action(mutable, uncertain["id"], status="prepared")
            replacement_file = root / "scene.json"
            replacement_file.write_text(
                json.dumps({"id": "scene-001", "duration_seconds": 6, "action": "revised"}),
                encoding="utf-8",
            )
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    video_ai.cmd_update_scene(
                        SimpleNamespace(
                            project="test-project",
                            file=str(replacement_file),
                            reason="user revision",
                            change_type="visual",
                        )
                    )
            except state.StateError as exc:
                assert "reconcilie" in str(exc)
            else:
                raise AssertionError("update-scene aceitou ação prepared")
            with state.locked_state("test-project") as mutable:
                state.update_action(mutable, uncertain["id"], status="failed")
            update_output = io.StringIO()
            with contextlib.redirect_stdout(update_output):
                video_ai.cmd_update_scene(
                    SimpleNamespace(
                        project="test-project",
                        file=str(replacement_file),
                        reason="user revision",
                        change_type="visual",
                    )
                )
            update_result = json.loads(update_output.getvalue())
            revised = state.read_state("test-project")
            assert revised["plan"]["scenes"][0]["action"] == "revised"
            assert revised["plan"]["scenes"][0]["dialogue"][0]["text"] == "hello"
            assert revised["plan"]["scenes"][0]["references"] == ["hero.png"]
            assert revised["plan"]["scenes"][1]["action"] == "untouched"
            assert revised["actions"][generated["id"]]["status"] == "stale"
            assert revised["actions"][voice["id"]]["status"] == "completed"
            assert revised["approvals"]["references"]["approved"] is True
            assert revised["approvals"]["script"]["approved"] is True
            assert revised["approvals"]["review"]["approved"] is False
            assert update_result["preserved_gates"] == {"references": True, "script": True}

            preview_output = io.StringIO()
            with contextlib.redirect_stdout(preview_output):
                video_ai.paid_preview("OpenRouter", "reference_image", "scene-001", "test-image", {})
            preview = json.loads(preview_output.getvalue())
            assert "authorization_required" not in preview
            assert preview["submission_blocked_without_yes_paid"] is True
            assert "sem pedir nova confirmação" in preview["next_step"]
        finally:
            config.settings = original_settings
    print(json.dumps({"ok": True, "tests": ["env_preservation", "permissions", "gitignore", "atomic_state", "action_resume", "safe_paths", "localized_scene_update", "partial_scene_merge", "dependency_invalidation", "approval_copy", "uncertain_action_guard", "non_redundant_paid_preview"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
