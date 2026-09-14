# Web app, and the worker in fake-model mode (no GPU). The GPU worker image is docker/worker-gpu.Dockerfile.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY yue2 ./yue2
ARG EXTRAS=""
RUN pip install --no-cache-dir ".${EXTRAS}"

ENV PYTHONUNBUFFERED=1 YUE2_HOME=/data
EXPOSE 8080
CMD ["python", "-m", "yue2", "api"]
