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
from starlette.requests import Request

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

# Number of trusted reverse proxies between the internet and this app that
# each append to X-Forwarded-For (0 = none: use the socket address, the
# safe default for local runs and plain docker-compose).
#
# Behind a proxy (Render) the socket address is the proxy's, so without
# this every user shares ONE rate-limit bucket. With it, the client IP is
# taken N entries from the RIGHT of X-Forwarded-For, i.e. the address the
# outermost proxy we trust actually saw. Never read the leftmost entry:
# the client controls it, so rotating a forged header would give every
# request a fresh bucket and defeat the limits (login brute force).
#
# Pick N by counting proxies; if unsure, round DOWN: too low only makes
# buckets coarser (several users per bucket), too high makes the key
# forgeable. See DEPLOY.md for how to verify on staging.
TRUSTED_PROXY_HOPS = max(0, int(os.getenv("TRUSTED_PROXY_HOPS", "0")))


def client_ip(request: Request) -> str:
    """Rate-limit key: the client IP, honouring TRUSTED_PROXY_HOPS."""
    hops = TRUSTED_PROXY_HOPS
    if hops > 0:
        values = request.headers.getlist("x-forwarded-for")
        parts = [p.strip() for v in values for p in v.split(",") if p.strip()]
        # Fewer entries than trusted hops means the request didn't come
        # through the proxy chain we expect: don't guess, use the socket.
        if len(parts) >= hops:
            return parts[-hops]
    return get_remote_address(request)


# Keyed by client IP (see client_ip). Good enough against anonymous
# brute-forcing of /auth/login; for authenticated endpoints this still
# caps abuse from any single source, but doesn't distinguish users behind
# the same IP (e.g. an office NAT) sharing a quota. Switch key_func to
# pull the user id off the request if that becomes a real problem.
limiter = Limiter(key_func=client_ip)
