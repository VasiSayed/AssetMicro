from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    AssetViewSet, AssetBundleCreateAPIView,
    AssetPurchaseInfoViewSet, AssetWarrantyAMCViewSet,
    AssetMeasureViewSet, AssetAttachmentViewSet,
    LocationListCreateAPIView,
    AssetTypeListCreateAPIView, AssetCategoryListCreateAPIView,
    AssetGroupListCreateAPIView, AssetSubgroupListCreateAPIView,
    RegisterDBByClientAPIView,GlobalLocationListCreateAPIView,AssetListAPIView,
    GlobalLocationBySiteAPIView,AssetsByLocationAPIView,AssetAMCCreateAPIView,AMCStatusListAPIView,AMCDueSoonListAPIView
    ,AssetMeasureReadingViewSet
)
from .views_autofill import AssetAutofillView

router = DefaultRouter()
router.register(r'assets', AssetViewSet, basename='asset')
router.register(r'purchase-info', AssetPurchaseInfoViewSet, basename='purchase-info')
router.register(r'warranty-amc', AssetWarrantyAMCViewSet, basename='warranty-amc')
router.register(r'measures', AssetMeasureViewSet, basename='measures')
router.register(r'attachments', AssetAttachmentViewSet, basename='attachments')
router.register(r"measure-readings", AssetMeasureReadingViewSet, basename="measure-reading")

urlpatterns = [
    path('register-db/', RegisterDBByClientAPIView.as_view()),

    
    path("api/assets/autofill/", AssetAutofillView.as_view(), name="asset-autofill"),

    path("all-assets/", AssetListAPIView.as_view(), name="asset-list"),
    path('Bulk-Asset-Create/', AssetBundleCreateAPIView.as_view()),
    path('locations/', LocationListCreateAPIView.as_view()),
    path('Global-locations', GlobalLocationListCreateAPIView.as_view()),
    path('asset-types/', AssetTypeListCreateAPIView.as_view()),
    path('asset-categories/', AssetCategoryListCreateAPIView.as_view()),
    path('asset-groups/', AssetGroupListCreateAPIView.as_view()),
    path('asset-subgroups/', AssetSubgroupListCreateAPIView.as_view()),

    path("Global-locations/by-site/<int:site_id>/", GlobalLocationBySiteAPIView.as_view(), name="global-location-by-site"),
    path("assets/by-location/<int:location_id>/", AssetsByLocationAPIView.as_view()),
    path('Create-AMC-inAsset/',AssetAMCCreateAPIView.as_view()),
    path('asset/status/',AMCStatusListAPIView.as_view()),
    path("asset/amc-due/", AMCDueSoonListAPIView.as_view(), name="amc-due"),
    path('', include(router.urls)),
]
