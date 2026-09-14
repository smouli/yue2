# GPU worker: YuE2, Whisper and SheetSage2, each in its own environment (their PyTorch pins conflict), plus the app.
# Model weights are not baked in; they download into the /models volume (python -m yue2 fetch-models).
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 UV_PYTHON_INSTALL_DIR=/opt/python UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

# YuE2 runtime, pinned to the revision the loop was developed against.
ARG YUE_REF=88da114
RUN git clone https://github.com/multimodal-art-projection/YuE.git /opt/YuE && git -C /opt/YuE checkout "${YUE_REF}"
RUN uv venv -p 3.12 /opt/venvs/yue2 && uv pip install -p /opt/venvs/yue2/bin/python /opt/YuE

# Whisper for the "heard clearly" score.
RUN uv venv -p 3.12 /opt/venvs/asr \
 && uv pip install -p /opt/venvs/asr/bin/python torch==2.10.0 transformers==4.57.6 accelerate soundfile librosa

# SheetSage2 for melody transcription and the melody check. Its docs pin cu126 torch; Blackwell and Ada GPUs work on cu128.
RUN uv venv -p 3.11 /opt/venvs/sheetsage2 \
 && uv pip install -p /opt/venvs/sheetsage2/bin/python huggingface-hub==0.36.0 \
 && /opt/venvs/sheetsage2/bin/huggingface-cli download m-a-p/SheetSage2 --local-dir /opt/SheetSage2 \
 && uv pip install -p /opt/venvs/sheetsage2/bin/python torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128 \
 && uv pip install -p /opt/venvs/sheetsage2/bin/python -r /opt/SheetSage2/requirements.txt

# The app.
RUN uv venv -p 3.12 /opt/venvs/app
WORKDIR /app
COPY pyproject.toml ./
COPY yue2 ./yue2
RUN uv pip install -p /opt/venvs/app/bin/python ".[tracing]"

ENV PATH=/opt/venvs/app/bin:$PATH \
    YUE2_MODELS=local YUE2_HOME=/data HF_HOME=/models/hf \
    YUE2_SKILL_DIR=/opt/YuE/skills/yue2-music SHEETSAGE_MODEL=/opt/SheetSage2 \
    YUE2_PYTHON=/opt/venvs/yue2/bin/python ASR_PYTHON=/opt/venvs/asr/bin/python SHEETSAGE_PYTHON=/opt/venvs/sheetsage2/bin/python
CMD ["python", "-m", "yue2", "worker"]
