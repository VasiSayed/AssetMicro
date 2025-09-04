# asset/utils/tenant_db.py
from __future__ import annotations

import json
import logging
import os
from typing import Optional, Dict, Any, Tuple

import psycopg2
import requests
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.cache import cache
from django.db import connections

logger = logging.getLogger("asset.utils")

# LOCAL_DB_HOST = "192.168.29.168"
LOCAL_DB_HOST = "127.0.0.1"

CACHE_TTL_SECONDS = 2000
ACCOUNTS_URL = os.getenv("ACCOUNTS_SERVICE_URL", f"http://{LOCAL_DB_HOST}:8000").rstrip("/")
INTERNAL_REGISTER_DB_TOKEN = os.getenv("INTERNAL_REGISTER_DB_TOKEN", "").strip()
ACCOUNTS_TIMEOUT = int(os.getenv("ACCOUNTS_HTTP_TIMEOUT", "10"))
DB_ENCRYPTION_KEY = os.getenv("DB_ENCRYPTION_KEY", "").strip()
TENANT_CONN_MAX_AGE = int(os.getenv("TENANT_CONN_MAX_AGE", "60"))
TENANT_CONN_TIMEOUT = int(os.getenv("TENANT_CONN_TIMEOUT", "5"))



def get_cached_client_db_info(
    *, client_id: Optional[int] = None, client_username: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retrieve tenant database credentials from cache or fetch from the Accounts service.

    :param client_id: Numeric client identifier.
    :param client_username: Username uniquely identifying the client.
    :return: A mapping containing alias, db_name, db_user, db_password(_encrypted), db_host, db_port.
    :raises ValueError: If neither client_id nor client_username is provided.
    :raises RuntimeError: For upstream errors or malformed responses.
    """
    cache_key = f"tenant_db_info:{client_id or client_username}"
    data = cache.get(cache_key)
    if not data:
        data = fetch_client_db_info(client_id=client_id, client_username=client_username)
        cache.set(cache_key, data, CACHE_TTL_SECONDS)
    return data


def ensure_alias_for_client(
    *, client_id: Optional[int] = None, client_username: Optional[str] = None
) -> str:
    """
    Ensure a Django database alias exists for the given client.

    :param client_id: Numeric client identifier.
    :param client_username: Username uniquely identifying the client.
    :return: The registered Django database alias (e.g., "client_1845").
    :raises ValueError: If neither client_id nor client_username is provided.
    :raises RuntimeError: If connectivity or registration fails.
    """
    data = get_cached_client_db_info(client_id=client_id, client_username=client_username)
    alias = data["alias"]

    if alias in settings.DATABASES:
        logger.debug("Alias %s already registered", alias)
        return alias

    password = decrypt_password(data["db_password_encrypted"]) if data.get("db_password_encrypted") else data["db_password"]

    ok, err = test_db_connection(
        name=data["db_name"],
        user=data["db_user"],
        password=password,
        host=LOCAL_DB_HOST,
        port=str(data["db_port"]),
    )
    if not ok:
        raise RuntimeError(f"DB connect failed: {err}")

    add_db_alias(
        alias=alias,
        db_name=data["db_name"],
        db_user=data["db_user"],
        db_password=password,
        db_host=data["db_host"],
        db_port=str(data["db_port"]),
    )
    logger.info("DB alias '%s' registered", alias)
    return alias


def refresh_alias_for_client(
    *, client_id: Optional[int] = None, client_username: Optional[str] = None
) -> str:
    """
    Refresh the tenant database alias by evicting cache and re-registering the alias.

    :param client_id: Numeric client identifier.
    :param client_username: Username uniquely identifying the client.
    :return: The refreshed Django database alias.
    :raises ValueError: If neither client_id nor client_username is provided.
    :raises RuntimeError: If upstream fetch or alias recreation fails.
    """
    cache_key = f"tenant_db_info:{client_id or client_username}"
    cache.delete(cache_key)

    data = fetch_client_db_info(client_id=client_id, client_username=client_username)
    alias = data["alias"]

    try:
        connections[alias].close()
    except Exception:
        pass

    settings.DATABASES.pop(alias, None)
    connections.databases.pop(alias, None)

    return ensure_alias_for_client(client_id=client_id, client_username=client_username)


def _headers() -> Dict[str, str]:
    """
    Build HTTP headers for Accounts service requests.

    :return: Headers dictionary including optional internal token.
    """
    h = {"Accept": "application/json"}
    if INTERNAL_REGISTER_DB_TOKEN:
        h["X-Internal-Token"] = INTERNAL_REGISTER_DB_TOKEN
    return h


def fetch_client_db_info(
    *, client_id: Optional[int] = None, client_username: Optional[str] = None
) -> Dict[str, Any]:
    """
    Fetch tenant database credentials from the Accounts service.

    :param client_id: Numeric client identifier.
    :param client_username: Username uniquely identifying the client.
    :return: A mapping containing alias, db_name, db_user, db_password(_encrypted), db_host, db_port.
    :raises ValueError: If neither client_id nor client_username is provided.
    :raises RuntimeError: On HTTP errors, non-JSON bodies, or missing keys.
    """
    if not (client_id or client_username):
        raise ValueError("Provide client_id or client_username")

    if not ACCOUNTS_URL:
        raise RuntimeError("ACCOUNTS_SERVICE_URL not configured")

    if client_id:
        url = f"{ACCOUNTS_URL}/Client_db_info/by-client-id/"
        params = {"client_id": str(client_id)}
    else:
        url = f"{ACCOUNTS_URL}/api/master/user-dbs/by-username/{client_username}"
        params = {"username": client_username}

    logger.info("Fetching client DB info: %s params=%s", url, params)
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=ACCOUNTS_TIMEOUT)
    except requests.RequestException as e:
        raise RuntimeError(f"Accounts request failed: {e}") from e

    if resp.status_code != 200:
        body = _safe_trunc(resp.text)
        raise RuntimeError(f"Accounts error {resp.status_code}: {body}")

    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise RuntimeError("Accounts returned non-JSON response")

    required = ("db_name", "db_user", "db_host", "db_port")
    for k in required:
        if k not in data or data[k] in (None, ""):
            raise RuntimeError(f"Missing key '{k}' in Accounts response")

    if not data.get("db_password_encrypted") and not data.get("db_password"):
        raise RuntimeError("Missing db_password or db_password_encrypted in Accounts response")

    alias = data.get("alias") or f"client_{data.get('user_id')}"
    data["alias"] = str(alias)
    data["db_name"] = str(data["db_name"])
    data["db_user"] = str(data["db_user"])
    data["db_host"] = str(data["db_host"])
    data["db_port"] = str(data["db_port"])
    return data


def decrypt_password(enc_password: str) -> str:
    """
    Decrypt a Fernet-encrypted database password.

    :param enc_password: Ciphertext in URL-safe base64 format.
    :return: Decrypted plaintext password.
    :raises RuntimeError: If the encryption key is missing or decryption fails.
    """
    if not DB_ENCRYPTION_KEY:
        raise RuntimeError("DB_ENCRYPTION_KEY not set; cannot decrypt db_password_encrypted")

    try:
        f = Fernet(DB_ENCRYPTION_KEY.encode())
        return f.decrypt(enc_password.encode()).decode()
    except Exception as e:
        raise RuntimeError(f"Fernet decrypt failed: {e}") from e


def test_db_connection(
    *, name: str, user: str, password: str, host: str, port: str, timeout: int = TENANT_CONN_TIMEOUT
) -> Tuple[bool, Optional[str]]:
    """
    Probe connectivity to PostgreSQL.

    :param name: Database name.
    :param user: Database user.
    :param password: Database password.
    :param host: Database host.
    :param port: Database port as string.
    :param timeout: Connect timeout in seconds.
    :return: Tuple (ok, error_message). If ok is True, error_message is None.
    """
    logger.info("Testing DB connection to %s@%s:%s/%s", user, host, port, name)
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=name,
            user=user,
            password=password,
            host=host,
            port=port,
            connect_timeout=timeout,
        )
        logger.info("DB connection OK")
        return True, None
    except Exception as e:
        logger.error("DB connection FAILED: %s", e, exc_info=True)
        return False, str(e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def add_db_alias(*, alias: str, db_name: str, db_user: str, db_password: str, db_host: str, db_port: str) -> str:
    """
    Register a Django database alias at runtime.

    :param alias: The alias to register.
    :param db_name: Database name.
    :param db_user: Database user.
    :param db_password: Database password.
    :param db_host: Database host recorded for logging.
    :param db_port: Database port as string.
    :return: The registered alias.
    """
    cfg = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": db_name,
        "USER": db_user,
        "PASSWORD": db_password,
        "HOST": LOCAL_DB_HOST,
        "PORT": db_port,
        "CONN_MAX_AGE": TENANT_CONN_MAX_AGE,
        "CONN_HEALTH_CHECKS": True,
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "TIME_ZONE": getattr(settings, "TIME_ZONE", None),
        "OPTIONS": {"connect_timeout": TENANT_CONN_TIMEOUT},
    }

    settings.DATABASES[alias] = cfg
    connections.databases[alias] = cfg
    logger.info("Registered DB alias '%s' -> %s@%s:%s/%s", alias, db_user, db_host, db_port, db_name)
    return alias


def _safe_trunc(s: str, n: int = 280) -> str:
    """
    Truncate a string to at most n characters, appending an ellipsis if needed.

    :param s: Input string.
    :param n: Maximum length.
    :return: Possibly truncated string.
    """
    s = s or ""
    return s if len(s) <= n else (s[:n] + "…")


import os, requests
from django.core.cache import cache

INTERNAL_MASTER_BASE = os.getenv("INTERNAL_MASTER_BASE", "http://127.0.0.1:8000").rstrip("/")
INTERNAL_MASTER_TIMEOUT = int(os.getenv("INTERNAL_MASTER_TIMEOUT", "5"))

def _forward_auth_headers(request):
    h = {"Accept": "application/json"}
    auth = request.META.get("HTTP_AUTHORIZATION")
    if auth:
        h["Authorization"] = auth
    return h

def resolve_name(kind: str, obj_id: int | None, request) -> str | None:
    """
    kind: 'buildings' | 'floors' | 'units' | 'sites' (if you have it)
    Tries cache -> GET http://127.0.0.1:8000/api/<kind>/<id>/ -> cache
    Returns the 'name' or None on error.
    """
    if not obj_id:
        return None
    cache_key = f"name:{kind}:{obj_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        url = f"{INTERNAL_MASTER_BASE}/api/{kind}/{obj_id}/"
        resp = requests.get(url, headers=_forward_auth_headers(request), timeout=INTERNAL_MASTER_TIMEOUT)
        if resp.status_code == 200:
            name = (resp.json() or {}).get("name")
            if name:
                cache.set(cache_key, name, 600)  # 10 minutes
                return name
    except Exception:
        pass
    return None
