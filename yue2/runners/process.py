"""Jobs as local subprocesses: the dispatcher's whole flow on a laptop, without a cloud account."""

import os
import subprocess
import sys
import uuid

from yue2.config import Settings
from yue2.runners.base import GONE


class ProcessRunner:
    name = "process"
    remote = False

    def __init__(self, settings: Settings):
        self.log_dir = settings.home / "jobs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, subprocess.Popen] = {}

    def launch(self, args: list[str], env: dict[str, str]) -> str:
        ref = uuid.uuid4().hex[:12]
        with open(self.log_dir / f"{ref}.log", "w") as log:
            # Unlike a sandbox, a local process inherits this machine's environment (paths, local storage).
            self.jobs[ref] = subprocess.Popen([sys.executable, "-m", "yue2", *args], env={**os.environ, **env},
                                              stdout=log, stderr=subprocess.STDOUT)
        return ref

    def poll(self, ref: str) -> int | None:
        job = self.jobs.get(ref)
        return GONE if job is None else job.poll()  # a job from an earlier dispatcher can't be watched

    def stop(self, ref: str) -> None:
        if ref in self.jobs:
            self.jobs[ref].terminate()
