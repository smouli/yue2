"""JSON chat completions against any OpenAI-compatible endpoint (W&B Inference, DigitalOcean Serverless Inference,
a self-hosted vLLM server...)."""

import json
import re

from yue2.config import Settings

# Reasoning models spend completion tokens thinking before they answer; give them room.
REASONING_MODELS = {"openai/gpt-oss-120b", "openai/gpt-oss-20b", "zai-org/GLM-5.2", "zai-org/GLM-5.3-Flash",
                    "moonshotai/Kimi-K2.6", "moonshotai/Kimi-K2.7-Code", "MiniMaxAI/MiniMax-M3",
                    "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B"}


class LLM:
    def __init__(self, settings: Settings):
        import openai

        self._openai = openai
        kwargs = {"base_url": settings.llm_base_url, "api_key": settings.llm_api_key,
                  "default_headers": {"User-Agent": "yue2/0.2"}}
        if settings.llm_project:
            kwargs["project"] = settings.llm_project  # W&B Inference bills to entity/project
        self.client = openai.OpenAI(**kwargs)

    def json(self, model: str, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.7) -> dict:
        extra = {}
        if model in REASONING_MODELS:
            max_tokens = max(max_tokens, 16000)
            if model.startswith("openai/gpt-oss"):
                extra["reasoning_effort"] = "low"
        else:
            extra["response_format"] = {"type": "json_object"}  # otherwise some models wrap invalid JSON in fences
        problem = ""
        for _attempt in range(3):  # retry truncated or malformed JSON before failing
            try:
                response = self.client.chat.completions.create(
                    model=model, max_tokens=max_tokens, temperature=temperature,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **extra)
            except self._openai.BadRequestError:
                if extra.pop("response_format", None) is None:
                    raise
                continue  # model doesn't support JSON mode; retry without it
            text = response.choices[0].message.content or ""
            parsed = parse_json(text)
            if parsed is not None:
                return parsed
            problem = f"finish_reason={response.choices[0].finish_reason}: {text[:300]}"
        raise ValueError(f"{model} returned no valid JSON ({problem})")


def parse_json(text: str) -> dict | None:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = fenced.group(1) if fenced else text
    match = re.search(r"\{.*\}", body, re.S)
    if not match:
        return None
    for candidate in (match.group(0), re.sub(r",\s*([\]}])", r"\1", match.group(0))):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None
