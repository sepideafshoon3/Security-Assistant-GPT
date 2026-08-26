import json
import re
import os
import logging
import datetime
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Union

# ----------------------------------------------------------------------
# Logger setup
# ----------------------------------------------------------------------
def setup_logger(name: str = "llm_logger") -> logging.Logger:
    """
    Creates a logger that writes to console and a rotating file.
    Configuration can be overridden with environment variables:
        LOG_LEVEL   – DEBUG, INFO, WARNING, ERROR (default: INFO)
        LOG_FILE    – path to log file (default: llm_calls.log)
        LOG_MAX_MB  – max size per log file in MB (default: 5)
        LOG_BACKUP  – number of backup files to keep (default: 3)
    """
    logger = logging.getLogger(name)
    if logger.handlers:  # Prevent duplicate handlers on re‑import
        return logger

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE", "llm_calls.log")
    max_bytes = int(os.getenv("LOG_MAX_MB", "5")) * 1024 * 1024
    backup_count = int(os.getenv("LOG_BACKUP", "3"))

    logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Console handler (color‑less, simple)
    console_handler = logging.StreamHandler()
    console_fmt = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    # Rotating file handler
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_fmt = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    logger.debug("Logger initialized – level=%s, file=%s", log_level, log_file)
    return logger


# Obtain a module‑wide logger instance
logger = setup_logger()


def _get_daily_llm_logger() -> logging.Logger:
    """Lazy-init a daily JSONL logger shared with the main openai_client."""
    try:
        from src.core.paths import BASE_DIR as _BASE_DIR
        log_dir_env = os.getenv("LLM_LOG_DIR")
        log_dir = Path(log_dir_env).expanduser() if log_dir_env else (_BASE_DIR / "logs" / "llm")
        log_dir.mkdir(parents=True, exist_ok=True)

        llm_log = logging.getLogger("mrrobot.llm")
        if not any(getattr(h, "log_dir", None) == log_dir for h in llm_log.handlers):
            from src.llm.openai_client import DailyFileHandler
            h = DailyFileHandler(log_dir=log_dir, prefix="llm")
            h.setFormatter(logging.Formatter("%(message)s"))
            llm_log.addHandler(h)
            llm_log.setLevel(logging.INFO)
            llm_log.propagate = False
        return llm_log
    except Exception:
        return logging.getLogger("mrrobot.llm")


# ----------------------------------------------------------------------
# JSON extraction helper
# ----------------------------------------------------------------------
def safe_parse_json(text: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Accepts either a raw JSON string or an already‑decoded dict.
    Returns a dict with the extracted JSON object.
    """
    if isinstance(text, dict):
        logger.debug("safe_parse_json received a dict – returning unchanged")
        return text

    logger.debug("Attempting to extract JSON from raw string")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        logger.error("No JSON object found in LLM response")
        raise ValueError("No JSON object found in LLM response")
    try:
        parsed = json.loads(text[start : end + 1])
        logger.debug("JSON successfully parsed")
        return parsed
    except json.JSONDecodeError as exc:
        logger.exception("JSON decoding failed")
        raise ValueError("Failed to decode JSON") from exc


# ----------------------------------------------------------------------
# LLM call wrapper
# ----------------------------------------------------------------------
def call_llm(*, system_prompt: str, user_prompt: str, json_mode: bool = True) -> Dict[str, Any]:
    """
    Sends prompts to the model. If `json_mode` is True, the API is asked
    to return a JSON object. The function always returns a dict.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.critical("OPENAI_API_KEY environment variable not set")
        raise RuntimeError("OPENAI_API_KEY not set")

    # Lazy import to avoid import errors when the function is not used
    from openai import OpenAI

    client = OpenAI(api_key=api_key)

    from src.llm.model_config import get_chat_model

    model_name = get_chat_model()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    kwargs = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "temperature": 0.0,
        "top_p": 1.0,

    }

    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    logger.info("Calling LLM – model=%s, json_mode=%s", model_name, json_mode)
    logger.debug("System prompt: %s", system_prompt)
    logger.debug("User prompt: %s", user_prompt)

    # ── Log full request to daily file ──
    llm_log = _get_daily_llm_logger()
    try:
        llm_log.info(json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "event": "llm_request",
            "layer": "call_llm",
            "api": "chat.completions",
            "model": model_name,
            "backend": base_url or "default",
            "json_mode": json_mode,
            "system_prompt_len": len(system_prompt or ""),
            "user_prompt_len": len(user_prompt or ""),
            "system_prompt": (system_prompt or "")[:50_000],
            "user_prompt": (user_prompt or "")[:50_000],
        }, ensure_ascii=False))
    except Exception:
        pass

    _llm_t0 = time.monotonic()
    try:
        response = client.chat.completions.create(**kwargs)
        raw = response.choices[0].message.content or ""
        _llm_elapsed = round((time.monotonic() - _llm_t0) * 1000, 2)
        logger.info("LLM response received in %.1fms (%d chars)", _llm_elapsed, len(raw))
    except Exception as exc:
        _llm_elapsed = round((time.monotonic() - _llm_t0) * 1000, 2)
        logger.exception("LLM request failed after %.1fms", _llm_elapsed)
        # ── Log error ──
        try:
            llm_log.info(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
                "event": "llm_error",
                "layer": "call_llm",
                "api": "chat.completions",
                "model": model_name,
                "backend": base_url or "default",
                "elapsed_ms": _llm_elapsed,
                "error": str(exc),
            }, ensure_ascii=False))
        except Exception:
            pass
        raise RuntimeError("Failed to get response from LLM") from exc

    # ── Log full response + reasoning + tokens to daily file ──
    try:
        usage = getattr(response, "usage", None)
        usage_data: Dict[str, Any] = {}
        if usage:
            usage_data = {
                "tokens_total": getattr(usage, "total_tokens", None),
                "tokens_prompt": getattr(usage, "prompt_tokens", None),
                "tokens_completion": getattr(usage, "completion_tokens", None),
            }

        # Full response text (1 MB cap)
        full_text = raw[:1_000_000] + ("...[TRUNCATED_AT_1MB]" if len(raw) > 1_000_000 else "")
        llm_log.info(json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "event": "llm_response",
            "layer": "call_llm",
            "api": "chat.completions",
            "model": model_name,
            "backend": base_url or "default",
            "elapsed_ms": _llm_elapsed,
            **usage_data,
            "text_length": len(raw),
            "text": full_text,
        }, ensure_ascii=False))

        # Full reasoning (NVIDIA NIM, DeepSeek, etc. may provide reasoning_content)
        msg = response.choices[0].message
        reasoning = getattr(msg, "reasoning", None) or ""
        if not reasoning:
            reasoning = getattr(msg, "reasoning_content", None) or ""
        full_reasoning = str(reasoning)[:10_000_000] if reasoning else ""
        llm_log.info(json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "event": "llm_reasoning",
            "layer": "call_llm",
            "api": "chat.completions",
            "model": model_name,
            "backend": base_url or "default",
            "elapsed_ms": _llm_elapsed,
            "missing": not bool(full_reasoning),
            "reasoning_length": len(full_reasoning),
            "reasoning": full_reasoning,
        }, ensure_ascii=False))

        # Thinking section (some models embed <Thinking>...</Thinking> in output)
        thinking = ""
        think_match = re.search(r"(?:## ?Thinking|<thinking>)(.*?)(?:</thinking>|## )", raw, re.DOTALL | re.IGNORECASE)
        if think_match:
            thinking = think_match.group(1).strip()
        llm_log.info(json.dumps({
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "event": "llm_thinking",
            "layer": "call_llm",
            "api": "chat.completions",
            "model": model_name,
            "backend": base_url or "default",
            "elapsed_ms": _llm_elapsed,
            "missing": not bool(thinking),
            "thinking_length": len(thinking) if thinking else 0,
            "thinking": thinking if thinking else None,
        }, ensure_ascii=False))
    except Exception:
        pass

    if json_mode:
        # Try strict parsing first
        try:
            result = json.loads(raw)
            logger.debug("Strict JSON parsing succeeded")
            return result
        except json.JSONDecodeError:
            logger.warning("Strict JSON parsing failed – falling back to safe_parse_json")
            # Fallback to safe extraction (handles dicts & noisy text)
            return safe_parse_json(raw)
    else:
        logger.debug("Non‑JSON mode – returning raw text")
        return {"text": raw}




def parse_llm_json(raw):
    # Case 1: already parsed (best case)
    if isinstance(raw, dict):
        return raw

    if not isinstance(raw, str):
        raise TypeError(f"Unsupported LLM output type: {type(raw)}")

    text = raw.strip()

    # Remove markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text)
        text = re.sub(r"```$", "", text)
        text = text.strip()

    # Extract first JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in LLM output")

    json_text = text[start:end + 1]

    return json.loads(json_text)


# ----------------------------------------------------------------------
# Example usage (can be removed or placed under `if __name__ == "__main__":`)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    sys_prompt = "You are a JSON‑only assistant."
    usr_prompt = "Return the current UTC date and time as a JSON object."
    try:
        result = call_llm(system_prompt=sys_prompt, user_prompt=usr_prompt, json_mode=True)
        logger.info("Parsed result: %s", result)
        print("Parsed result:", result)
    except Exception as e:
        logger.error("Example execution failed: %s", e)

