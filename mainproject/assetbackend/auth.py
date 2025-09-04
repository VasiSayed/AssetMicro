from rest_framework.authentication import BaseAuthentication
from rest_framework import exceptions
from django.conf import settings
import jwt

from api.utils import ensure_alias_for_client 

class SimpleJWTUser:
    def __init__(self, user_id, username, permissions, tenant=None):
        self.id = user_id
        self.username = username
        self.permissions = permissions or {}
        self.tenant = tenant or {}
    @property
    def is_authenticated(self):
        return True

class ExternalJWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header.split(" ", 1)[1]

        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed("Token expired.")
        except jwt.InvalidTokenError:
            raise exceptions.AuthenticationFailed("Invalid token.")

        tenant_alias = payload.get("tenant_alias") or (payload.get("tenant") or {}).get("alias")
        client_username = payload.get("client_username") or (payload.get("tenant") or {}).get("client_username")
        client_id = payload.get("client_id") or (payload.get("tenant") or {}).get("client_id")

        if not tenant_alias:
            raise exceptions.AuthenticationFailed("Tenant alias missing in token.")

        username = payload.get("username") or (payload.get("tenant") or {}).get("username")
        if not username:
            raise exceptions.AuthenticationFailed("Username missing in token.")

        try:
            if client_username:
                ensure_alias_for_client(client_username=client_username)
            elif client_id:
                ensure_alias_for_client(client_id=int(client_id))
            elif tenant_alias.startswith("client_"):
                ensure_alias_for_client(client_id=int(tenant_alias.split("_", 1)[1]))
            else:
                raise RuntimeError("No client identifier present to register tenant DB.")
        except Exception as e:
            raise exceptions.AuthenticationFailed(f"Tenant DB setup failed: {e}")

        tenant_info = {
            "alias": tenant_alias,
            "client_username": client_username,
            "client_id": client_id,
            "user_id": payload.get("user_id"),
            "username": username,
        }

        user = SimpleJWTUser(
            user_id=payload.get("user_id"),
            username=username,
            permissions=payload.get("permissions", {}),
            tenant=tenant_info,
        )
        request.tenant_info = tenant_info
        return (user, token)
