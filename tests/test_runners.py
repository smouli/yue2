"""Runner abstraction: the dispatcher against local processes end to end, and the Modal and CoreWeave runners
against stand-ins for their SDKs (checking what we ask each cloud for)."""

import os
import socket
import sys
import threading
import time
import types
from dataclasses import replace

import pytest

from tests.conftest import PARAGRAPH
from yue2 import report
from yue2.runners import base


def test_token_is_per_song_and_attempt():
    token = report.song_token("s3cret", "song-1", 1)
    assert report.check_token("s3cret", "song-1", 1, token)
    assert not report.check_token("s3cret", "song-1", 2, token)  # a job from an earlier attempt
    assert not report.check_token("s3cret", "song-2", 1, token)
    assert not report.check_token("", "song-1", 1, token)  # no secret configured: jobs can't report


def test_job_env_forwards_only_job_settings(settings, monkeypatch):
    from yue2 import dispatcher

    monkeypatch.setenv("LLM_API_KEY", "key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    settings = replace(settings, runner_secret="s3cret", api_url="https://yue2.example")
    env = dispatcher.job_env(settings, "song-1", 1)
    assert env["LLM_API_KEY"] == "key" and env["YUE2_API_URL"] == "https://yue2.example"
    assert "DATABASE_URL" not in env
    assert report.check_token("s3cret", "song-1", 1, env["YUE2_SONG_TOKEN"])


class FakeModal(types.SimpleNamespace):
    """Records Modal calls; sandboxes finish on the second poll."""

    def __init__(self):
        calls = self.calls = []
        polls = {}

        class Sandbox:
            def __init__(self, ref):
                self.object_id = ref

            @staticmethod
            def create(*args, **kwargs):
                calls.append(("create", args, kwargs))
                return Sandbox(f"sb-{len(calls)}")

            @staticmethod
            def from_id(ref):
                return Sandbox(ref)

            def poll(self):
                polls[self.object_id] = polls.get(self.object_id, 0) + 1
                return 0 if polls[self.object_id] > 1 else None

            def terminate(self):
                calls.append(("terminate", self.object_id))

        super().__init__(
            calls=calls, Sandbox=Sandbox,
            App=types.SimpleNamespace(lookup=lambda name, create_if_missing: f"app:{name}"),
            Volume=types.SimpleNamespace(from_name=lambda name, create_if_missing: f"volume:{name}"),
            Secret=types.SimpleNamespace(from_dict=lambda env: ("secret", env)),
            Image=types.SimpleNamespace(from_registry=lambda tag, add_python: f"registry:{tag}",
                                        from_dockerfile=lambda path, context_dir, add_python: f"dockerfile:{path.name}"),
            exception=types.SimpleNamespace(NotFoundError=LookupError))


def test_modal_runner_asks_for_a_gpu_only_for_real_models(settings, monkeypatch):
    fake = FakeModal()
    monkeypatch.setitem(sys.modules, "modal", fake)
    from yue2.runners.modal_sandbox import ModalRunner

    runner = ModalRunner(replace(settings, modal_gpu="L40S", worker_image="ghcr.io/me/yue2-worker:1", job_timeout=900))
    ref = runner.launch(["run-song", "song-1"], {"YUE2_MODELS": "local", "LLM_API_KEY": "key"})
    _, args, kwargs = fake.calls[0]
    assert args == (settings.worker_python, "-m", "yue2", "run-song", "song-1")
    assert kwargs["gpu"] == "L40S" and kwargs["image"] == "registry:ghcr.io/me/yue2-worker:1"
    assert kwargs["volumes"] == {"/models": "volume:yue2-models"} and kwargs["timeout"] == 900
    assert kwargs["secrets"] == [("secret", {"YUE2_MODELS": "local", "LLM_API_KEY": "key"})]
    assert runner.poll(ref) is None and runner.poll(ref) == 0

    runner.launch(["run-song", "song-2"], {"YUE2_MODELS": "fake"})
    _, args, kwargs = fake.calls[1]
    assert kwargs["gpu"] is None and kwargs["image"] == "dockerfile:Dockerfile" and args[0] == "python"


def test_coreweave_runner_mounts_the_weights_volume(settings, monkeypatch):
    calls = []

    class Sandbox:
        sandbox_id = "cw-1"
        returncode = 0

        @staticmethod
        def run(*args, **kwargs):
            calls.append((args, kwargs))
            return Sandbox()

        @staticmethod
        def from_id(ref, auth=None):
            return types.SimpleNamespace(result=lambda: Sandbox())

        def get_status(self):
            return "completed"

    status = types.SimpleNamespace(COMPLETED="completed", FAILED="failed", TERMINATED="terminated")
    fake = types.SimpleNamespace(
        Sandbox=Sandbox, SandboxStatus=status, SandboxNotFoundError=LookupError,
        AuthStrategy=types.SimpleNamespace(WANDB="wandb"),
        RegisteredVolumeOptions=lambda **kw: ("volume", kw))
    monkeypatch.setitem(sys.modules, "cwsandbox", fake)
    from yue2.runners.coreweave_sandbox import CoreWeaveRunner

    s = replace(settings, worker_image="ghcr.io/me/yue2-worker:1", cwsandbox_volume_id="vol-9",
                cwsandbox_gpu_type="L40S", cwsandbox_auth="wandb")
    runner = CoreWeaveRunner(s)
    assert runner.launch(["run-song", "song-1"], {"YUE2_MODELS": "local"}) == "cw-1"
    args, kwargs = calls[0]
    assert args == (s.worker_python, "-m", "yue2", "run-song", "song-1")
    assert kwargs["resources"] == {"gpu": {"count": 1, "memory_gb": 40, "type": "L40S"}}
    assert kwargs["volumes"] == [("volume", {"name": "models", "volume_id": "vol-9", "mount_path": "/models"})]
    assert kwargs["auth"] == "wandb" and kwargs["container_image"] == "ghcr.io/me/yue2-worker:1"
    assert runner.poll("cw-1") == 0

    runner = CoreWeaveRunner(replace(s, cwsandbox_volume_id=""))
    runner.launch(["run-song", "song-2"], {"YUE2_MODELS": "local"})
    assert calls[1][1]["environment_variables"]["YUE2_FETCH_MODELS"] == "1"  # no volume: download weights first


def _serve(app) -> str:
    import uvicorn

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return f"http://127.0.0.1:{port}"
        time.sleep(0.05)
    raise RuntimeError("web app didn't start")


@pytest.mark.db
def test_dispatcher_runs_songs_as_process_jobs(settings, monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    from yue2 import db, dispatcher
    from yue2.api.app import create_app
    from yue2.runners.process import ProcessRunner

    try:
        conn = db.connect(os.environ["DATABASE_URL"])
    except (KeyError, psycopg.OperationalError):
        pytest.skip("no database")
    db.init_schema(conn)
    conn.execute("TRUNCATE songs CASCADE")
    settings = replace(settings, database_url=os.environ["DATABASE_URL"], runner_secret="s3cret")
    api_url = _serve(create_app(settings))

    # The dispatcher and its jobs read settings from the environment, like in production.
    for name, value in {"YUE2_HOME": str(settings.home), "YUE2_STORAGE": "local",
                        "YUE2_STORAGE_DIR": str(settings.storage_dir), "YUE2_MELODY_DIR": str(settings.melody_dir),
                        "YUE2_MODELS": "fake", "LLM_API_KEY": "", "WRITER_MODEL": "fake", "WEAVE_PROJECT": "",
                        "YUE2_TAKES": "2", "YUE2_RUNNER_SECRET": "s3cret", "YUE2_API_URL": api_url,
                        "YUE2_RUNNER": "process"}.items():
        monkeypatch.setenv(name, value)

    good = db.create_song(conn, PARAGRAPH, "", 2)
    doomed = db.create_song(conn, PARAGRAPH, "", 2)

    class Crashing(ProcessRunner):
        """Every job for `doomed` dies before reporting, like a sandbox killed mid-song."""

        def launch(self, args, env):
            if args[-1] == doomed:
                args = ["no-such-command"]
            return super().launch(args, env)

    dispatcher.main(poll_seconds=0.2, once=True, runner=Crashing(settings))

    finished = db.get(conn, good)
    assert finished["status"] == "done", finished["error"]
    assert finished["events"][0]["step"] == "setup" and finished["events"][-1]["step"] == "done"
    assert (settings.storage_dir / f"songs/{good}/song.mp3").exists() or \
        any((settings.storage_dir / f"songs/{good}").glob("song.*"))

    crashed = db.get(conn, doomed)
    assert crashed["status"] == "failed" and crashed["attempts"] == db.MAX_ATTEMPTS
    assert "ended (exit code 2)" in crashed["error"]
    conn.close()
