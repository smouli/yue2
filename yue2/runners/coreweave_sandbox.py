"""Jobs as CoreWeave Sandboxes. Auth: CWSANDBOX_API_KEY, or CWSANDBOX_AUTH=wandb to use W&B credentials.

The image must be in a registry (YUE2_WORKER_IMAGE). Weights go on a registered volume (CWSANDBOX_VOLUME_ID,
mounted at /models); without one, every job downloads them first.
"""

from yue2.config import Settings
from yue2.runners.base import GONE, wants_gpu


class CoreWeaveRunner:
    name = "coreweave"
    remote = True

    def __init__(self, settings: Settings):
        import cwsandbox

        if not settings.worker_image:
            raise SystemExit("CoreWeave sandboxes need YUE2_WORKER_IMAGE: the worker image pushed to a registry.")
        self.cw = cwsandbox
        self.settings = settings
        self.auth = cwsandbox.AuthStrategy.WANDB if settings.cwsandbox_auth == "wandb" else None
        self.terminal = {cwsandbox.SandboxStatus.COMPLETED, cwsandbox.SandboxStatus.FAILED,
                         cwsandbox.SandboxStatus.TERMINATED}

    def launch(self, args: list[str], env: dict[str, str]) -> str:
        s, cw = self.settings, self.cw
        resources, volumes = None, None
        if wants_gpu(env):
            gpu = {"count": 1, "memory_gb": s.cwsandbox_gpu_memory_gb}
            if s.cwsandbox_gpu_type:
                gpu["type"] = s.cwsandbox_gpu_type
            resources = {"gpu": gpu}
            if s.cwsandbox_volume_id:
                volumes = [cw.RegisteredVolumeOptions(name="models", volume_id=s.cwsandbox_volume_id,
                                                      mount_path="/models")]
            else:
                env = {**env, "YUE2_FETCH_MODELS": "1"}
        sandbox = cw.Sandbox.run(
            s.worker_python, "-m", "yue2", *args, container_image=s.worker_image, resources=resources,
            volumes=volumes, environment_variables=env, max_lifetime_seconds=s.job_timeout, tags=["yue2"],
            auth=self.auth)
        return sandbox.sandbox_id

    def _sandbox(self, ref: str):
        return self.cw.Sandbox.from_id(ref, auth=self.auth).result()

    def poll(self, ref: str) -> int | None:
        try:
            sandbox = self._sandbox(ref)
        except self.cw.SandboxNotFoundError:
            return GONE
        status = sandbox.get_status()
        if status not in self.terminal:
            return None
        if sandbox.returncode is not None:
            return sandbox.returncode
        return 0 if status == self.cw.SandboxStatus.COMPLETED else 1

    def stop(self, ref: str) -> None:
        self._sandbox(ref).stop(missing_ok=True).result()
