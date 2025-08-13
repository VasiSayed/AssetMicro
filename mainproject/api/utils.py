import os
import psycopg2
import logging
from cryptography.fernet import Fernet
from django.conf import settings
from django.db import connections

logger = logging.getLogger("asset.utils")

def decrypt_password(enc_password: str) -> str:
    logger.debug("Decrypting DB password (len=%s)", len(enc_password or ""))
    key = os.environ['DB_ENCRYPTION_KEY'].encode()
    plain = Fernet(key).decrypt(enc_password.encode()).decode()
    logger.debug("Decryption successful")
    return plain

def add_db_alias(alias: str, *, db_name, db_user, db_password, db_host, db_port):
    logger.info("Registering DB alias '%s' -> %s@%s:%s/%s",
                alias, db_user, db_host, db_port, db_name)
    cfg = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': db_name,
        'USER': db_user,
        'PASSWORD': db_password,  # DO NOT LOG
        'HOST': db_host,
        'PORT': db_port,
        'OPTIONS': {},
        'ATOMIC_REQUESTS': False,
        'AUTOCOMMIT': True,
        'TIME_ZONE': getattr(settings, 'TIME_ZONE', None),
        'CONN_HEALTH_CHECKS': False,
        'CONN_MAX_AGE': 0,
    }
    settings.DATABASES[alias] = cfg
    connections.databases[alias] = cfg
    logger.info("DB alias '%s' registered in settings & connections", alias)
    return alias

def test_db_connection(*, name, user, password, host, port):
    logger.info("Testing DB connection to %s@%s:%s/%s", user, host, port, name)
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=name, user=user, password=password, host=host, port=port, connect_timeout=5
        )
        logger.info("DB connection OK")
        return True, None
    except Exception as e:
        logger.error("DB connection FAILED: %s", e, exc_info=True)
        return False, str(e)
    finally:
        if conn:
            conn.close()
            logger.debug("Test connection closed")


log = logging.getLogger("asset.accounts")

ACCOUNTS_URL = os.getenv("ACCOUNTS_SERVICE_URL", "http://localhost:8000")
ACCOUNTS_TOKEN = os.getenv("ACCOUNTS_SERVICE_TOKEN")

def _headers():
    h = {"Accept": "application/json"}
    if ACCOUNTS_TOKEN:
        h["Authorization"] = f"Bearer {ACCOUNTS_TOKEN}"
    return h

def fetch_client_db_info(*, client_id: Optional[int] = None, client_username: Optional[str] = None) -> dict:
    """
    Calls Central Accounts service to get DB creds for a client.
    Expected response (example):
    {
      "alias": "client_1845",
      "db_name": "...",
      "db_user": "...",
      "db_password_encrypted": "...",  # preferred (FERNET)
      "db_host": "...",
      "db_port": "5432"
    }
    """
    if not ACCOUNTS_URL:
        raise RuntimeError("ACCOUNTS_SERVICE_URL not configured")

    if client_id:
        url = f"{ACCOUNTS_URL}/Client_db_info/by-client-id/"
        params = {"client_id": str(client_id)}
    elif client_username:
        url = f"{ACCOUNTS_URL}/Client_db_info/by-username/"
        params = {"username": client_username}
    else:
        raise ValueError("Provide client_id or client_username")

    resp = requests.get(url, headers=_headers(), params=params, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Accounts responded {resp.status_code}: {resp.text}")
    data = resp.json()

    # normalize expected keys
    for k in ("alias", "db_name", "db_user", "db_host", "db_port"):
        if k not in data or not data[k]:
            raise RuntimeError(f"Missing key '{k}' in Accounts response")
    # password may be encrypted or plain; prefer encrypted
    if "db_password_encrypted" not in data and "db_password" not in data:
        raise RuntimeError("Missing db_password or db_password_encrypted")

    return data

def ensure_alias_for_client(*, client_id: Optional[int] = None, client_username: Optional[str] = None) -> str:
    """
    Ensures settings.DATABASES has the tenant alias. Registers it if missing.
    Returns the alias string (e.g., 'client_1845').
    """
    data = fetch_client_db_info(client_id=client_id, client_username=client_username)
    alias = data["alias"]

    if alias in settings.DATABASES:
        log.debug("Alias %s already registered", alias)
        return alias

    # decrypt if needed
    if "db_password_encrypted" in data:
        real_pw = decrypt_password(data["db_password_encrypted"])
    else:
        real_pw = data["db_password"]

    # test connectivity first
    ok, err = test_db_connection(
        name=data["db_name"],
        user=data["db_user"],
        password=real_pw,
        host=data["db_host"],
        port=data["db_port"],
    )
    if not ok:
        raise RuntimeError(f"DB connect failed: {err}")

    # register alias
    add_db_alias(
        alias=alias,
        db_name=data["db_name"],
        db_user=data["db_user"],
        db_password=real_pw,
        db_host=data["db_host"],
        db_port=data["db_port"],
    )
    return alias

def refresh_alias_for_client(*, client_id: Optional[int] = None, client_username: Optional[str] = None) -> str:
    """
    Force-refresh the alias in case creds/host changed centrally.
    """
    data = fetch_client_db_info(client_id=client_id, client_username=client_username)
    alias = data["alias"]

    try:
        connections[alias].close()
    except Exception:
        pass
    settings.DATABASES.pop(alias, None)
    try:
        connections.databases.pop(alias, None)
    except Exception:
        pass

    return ensure_alias_for_client(client_id=client_id, client_username=client_username)