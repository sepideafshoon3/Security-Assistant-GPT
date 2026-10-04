"""Rate limiting for endpoints that are cheap to abuse: login (credential
stuffing / brute force), chat (cost — each request calls out to the LLM
provider), and every state-changing (POST/PATCH/DELETE) endpoint, so a
single client can't hammer the database or disk.

Backed by slowapi's default in-memory store, which is fine for a single
process. If this ever runs as more than one worker/instance, switch the
Limiter's ``storage_uri`` to a shared Redis instance (see slowapi's docs)
or counts will be per-process instead of global — each instance would
quietly allow its own full quota.

Limits are env-configurable (see .env.example) so they can be tuned
without a code change; same pattern as DATABASE_URL / LOG_LEVEL elsewhere
in this codebase.
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

LOGIN_RATE_LIMIT = os.getenv("RATE_LIMIT_LOGIN", "5/minute")
# Account creation: stops scripted mass-signup.
SIGNUP_RATE_LIMIT = os.getenv("RATE_LIMIT_SIGNUP", "5/minute")
CHAT_RATE_LIMIT = os.getenv("RATE_LIMIT_CHAT", "20/minute")
# Default for writes to conversations/projects (create, rename, delete).
WRITE_RATE_LIMIT = os.getenv("RATE_LIMIT_WRITE", "30/minute")
# Online-learning event ingestion (client -> API and service -> API).
ONLINE_LEARNING_RATE_LIMIT = os.getenv("RATE_LIMIT_ONLINE_LEARNING", "60/minute")
# Building a dataset reads and rewrites files on disk — much heavier.
DATASET_BUILD_RATE_LIMIT = os.getenv("RATE_LIMIT_DATASET_BUILD", "5/minute")

# Keyed by client IP. Good enough against anonymous brute-forcing of
# /auth/login; for /chat (already authenticated) this still caps abuse
# from any single source, but doesn't distinguish users behind the same
# IP (e.g. an office NAT) sharing a quota. Switch key_func to pull the
# user id off the request if that becomes a real problem.
limiter = Limiter(key_func=get_remote_address)
