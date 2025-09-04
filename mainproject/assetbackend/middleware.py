from django.utils.deprecation import MiddlewareMixin
from .db_router import set_current_tenant

class TenantMiddleware(MiddlewareMixin):
    def process_request(self, request):
        set_current_tenant(request.headers.get("X-Tenant"))
    def process_response(self, request, response):
        set_current_tenant(None)
        return response
    
