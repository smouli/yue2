"""Jobs as Modal Sandboxes. Auth: `modal token new` (or MODAL_TOKEN_ID / MODAL_TOKEN_SECRET).

Weights live in a Modal Volume mounted at /models; fill it once with `python -m yue2 remote fetch-models`.
The image is YUE2_WORKER_IMAGE from a registry, or Modal builds it from this checkout's Dockerfiles.
"""

from pathlib import Path

from yue2.config import Settings
from yue2.runners.base import GONE, wants_gpu

REPO_ROOT = Path(__file__).resolve().parents[2]


class ModalRunner:
    name = "modal"
    remote = True

    def __init__(self, settings: Settings):
        import modal

        self.modal = modal
        self.settings = settings
        self.app = modal.App.lookup(settings.modal_app, create_if_missing=True)
        self.volume = modal.Volume.from_name(settings.modal_volume, create_if_missing=True)
        self._images: dict[bool, tuple] = {}

    def _image(self, gpu: bool):
        """(image, python): the GPU worker image for real models, the light web image for fake-model smoke tests."""
        if gpu not in self._images:
            modal, s = self.modal, self.settings
            if gpu and s.worker_image:
                self._images[gpu] = (modal.Image.from_registry(s.worker_image, add_python="3.12"), s.worker_python)
            else:
                dockerfile = REPO_ROOT / ("docker/worker-gpu.Dockerfile" if gpu else "Dockerfile")
                if not dockerfile.exists():
                    raise SystemExit("Set YUE2_WORKER_IMAGE, or run the dispatcher from a checkout so Modal can build "
                                     f"{dockerfile.name}.")
                # The GPU image has no system Python for Modal's runtime; the app runs from its own venv.
                image = modal.Image.from_dockerfile(dockerfile, context_dir=REPO_ROOT,
                                                    add_python="3.12" if gpu else None)
                self._images[gpu] = (image, s.worker_python if gpu else "python")
        return self._images[gpu]

    def launch(self, args: list[str], env: dict[str, str]) -> str:
        gpu = wants_gpu(env)
        image, python = self._image(gpu)
        sandbox = self.modal.Sandbox.create(
            python, "-m", "yue2", *args, app=self.app, image=image, secrets=[self.modal.Secret.from_dict(env)],
            gpu=self.settings.modal_gpu if gpu else None, timeout=self.settings.job_timeout,
            volumes={"/models": self.volume})
        return sandbox.object_id

    def poll(self, ref: str) -> int | None:
        try:
            return self.modal.Sandbox.from_id(ref).poll()
        except self.modal.exception.NotFoundError:
            return GONE

    def stop(self, ref: str) -> None:
        self.modal.Sandbox.from_id(ref).terminate()
