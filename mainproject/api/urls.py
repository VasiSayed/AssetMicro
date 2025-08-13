from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from .views import RegisterDBAPIView
urlpatterns = [
    # path('user-dbs/', UserDatabaseCreateView.as_view(), name='user-database-create'),
    path('register_db/', RegisterDBAPIView.as_view()),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)