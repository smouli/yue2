#!/usr/bin/env bash
# Whisper ASR venv for the intelligibility scorer.
set -x
cd /home/marimo/hack
export HF_HOME=/home/marimo/hack/hf-cache UV_CACHE_DIR=/home/marimo/hack/uv-cache
uv venv -p 3.12 .venv-asr \
  && uv pip install -p .venv-asr/bin/python torch==2.10.0 transformers==4.57.6 accelerate soundfile librosa jiwer \
  && .venv-asr/bin/python -c "from huggingface_hub import snapshot_download; print(snapshot_download('openai/whisper-large-v3'))" \
  && .venv-asr/bin/python -c "import torch;print('ASR OK',torch.__version__,torch.cuda.is_available())"
echo ASR_DONE
