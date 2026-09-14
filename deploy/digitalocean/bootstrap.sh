#!/usr/bin/env bash
# Set up yue2 on a DigitalOcean GPU Droplet (NVIDIA base image) and start it. Safe to rerun; it pulls and rebuilds.
#
#   ssh root@DROPLET 'bash -s' < deploy/digitalocean/bootstrap.sh              # first run: clones, asks for .env
#   scp .env root@DROPLET:/opt/yue2/.env
#   scp song.mp3 root@DROPLET:/opt/yue2/song.mp3
#   ssh root@DROPLET 'SONG=/opt/yue2/song.mp3 bash /opt/yue2/deploy/digitalocean/bootstrap.sh'
#
# Settings (environment): REPO_URL, BRANCH (main), APP_DIR (/opt/yue2), SONG (a recording to transcribe into the
# melody profile; skip once the profile is saved), WEB_PORT (127.0.0.1:8080, reachable only through an SSH tunnel).
set -euo pipefail

REPO_URL=${REPO_URL:-https://github.com/smouli/yue2.git}
BRANCH=${BRANCH:-main}
APP_DIR=${APP_DIR:-/opt/yue2}
SONG=${SONG:-}
export WEB_PORT=${WEB_PORT:-127.0.0.1:8080}

step() { printf '\n==> %s\n' "$*"; }

step "GPU"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader \
  || { echo "No NVIDIA GPU found. Use a GPU Droplet with the NVIDIA base image."; exit 1; }

step "Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
if ! command -v nvidia-ctk >/dev/null; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update && apt-get install -y nvidia-container-toolkit
fi
if ! docker info --format '{{json .Runtimes}}' | grep -q nvidia; then
  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker
fi

step "Code ($BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --quiet origin
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" pull --quiet --ff-only origin "$BRANCH"
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

if [ ! -f .env ]; then
  echo "No $APP_DIR/.env yet. Fill in .env.example on your machine (YUE2_MODELS=local, LLM_API_KEY, storage),"
  echo "copy it with: scp .env root@<droplet-ip>:$APP_DIR/.env   then run this script again."
  exit 1
fi
grep -q '^YUE2_MODELS=local' .env || echo "warning: .env does not set YUE2_MODELS=local"
grep -q '^LLM_API_KEY=.\+' .env || { echo "LLM_API_KEY is empty in .env; the GPU worker needs a lyric writer."; exit 1; }

compose=(docker compose -f compose.yml -f compose.gpu.yml)

step "Build (the first GPU image build takes a while)"
"${compose[@]}" build

step "Database and web app"
"${compose[@]}" up -d db web

step "Model weights (cached in the models volume after the first run)"
"${compose[@]}" run --rm --no-deps worker python -m yue2 fetch-models

if [ -n "$SONG" ]; then
  step "Melody profile from $SONG"
  song_path=$(realpath "$SONG")
  "${compose[@]}" run --rm -v "$song_path:/input/$(basename "$song_path"):ro" worker \
    python -m yue2 add-melody --audio "/input/$(basename "$song_path")"
fi

step "Worker"
"${compose[@]}" up -d worker
sleep 5
"${compose[@]}" ps
"${compose[@]}" logs --tail 20 worker

cat <<EOF

yue2 is running. From your machine:
  ssh -N -L 8080:localhost:8080 root@<droplet-ip>     then open http://localhost:8080
If the worker says there is no melody profile, rerun with SONG=/path/to/song.mp3.
When you're done, snapshot and destroy the Droplet (a powered-off Droplet is still billed).
EOF
