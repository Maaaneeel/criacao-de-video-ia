#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
from pathlib import Path

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
                state.update_action(mutable, action["id"], status="submitted", request_id="request-test")
            restored = state.read_state("test-project")
            assert restored["actions"][action["id"]]["request_id"] == "request-test"
            assert state.safe_output_path("test-project", "clips/result").is_relative_to(state.project_dir("test-project"))
        finally:
            config.settings = original_settings
    print(json.dumps({"ok": True, "tests": ["env_preservation", "permissions", "gitignore", "atomic_state", "action_resume", "safe_paths"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
