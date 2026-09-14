# Run songs on Modal or CoreWeave sandboxes

Instead of an always-on GPU worker, a small **dispatcher** starts one GPU sandbox per song and stops paying when
the song is done. Modal and CoreWeave are interchangeable: pick one with `YUE2_RUNNER`.

```
browser ──► web app ──► Postgres (songs, queue) ◄── dispatcher ──starts──► sandbox per song (GPU)
               ▲                                                              │
               └──────────── progress, with a per-song token ◄────────────────┘
                                   song files ──► Spaces / S3 ◄── sandbox
```

- **The dispatcher** claims a queued song and starts `python -m yue2 run-song ID` on the runner. It passes only
  the settings a job needs (storage, writer, tracing) plus a token for that song. The database URL is never
  passed.
- **The sandbox** runs the same loop as the worker. It reports progress to the web app's `/api/runner/...`
  endpoints and saves audio to S3.
- **A sandbox that dies** (crash, timeout, lost machine) sends its song back to the queue, and the song fails
  after 2 attempts. A token only works for its own attempt, so a leftover sandbox can't overwrite a newer one.

## How the runners differ

| | Modal | CoreWeave |
|---|---|---|
| Auth | `modal token new`, or `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` | `CWSANDBOX_API_KEY`, or `CWSANDBOX_AUTH=wandb` with `WANDB_API_KEY` |
| Image | `YUE2_WORKER_IMAGE`, or Modal builds `docker/worker-gpu.Dockerfile` from a checkout | `YUE2_WORKER_IMAGE` in a registry (required) |
| GPU | `MODAL_GPU` (default `L40S`) | `CWSANDBOX_GPU_TYPE`, and `CWSANDBOX_GPU_MEMORY_GB` (default 40) |
| Weights | Modal Volume `MODAL_VOLUME`, mounted at `/models` | Registered volume `CWSANDBOX_VOLUME_ID` at `/models`; without one, each job downloads the weights first |
| Job settings | Passed as a Modal Secret | Passed as sandbox environment variables |

Adding another backend means writing `launch`, `poll` and `stop` in [yue2/runners](../../yue2/runners/base.py).

## Settings

In `.env`, shared by the web app and the dispatcher:

```bash
YUE2_RUNNER=modal                     # or coreweave
YUE2_RUNNER_SECRET=<openssl rand -hex 32>
YUE2_API_URL=https://<your web app>   # must be reachable from the sandboxes
YUE2_MODELS=local
YUE2_STORAGE=s3                       # plus S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY
LLM_BASE_URL=...                      # plus LLM_API_KEY, WRITER_MODEL
YUE2_WORKER_IMAGE=<registry>/yue2-worker-gpu:<tag>
YUE2_MAX_PARALLEL=2                   # songs at once
```

The web app has to be reachable from the internet (for example on DigitalOcean App Platform), because the
sandboxes report to it.

## 1. Build and push the GPU image

The image is linux/amd64 with CUDA. Build it on an amd64 machine, such as a CPU Droplet:

```bash
docker build -f docker/worker-gpu.Dockerfile -t <registry>/yue2-worker-gpu:<tag> .
```

```bash
docker push <registry>/yue2-worker-gpu:<tag>
```

On Modal you can skip this step: leave `YUE2_WORKER_IMAGE` empty and run the dispatcher from a checkout, and
Modal builds the Dockerfile itself.

## 2. Install the runner SDK

```bash
pip install -e ".[modal]"
```

or `".[coreweave]"`. The `dispatcher` Compose service installs both.

## 3. Download the weights once

This runs `fetch-models` in a sandbox and saves the weights to the volume:

```bash
python -m yue2 remote fetch-models
```

On CoreWeave, create the registered volume first and set `CWSANDBOX_VOLUME_ID`.

## 4. Add the melody

Upload the recording to your bucket (for example `uploads/song.mp3`), then transcribe it in a sandbox:

```bash
python -m yue2 remote add-melody --audio-key uploads/song.mp3
```

The profile is saved to storage, and every job fetches it from there.

## 5. Start the dispatcher

```bash
python -m yue2 dispatch
```

Or run it next to the web app and database with Compose:

```bash
docker compose --profile sandboxes up -d
```

## Try the whole flow on a laptop first

`YUE2_RUNNER=process` runs each song as a local subprocess that talks to the web app over HTTP, the same way a
sandbox does. It needs no cloud account:

```bash
YUE2_RUNNER=process YUE2_RUNNER_SECRET=dev python -m yue2 dispatch
```

With `YUE2_MODELS=fake`, Modal and CoreWeave jobs run on CPU without a GPU. That's a cheap way to check auth,
images, networking and storage before paying for GPUs.

## Not verified yet

- **Mocks only:** the Modal and CoreWeave runners are tested against stand-ins for their SDKs, with arguments
  checked against the real SDK signatures. They haven't started a real sandbox yet.
- **Unmeasured costs:** cold start time (image pull plus loading about 20 GB of weights from a volume) and the
  cost per song.
- **Unchecked on CoreWeave:** GPU type names, how registered volumes are created, and whether sandboxes can
  reach the internet by default. See the [CoreWeave Sandbox docs](https://docs.coreweave.com/products/coreweave-sandbox/client).
