# gtos/core/llm.py
"""LLM 接口：OpenAI 兼容 Chat Completions 实现。"""

import json
import os
from dataclasses import dataclass
from typing import Callable
from urllib import request

GenerateFn = Callable[[str], str]
FixFn = Callable[[str, str], str]


def _extract_python_code(text: str) -> str:
    body = (text or "").strip()
    if "```" not in body:
        return body
    blocks = body.split("```")
    for block in blocks:
        b = block.strip()
        if b.startswith("python"):
            return b[len("python"):].strip()
    if len(blocks) >= 2:
        return blocks[1].strip()
    return body


@dataclass
class OpenAICompatibleSettings:
    base_url: str
    api_key: str
    model: str
    tokenizer_model: str
    temperature: float
    max_output_tokens: int
    max_input_tokens: int
    timeout_seconds: int

    @classmethod
    def from_config(cls, config: dict | None = None) -> "OpenAICompatibleSettings":
        cfg = config or {}
        api_key_env = str(cfg.get("api_key_env", "OPENAI_API_KEY")).strip()
        # 容错：若误把 key 填到 api_key_env，直接当作 key 使用。
        if api_key_env.startswith("sk-"):
            api_key = api_key_env
            api_key_env = "OPENAI_API_KEY"
        else:
            api_key = (cfg.get("api_key") or os.environ.get(api_key_env, "")).strip()
        model = (cfg.get("model") or "").strip()
        if not api_key:
            raise RuntimeError(f"LLM API key is missing. Set config.llm.api_key or env {api_key_env}.")
        if not model:
            raise RuntimeError("LLM model is missing. Set config.llm.model.")
        base_url = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            tokenizer_model=(cfg.get("tokenizer_model") or model).strip(),
            temperature=float(cfg.get("temperature", 0.2)),
            max_output_tokens=int(cfg.get("max_output_tokens", 1200)),
            max_input_tokens=int(cfg.get("max_input_tokens", 12000)),
            timeout_seconds=int(cfg.get("timeout_seconds", 60)),
        )


class OpenAICompatibleLLM:
    def __init__(self, settings: OpenAICompatibleSettings) -> None:
        self._settings = settings
        self._encoding = self._build_encoding(settings.tokenizer_model)

    def _build_encoding(self, tokenizer_model: str):
        try:
            import tiktoken  # type: ignore

            return tiktoken.encoding_for_model(tokenizer_model)
        except Exception:
            return None

    def _count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._encoding is not None:
            try:
                return len(self._encoding.encode(text))
            except Exception:
                pass
        return max(1, len(text) // 4)

    def _trim_user_text(self, user_text: str) -> str:
        max_input = self._settings.max_input_tokens
        if max_input <= 0:
            return user_text
        reserve = 2000
        budget = max(1000, max_input - reserve)
        if self._count_tokens(user_text) <= budget:
            return user_text
        trimmed = user_text
        while len(trimmed) > 1000 and self._count_tokens(trimmed) > budget:
            trimmed = trimmed[: int(len(trimmed) * 0.9)]
        return trimmed

    def _chat(self, *, system_prompt: str, user_prompt: str) -> str:
        endpoint = self._settings.base_url
        if not endpoint.endswith("/v1"):
            endpoint = endpoint + "/v1"
        endpoint = endpoint + "/chat/completions"
        body = {
            "model": self._settings.model,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": self._trim_user_text(user_prompt)},
            ],
        }
        req = request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._settings.api_key}",
            },
        )
        try:
            with request.urlopen(req, timeout=self._settings.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"OpenAI-compatible request failed: {e}") from e
        try:
            return payload["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(f"Unexpected LLM response: {payload}") from e

    def generate_code(self, task_prompt: str) -> str:
        system_prompt = (
            "You generate runnable Python code only. "
            "Return only Python code without markdown fences."
        )
        content = self._chat(system_prompt=system_prompt, user_prompt=task_prompt)
        return _extract_python_code(content)

    def fix_code(self, task_prompt: str, error_info: str) -> str:
        system_prompt = (
            "You repair Python code tasks based on runtime errors. "
            "Return only corrected runnable Python code."
        )
        user_prompt = (
            f"Task:\n{task_prompt}\n\n"
            f"Runtime error:\n{error_info[:4000]}\n\n"
            "Provide corrected Python code only."
        )
        content = self._chat(system_prompt=system_prompt, user_prompt=user_prompt)
        return _extract_python_code(content)

    def refine_task(self, task_prompt: str) -> str:
        system_prompt = "Rewrite task descriptions for code generation: concise, specific, testable."
        refined = self._chat(system_prompt=system_prompt, user_prompt=task_prompt)
        return refined or task_prompt


class LLMClient:
    """统一入口：默认使用 OpenAI 兼容配置；也支持外部注入函数。"""

    def __init__(
        self,
        config: dict | None = None,
        generate: GenerateFn | None = None,
        fix: FixFn | None = None,
        refine: Callable[[str], str] | None = None,
    ) -> None:
        if generate or fix or refine:
            if not generate or not fix:
                raise RuntimeError("Custom LLM injection requires both generate and fix functions.")
            self.generate = generate
            self.fix = fix
            self._refine = refine
            return
        backend = OpenAICompatibleLLM(OpenAICompatibleSettings.from_config(config))
        self.generate = backend.generate_code
        self.fix = backend.fix_code
        self._refine = backend.refine_task

    def generate_code(self, task_prompt: str) -> str:
        return self.generate(task_prompt)

    def fix_code(self, task_prompt: str, error_info: str) -> str:
        return self.fix(task_prompt, error_info)

    def refine_task(self, task_prompt: str) -> str:
        if self._refine:
            return self._refine(task_prompt)
        return task_prompt
