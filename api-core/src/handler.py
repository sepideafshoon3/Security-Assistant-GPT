# src/app/handler.py

import re
from pathlib import Path

from src.llm.openai_client import load_llm_config
from src.llm.router import create_advisor
from src.agents.dark_recon_agent import run_dark_recon_agent

def handle_user_text(raw_text: str, config_dir: Path) -> str:
    # LLM (OpenAI or xAI via central router)
    llm_cfg = load_llm_config(config_dir)
    advisor = create_advisor(llm_cfg)

    # چک اگر درخواست dark_recon است
    m = re.search(r"dark_recon\s+(\S+)", raw_text)
    if m:
        domain = m.group(1).strip()
        # 1) پاسخ فوری به یوزر (می‌تونی این را sync برگردانی)
        #    و در عین حال، اگر UI/استریم داری، فاز دوم را بعداً push کنی.
        # اگر فقط یک پاسخ نهایی می‌خواهی، می‌توانیم به‌صورت ساده‌تر:
        #
        #   اول یک متن «در حال اجرا...» بسازیم،
        #   بعد agent را اجرا کنیم،
        #   بعد attack plan را بچینیم پشتش.

        running_msg = f"dark_recon در حال اجرا روی {domain} ... کمی صبر کن.\n"

        # اجرای agent (بلوکینگ)
        attack_plan = run_dark_recon_agent(domain, advisor)

        done_msg = "\n---\n[+] dark_recon تمام شد. این هم پلن حمله:\n\n"
        return running_msg + done_msg + attack_plan

    # اگر dark_recon نبود → معمولی بفرست برای LLM
    messages = [{"role": "user", "content": raw_text}]
    return advisor.secure_chat(messages, resource_text="")