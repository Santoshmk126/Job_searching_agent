from collections import deque
import json
import os
import re
import sys
import time
from typing import Any, Callable
import warnings
from edgedash.config import Config, load_config


class LLMError(Exception):
    """Raised when LLM call, parsing, or validation fails."""
    pass


# Rate limiting state (Rule 15: min 1s between calls, max 15 calls/min)
_last_call_time: float = 0.0
_call_history: deque[float] = deque()


def _rate_limit() -> None:
    global _last_call_time
    now = time.time()
    if (now - _last_call_time) < 1.0:
        time.sleep(1.0 - (now - _last_call_time))
        now = time.time()
    while _call_history and (_call_history[0] <= now - 60.0):
        _call_history.popleft()
    if len(_call_history) >= 15:
        sleep_dur = 60.0 - (now - _call_history[0]) + 0.1
        if sleep_dur > 0:
            time.sleep(sleep_dur)
            now = time.time()
    _last_call_time = now
    _call_history.append(now)


def _redact(text: Any) -> str:
    """Mask any Google API keys in exception messages or logs."""
    return re.sub(r"AIza[0-9A-Za-z-_]{35}", "[REDACTED_KEY]", str(text))


def _clean_json_text(text: str) -> str:
    c = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    c = re.sub(r"\s*```$", "", c)
    starts = [s for s in (c.find("{"), c.find("[")) if s != -1]
    start = min(starts) if starts else -1
    end = max(c.rfind("}"), c.rfind("]"))
    return c[start : end + 1] if (start != -1 and end > start) else c


def _validate_schema(data: Any, schema: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict, got {type(data).__name__}")
    req = schema.get("required") if isinstance(schema.get("required"), list) else None
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else None
    expected = req or (list(props.keys()) if props else list(schema.keys()))
    missing = [k for k in expected if k not in data]
    if missing:
        raise ValueError(f"Missing required key(s): {missing}")


def _call_gemini(prompt: str, model_name: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not api_key.strip():
        raise LLMError("Missing GEMINI_API_KEY environment variable. Please add it to your .env file.")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import google.generativeai as genai
        genai.configure(api_key=api_key.strip())
        model = genai.GenerativeModel(model_name)
        res = model.generate_content(prompt)
        if not res or not res.text:
            raise LLMError("Gemini returned an empty response.")
        return res.text


def _call_ollama(prompt: str, model_name: str) -> str:
    import urllib.request
    payload = json.dumps({"model": model_name, "prompt": prompt, "stream": False, "format": "json"}).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            return str(body.get("response", ""))
    except Exception as exc:
        raise LLMError(f"Ollama request failed: {exc}") from exc


PROVIDERS: dict[str, Callable[[str, str], str]] = {"gemini": _call_gemini, "ollama": _call_ollama}


def _execute_with_backoff(fn: Callable[[str, str], str], prompt: str, model: str) -> str:
    for attempt in range(3):
        try:
            return fn(prompt, model)
        except Exception as exc:
            msg = str(exc).lower()
            if ("429" in msg or "quota" in msg or "resourceexhausted" in msg) and attempt < 2:
                time.sleep(6.0 * (attempt + 1))
                continue
            raise
    raise LLMError("Exceeded maximum quota retries (3 attempts).")


def complete_json(prompt: str, schema: dict[str, Any], *, config: Config | None = None, max_retries: int = 1) -> dict[str, Any]:
    cfg = config or load_config()
    provider_key = cfg.llm_provider.lower().strip()
    if provider_key not in PROVIDERS:
        raise LLMError(f"Unsupported LLM provider '{cfg.llm_provider}'. Supported: {list(PROVIDERS.keys())}")

    provider_fn = PROVIDERS[provider_key]
    current_prompt = prompt
    last_err: Exception | None = None

    for attempt in range(max_retries + 1):
        _rate_limit()
        try:
            raw_text = _execute_with_backoff(provider_fn, current_prompt, cfg.llm_model)
            cleaned = _clean_json_text(raw_text)
            parsed = json.loads(cleaned)
            _validate_schema(parsed, schema)
            return parsed
        except Exception as exc:
            last_err = exc
            if attempt < max_retries:
                current_prompt = (
                    prompt + "\n\n"
                    f"[CORRECTION]: Previous response failed validation: {_redact(exc)}. "
                    "Reply with ONLY valid JSON matching the schema. No markdown fences, no prose."
                )
                continue
            raise LLMError(f"LLM JSON completion failed: {_redact(last_err)}") from None
    raise LLMError(f"LLM JSON completion failed: {_redact(last_err)}")


if __name__ == "__main__":
    if "--check" in sys.argv:
        conf = load_config()
        print(f"Provider : {conf.llm_provider}")
        print(f"Model    : {conf.llm_model}")
        try:
            result = complete_json("Return a JSON object with key 'status' set to 'ok'.", {"status": str}, config=conf)
            print(f"Status   : OK -> {result}")
        except Exception as err:
            print(f"Status   : FAILED -> {_redact(err)}")
            sys.exit(1)
