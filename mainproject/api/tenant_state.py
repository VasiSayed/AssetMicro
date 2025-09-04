# api/tenant_state.py
import threading
_local = threading.local()

def set_current_db_alias(alias: str | None):
    _local.db_alias = alias

def get_current_db_alias() -> str | None:
    return getattr(_local, "db_alias", None)

def clear_current_db_alias():
    if hasattr(_local, "db_alias"):
        delattr(_local, "db_alias")
