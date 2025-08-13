# UserService/db_router.py
from contextvars import ContextVar

_current_tenant = ContextVar("current_tenant", default=None)

def set_current_tenant(alias: str | None):
    _current_tenant.set(alias)

def get_current_tenant() -> str | None:
    return _current_tenant.get()


class MultiTenantRouter:
    """
    MASTER apps -> default (SQLite): config, auth, admin, contenttypes, sessions
    TENANT apps -> per-tenant Postgres: accounts
    """
    master_apps = {"config", "auth", "admin", "contenttypes", "sessions"}
    tenant_apps = {"api"}

    def _tenant_for_hints(self, hints):
        return hints.get("tenant_db") or get_current_tenant()

    def db_for_read(self, model, **hints):
        app = model._meta.app_label
        if app in self.master_apps:  return "default"
        if app in self.tenant_apps:  return self._tenant_for_hints(hints)
        return None

    def db_for_write(self, model, **hints):
        app = model._meta.app_label
        if app in self.master_apps:  return "default"
        if app in self.tenant_apps:  return self._tenant_for_hints(hints)
        return None

    def allow_relation(self, obj1, obj2, **hints):
        # Only allow relations within same DB
        db1 = self.db_for_read(obj1._meta.model, **hints) or "default"
        db2 = self.db_for_read(obj2._meta.model, **hints) or "default"
        return db1 == db2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.master_apps:  
            return db == "default"
        if app_label in self.tenant_apps:   
            return db != "default"
        return False