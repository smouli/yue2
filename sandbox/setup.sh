#!/usr/bin/env bash
# One-time setup on a molab GPU sandbox: YuE2 + SheetSage2 in separate venvs, model weights cached.
# Run detached: nohup bash setup.sh > logs/setup.log 2>&1 &
set -x
mkdir -p /home/marimo/hack/logs
cd /home/marimo/hack
test -d YuE || git clone --depth 1 https://github.com/multimodal-art-projection/YuE.git
export HF_HOME=/home/marimo/hack/hf-cache UV_CACHE_DIR=/home/marimo/hack/uv-cache
( uv venv -p 3.12 .venv-yue2 && uv pip install -p .venv-yue2/bin/python ./YuE \
  && .venv-yue2/bin/python -c "import torch,yue2;print('YUE2 OK',torch.__version__,torch.cuda.is_available(),torch.cuda.get_device_capability())" ) > logs/yue2-install.log 2>&1 &
# SheetSage2's docs pin torch cu126; Blackwell GPUs (compute 12.0) need cu128.
( uv venv -p 3.11 .venv-sheetsage2 && uv pip install -p .venv-sheetsage2/bin/python huggingface-hub==0.36.0 \
  && .venv-sheetsage2/bin/huggingface-cli download m-a-p/SheetSage2 --local-dir models/SheetSage2 \
  && uv pip install -p .venv-sheetsage2/bin/python torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128 \
  && uv pip install -p .venv-sheetsage2/bin/python -r models/SheetSage2/requirements.txt \
  && .venv-sheetsage2/bin/python -c "import torch;print('SS2 OK',torch.__version__,torch.cuda.is_available())" ) > logs/ss2-install.log 2>&1 &
( sleep 60; until test -x .venv-yue2/bin/huggingface-cli; do sleep 10; done
  .venv-yue2/bin/huggingface-cli download m-a-p/YuE2-3B && .venv-yue2/bin/huggingface-cli download m-a-p/YuE2-Vae && echo WEIGHTS OK ) > logs/weights.log 2>&1 &
wait
echo ALL_DONE
