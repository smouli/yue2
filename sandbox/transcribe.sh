
cd /home/marimo/hack/YuE/skills/yue2-music
export HF_HOME=/home/marimo/hack/hf-cache
PY=/home/marimo/hack/.venv-sheetsage2/bin/python
for T in melody-vocal full; do
  S=$(date +%s)
  env -u PYTHONSAFEPATH $PY scripts/transcribe.py /home/marimo/hack/input/song.mp3 --task $T --model /home/marimo/hack/models/SheetSage2 --output /home/marimo/hack/runs/island-$T
  echo "TASK=$T EXIT=$? SECONDS=$(( $(date +%s)-S ))"
done
echo TRANSCRIBE_DONE
