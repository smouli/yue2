"""Runners start one-off jobs (`python -m yue2 <args>`) in a container and report when they end.

The dispatcher only uses this interface, so Modal, CoreWeave and local processes are interchangeable: pick one
with YUE2_RUNNER. A new backend needs three methods.
"""

from typing import Protocol

from yue2.config import Settings

GONE = -1  # poll() result for a job the backend no longer knows about


class Runner(Protocol):
    name: str
    remote: bool  # jobs run on another machine: they need S3 storage and a web app URL they can reach

    def launch(self, args: list[str], env: dict[str, str]) -> str:
        """Start `python -m yue2 *args` with exactly these environment variables; return the job's id."""

    def poll(self, ref: str) -> int | None:
        """None while the job runs; its exit code once it has ended (GONE if it can't be found)."""

    def stop(self, ref: str) -> None: ...


def wants_gpu(env: dict[str, str]) -> bool:
    """Jobs with fake models are cheap CPU smoke tests; only real models get a GPU."""
    return env.get("YUE2_MODELS") == "local"


def load(settings: Settings) -> Runner:
    if settings.runner == "process":
        from yue2.runners.process import ProcessRunner
        return ProcessRunner(settings)
    if settings.runner == "modal":
        from yue2.runners.modal_sandbox import ModalRunner
        return ModalRunner(settings)
    if settings.runner == "coreweave":
        from yue2.runners.coreweave_sandbox import CoreWeaveRunner
        return CoreWeaveRunner(settings)
    raise SystemExit(f"Unknown YUE2_RUNNER {settings.runner!r}: use process, modal or coreweave.")
