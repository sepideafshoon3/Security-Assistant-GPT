#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# dark_agent.py – رباتی که dark_recon را اجرا می‌کند و خروجی را به GPT می‌دهد
# usage:
#   python3 dark_agent.py cex.io

import os
import sys
import json
import subprocess
import time
import logging
import datetime
import re
from glob import glob
from pathlib import Path

from openai import OpenAI
from src.core.paths import BASE_DIR

logger = logging.getLogger(__name__)


def _get_daily_llm_logger() -> logging.Logger:
    """Lazy-init a daily JSONL logger shared with the main openai_client."""
    try:
        log_dir_env = os.getenv("LLM_LOG_DIR")
        log_dir = Path(log_dir_env).expanduser() if log_dir_env else (BASE_DIR / "logs" / "llm")
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


# ============================== تنظیمات تاریک ==============================
PLUGIN_ROOT = BASE_DIR / "src" / "plugins"
DARK_RECON_SCRIPT = PLUGIN_ROOT / "dark_recon_plugin" / "dark_recon_plugin.sh"

RECON_ROOT = BASE_DIR / "data"
RECON_GLOB = str(RECON_ROOT / "recon_*")

def _get_openai_model() -> str:
    """Chat model from env (OPENAI_DEFAULT_CHAT_MODEL / LLM_MODEL)."""
    from src.llm.model_config import get_chat_model
    return get_chat_model()


# Back-compat alias; prefer _get_openai_model() so env is read at call time.
OPENAI_MODEL = _get_openai_model()
MAX_OUTPUT_TOKENS = 10000
DARK_RECON_TIMEOUT_SEC = 900.0  # 15 دقیقه، هرچی دوست داری

client = OpenAI()


# ============================== ابزار اجرای recon ==============================

def run_dark_recon_agent(domain: str) -> Path:
    if not DARK_RECON_SCRIPT.is_file():
        raise RuntimeError(f"[x] dark_recon script not found: {DARK_RECON_SCRIPT}")

    DARK_RECON_SCRIPT.chmod(0o755)

    cwd = BASE_DIR

    cmd = [str(DARK_RECON_SCRIPT), domain]
    print(f"[*] Running: {' '.join(cmd)}  (cwd={cwd})")

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=DARK_RECON_TIMEOUT_SEC,
        cwd=cwd,
        env={
            **os.environ,
            "RECON_OUTPUT_DIR": str(RECON_ROOT),
        },
    )

    print("===== dark_recon output =====")
    print(proc.stdout)
    print("===== end of dark_recon output =====")

    recon_dirs = [Path(p) for p in glob(RECON_GLOB) if Path(p).is_dir()]
    if not recon_dirs:
        raise RuntimeError(
            f"[x] No recon_* directories found under {RECON_ROOT} after running dark_recon."
        )

    recon_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    latest_dir = recon_dirs[0]
    print(f"[*] Latest recon dir: {latest_dir}")
    return latest_dir


def find_latest_summary(recon_dir: Path) -> Path:
    candidates = list(recon_dir.glob("**/dark_recon_summary*.json"))
    if not candidates:
        raise RuntimeError(f"[x] No dark_recon_summary*.json found inside {recon_dir}")

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    latest_summary = candidates[0]
    print(f"[*] Using summary JSON: {latest_summary}")
    return latest_summary


def load_summary(summary_path: Path) -> dict:
    with summary_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ask_gpt_attack_plan(domain: str, recon_json: dict, max_retries: int = 3) -> str:
    """
    فرستادن JSON به GPT و گرفتن پلن حمله.
    با auto-retry و لاگ خطا تا اگر لایه LLM قاطی کرد، اسکریپتت نسوزه.
    """
    dark_prompt = f"""
تو یک مهاجم حرفه‌ای هستی. این خروجی full reconnaissance روی دامنه `{domain}` است.
خروجی JSON زیر را کامل تحلیل کن و یک attack plan مرحله‌به‌مرحله بنویس که شامل موارد زیر باشد:

- خلاصه سطح حمله (attack surface summary)
- زنجیره‌های اکسپلویت محتمل (exploit chains)
- اولویت‌بندی تارگت‌ها بر اساس impact و سهولت حمله
- payloadها، ابزارها و تکنیک‌های مناسب هر مرحله

خروجی را به صورت مارک‌داون بده؛ ساختار پیشنهادی:

# Attack Plan for {domain}

## 1. Recon Summary
...

## 2. High-Value Targets
...

## 3. Exploit Chains
...

## 4. Post-Exploitation & Persistence
...

اینجا JSON است:
{json.dumps(recon_json, ensure_ascii=False, indent=2)}
"""

    llm_log = _get_daily_llm_logger()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    model_name = _get_openai_model()

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[*] Calling GPT attack planner (attempt {attempt}/{max_retries})...")
            logger.info("ask_gpt_attack_plan: attempt %d/%d, model=%s", attempt, max_retries, model_name)

            # ── Log request ──
            try:
                llm_log.info(json.dumps({
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_request",
                    "layer": "attack_plan",
                    "api": "chat.completions",
                    "model": model_name,
                    "backend": base_url or "default",
                    "attempt": attempt,
                    "domain": domain,
                }, ensure_ascii=False))
            except Exception:
                pass

            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an offensive security strategist. Produce detailed attack plans.",
                    },
                    {"role": "user", "content": dark_prompt},
                ],
                max_tokens=MAX_OUTPUT_TOKENS,
                temperature=0.2,
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("empty GPT response")

            # ── Log full response + reasoning + tokens ──
            try:
                usage = getattr(response, "usage", None)
                usage_data = {}
                if usage:
                    usage_data = {
                        "tokens_total": getattr(usage, "total_tokens", None),
                        "tokens_prompt": getattr(usage, "prompt_tokens", None),
                        "tokens_completion": getattr(usage, "completion_tokens", None),
                    }
                safe_text = content[:10_000] + ("...[TRUNCATED]" if len(content) > 10_000 else "")
                llm_log.info(json.dumps({
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_response",
                    "layer": "attack_plan",
                    "api": "chat.completions",
                    "model": model_name,
                    "backend": base_url or "default",
                    "attempt": attempt,
                    "domain": domain,
                    **usage_data,
                    "text": safe_text,
                }, ensure_ascii=False))

                # Reasoning (NVIDIA NIM / DeepSeek may provide reasoning_content)
                msg = response.choices[0].message
                reasoning = getattr(msg, "reasoning", None) or ""
                if not reasoning:
                    reasoning = getattr(msg, "reasoning_content", None) or ""
                safe_reasoning = str(reasoning)[:10_000_000] if reasoning else ""
                llm_log.info(json.dumps({
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_reasoning",
                    "layer": "attack_plan",
                    "api": "chat.completions",
                    "model": model_name,
                    "backend": base_url or "default",
                    "missing": not bool(safe_reasoning),
                    "reasoning": safe_reasoning,
                }, ensure_ascii=False))

                # Thinking section
                thinking = ""
                think_match = re.search(
                    r"(?:## ?Thinking|<thinking>)(.*?)(?:</thinking>|## )",
                    content, re.DOTALL | re.IGNORECASE,
                )
                if think_match:
                    thinking = think_match.group(1).strip()
                llm_log.info(json.dumps({
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_thinking",
                    "layer": "attack_plan",
                    "api": "chat.completions",
                    "model": model_name,
                    "backend": base_url or "default",
                    "missing": not bool(thinking),
                    "thinking": thinking if thinking else None,
                }, ensure_ascii=False))
            except Exception:
                pass

            return content
        except Exception as ex:
            last_exc = ex
            print(f"[!] GPT call failed on attempt {attempt}: {ex}")
            logger.error("ask_gpt_attack_plan: attempt %d failed: %s", attempt, ex)
            try:
                llm_log.info(json.dumps({
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                    "event": "llm_error",
                    "layer": "attack_plan",
                    "api": "chat.completions",
                    "model": model_name,
                    "backend": base_url or "default",
                    "attempt": attempt,
                    "error": str(ex),
                }, ensure_ascii=False))
            except Exception:
                pass
            time.sleep(3 * attempt)

    raise RuntimeError(f"[x] GPT attack plan generation failed after {max_retries} attempts: {last_exc}")


def save_attack_plan(domain: str, content: str) -> Path:
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = BASE_DIR / "data" / "attack_plans"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"attack_plan_{domain}_{ts}.md"
    out_path.write_text(content, encoding="utf-8")
    print(f"[*] Attack plan saved to: {out_path}")
    return out_path


def main():
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <domain>")
        sys.exit(1)

    domain = sys.argv[1].strip()
    latest_recon_dir = run_dark_recon_agent(domain)
    summary_path = find_latest_summary(latest_recon_dir)
    recon_json = load_summary(summary_path)
    attack_md = ask_gpt_attack_plan(domain, recon_json)
    save_attack_plan(domain, attack_md)


if __name__ == "__main__":
    main()