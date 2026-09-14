# Deploy on DigitalOcean

One GPU Droplet runs everything: Postgres, the web app and a GPU worker (YuE2, Whisper, SheetSage2), with Docker
Compose. The lyric writer is an OpenAI-compatible API (DigitalOcean Serverless Inference or W&B Inference), so
the Droplet only needs one GPU.

```
browser ──► web (FastAPI + UI) ──► Postgres (songs + job queue) ◄── worker (GPU) ──► writer API
                    │                                                 │
                    └──────────── storage: Docker volume or Spaces ◄──┘
```

## What you need

| | Where | Goes in `.env` |
|---|---|---|
| GPU Droplet, 48 GB GPU | `gpu-6000adax1-48gb` (RTX 6000 Ada, TOR1) or `gpu-l40sx1-48gb` | |
| Lyric writer key | Control panel → Serverless Inference → Model Access Keys | `LLM_BASE_URL`, `LLM_API_KEY`, `WRITER_MODEL` |
| Spaces bucket (optional) | Control panel → Spaces Object Storage; an access key for the bucket | `YUE2_STORAGE=s3`, `S3_*` |
| The source recording | a copy of the song you own, e.g. `song.mp3` (never committed) | |

YuE2 and SheetSage2 weights are CC BY-NC 4.0: noncommercial use only.

## 1. Fill in `.env`

Start from [`.env.example`](../../.env.example). The GPU-specific settings:

```bash
YUE2_MODELS=local
LLM_BASE_URL=https://inference.do-ai.run/v1
LLM_API_KEY=<model access key>
WRITER_MODEL=<a model id from the list below>
```

List the models your key can use:

```bash
curl -s -H "Authorization: Bearer $LLM_API_KEY" https://inference.do-ai.run/v1/models
```

The loop was tuned with Gemma 4 31B on W&B Inference. Other writers work, but their lyric quality hasn't been
compared yet, so check the first songs. To keep W&B Inference, use its URL and key instead.

**Storage:** leave `YUE2_STORAGE=local` to keep songs in a Docker volume on the Droplet. Songs survive a snapshot
but not a destroyed Droplet without one. With Spaces, songs outlive the Droplet and the web app hands out
presigned links:

```bash
YUE2_STORAGE=s3
S3_ENDPOINT=https://tor1.digitaloceanspaces.com
S3_REGION=tor1
S3_BUCKET=<bucket>
S3_ACCESS_KEY=<key>
S3_SECRET_KEY=<secret>
```

## 2. Create the Droplet

```bash
doctl compute size list | grep gpu
```

```bash
doctl compute droplet create yue2-gpu --region tor1 --size gpu-6000adax1-48gb --image gpu-h100x1-base --ssh-keys <key-fingerprint> --wait
```

`gpu-h100x1-base` is DigitalOcean's NVIDIA AI/ML image (Ubuntu with the driver and container toolkit) and works
on every NVIDIA GPU size. Check the size list for the regions that have your GPU. GPU Droplets are billed per
second while they exist.

## 3. Set it up

From the repo root on your machine, with `IP` set to the Droplet's address:

```bash
ssh root@$IP 'bash -s' < deploy/digitalocean/bootstrap.sh
```

The first run installs anything missing and clones the repo, then stops to ask for `.env`. Copy it along with
the recording and run the script again:

```bash
scp .env root@$IP:/opt/yue2/.env
```

```bash
scp song.mp3 root@$IP:/opt/yue2/song.mp3
```

```bash
ssh root@$IP 'SONG=/opt/yue2/song.mp3 bash /opt/yue2/deploy/digitalocean/bootstrap.sh'
```

This builds the images, downloads the model weights into a volume, transcribes the song into a melody profile
(saved to storage, so `SONG` is only needed once) and starts the worker. Rerun the script without `SONG` to
deploy new code.

## 4. Open it

The web app listens on the Droplet's localhost only. It has no sign-in, and every song uses the GPU.

```bash
ssh -N -L 8080:localhost:8080 root@$IP
```

Then open http://localhost:8080. To share it with an audience, set `WEB_PORT=8080` when running the script and
add a Cloud Firewall rule that allows port 8080 only from the addresses you trust.

Logs:

```bash
ssh root@$IP 'cd /opt/yue2 && docker compose -f compose.yml -f compose.gpu.yml logs -f worker'
```

## 5. Stop paying

A powered-off Droplet is still billed. Snapshot it (weights, melody and songs included), then destroy it:

```bash
doctl compute droplet-action snapshot <droplet-id> --snapshot-name yue2-gpu --wait
```

```bash
doctl compute droplet delete yue2-gpu
```

Later, create the Droplet from the snapshot with `--image <snapshot-id>` and rerun the bootstrap.

## Other ways to run the same containers

Nothing here is specific to a Droplet. The pieces only share `DATABASE_URL` and storage:

- **Web app without a GPU:** the root `Dockerfile` (`python -m yue2 api`) on App Platform or any container host.
- **Database:** a managed Postgres; set `DATABASE_URL`.
- **Workers:** `docker/worker-gpu.Dockerfile` (`python -m yue2 worker`) on any NVIDIA container platform or GPU
  VM, with `YUE2_STORAGE=s3`. Mount a persistent volume at `/models`, or the weights download again on every
  start. Add workers to sing more songs at once; each claims its own song from the queue.
- **Melody profile:** run `python -m yue2 add-melody --audio song.mp3` once from any worker; the profile is saved
  to storage and every worker fetches it.
