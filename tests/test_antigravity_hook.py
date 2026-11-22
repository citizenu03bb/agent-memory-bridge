import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "scripts" / "antigravity_memory_hook.py"


def run_hook(tmp_path, payload, bin_path, **extra_env):
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "AMB_BIN": str(bin_path),
        "AMB_HOOK_STATE_DIR": str(tmp_path / "state"),
        **extra_env,
    }
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def fake_bin(tmp_path, output="=== NEUTRAL ===\n- note-a", code=0):
    path = tmp_path / "fake-amb"
    path.write_text(f"#!/bin/sh\nprintf '%s' '{output}'\nexit {code}\n")
    path.chmod(0o755)
    return path


def test_injects_on_first_invocation_of_each_turn(tmp_path):
    binary = fake_bin(tmp_path)
    first = run_hook(tmp_path, {"conversationId": "c1", "invocationNum": 0}, binary)
    message = first["injectSteps"][0]["ephemeralMessage"]
    assert message.startswith("[agent-memory-bridge]")
    assert "note-a" in message
    assert run_hook(tmp_path, {"conversationId": "c1", "invocationNum": 1}, binary) == {}
    # next user turn restarts at 0 and must be served again
    assert "injectSteps" in run_hook(tmp_path, {"conversationId": "c1", "invocationNum": 0}, binary)


def test_without_invocation_num_falls_back_to_once_per_conversation(tmp_path):
    binary = fake_bin(tmp_path)
    assert "injectSteps" in run_hook(tmp_path, {"conversationId": "c1"}, binary)
    assert run_hook(tmp_path, {"conversationId": "c1"}, binary) == {}
    assert "injectSteps" in run_hook(tmp_path, {"conversationId": "c2"}, binary)


def test_truncates_long_index(tmp_path):
    binary = fake_bin(tmp_path, output="x" * 500)
    out = run_hook(tmp_path, {"conversationId": "c1"}, binary, AMB_HOOK_MAX_CHARS="100")
    message = out["injectSteps"][0]["ephemeralMessage"]
    assert "truncated" in message
    assert "x" * 100 in message and "x" * 101 not in message


def test_failures_yield_empty_object(tmp_path):
    binary = fake_bin(tmp_path, code=1)
    assert run_hook(tmp_path, {"conversationId": "c1"}, binary) == {}
    assert run_hook(tmp_path, "not json", binary) == {}
    assert run_hook(tmp_path, {"invocationNum": 1}, binary) == {}
    assert run_hook(tmp_path, {"conversationId": "c9"}, tmp_path / "missing") == {}


def test_conversation_id_cannot_escape_state_dir(tmp_path):
    binary = fake_bin(tmp_path)
    run_hook(tmp_path, {"conversationId": "../../evil"}, binary)
    assert not (tmp_path / "evil").exists()
    assert list((tmp_path / "state" / "seen").iterdir())
