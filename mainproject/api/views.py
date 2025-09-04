from __future__ import annotations
import json
import logging
from django.db.models import Q, Count, Sum, Min

import os
import traceback
from io import StringIO
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.db import connections, transaction, IntegrityError
from django.db.models import Q, Count, Sum
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoValidationError

from rest_framework import viewsets, status, filters, exceptions, generics, permissions
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.pagination import PageNumberPagination

from assetbackend.db_router import set_current_tenant

from .utils import ensure_alias_for_client
from .models import (
    AssetType, AssetCategory, AssetGroup, AssetSubgroup,
    Asset, AssetPurchaseInfo, AssetWarrantyAMC, AssetMeasure, AssetAttachment,
    Location,
)
from .serializers import (
    AssetSerializer, AssetPurchaseInfoSerializer, AssetWarrantyAMCSerializer,
    AssetMeasureSerializer, AssetAttachmentSerializer,
    AssetTypeSerializer, AssetCategorySerializer, AssetGroupSerializer, AssetSubgroupSerializer,
    LocationSerializer,AssetListSerializer,AssetWarrantyAMCCreateSerializer
)
from .pagination import StandardResultsSetPagination
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from django.db import transaction
from datetime import datetime
from django.utils import timezone
from django.db.models import Q
from rest_framework import generics, permissions, filters, exceptions
from django_filters.rest_framework import DjangoFilterBackend
from .serializers import AssetWarrantyAMCListSerializer
from rest_framework.decorators import action


logger = logging.getLogger("asset.api")
tax_logger = logging.getLogger("asset.taxonomy")
bundle_logger = logging.getLogger("asset.bundle")


# -------------------------------------------------------------------
# Tenant helpers
# -------------------------------------------------------------------
def _get_tenant_from_request(request):
    return getattr(request.user, "tenant", None) or getattr(request, "tenant_info", None)


def _ensure_alias_ready(tenant: dict) -> str:
    if not tenant or "alias" not in tenant:
        raise exceptions.AuthenticationFailed("Tenant alias missing in token.")
    alias = tenant["alias"]

    if alias not in settings.DATABASES:
        if tenant.get("client_username"):
            ensure_alias_for_client(client_username=tenant["client_username"])
        elif tenant.get("client_id"):
            ensure_alias_for_client(client_id=int(tenant["client_id"]))
        elif alias.startswith("client_"):
            ensure_alias_for_client(client_id=int(alias.split("_", 1)[1]))
        else:
            raise exceptions.APIException("Unable to resolve tenant DB.")
    return alias


class RouterTenantContextMixin(APIView):
    """
    Ensure DB router knows the tenant BEFORE any serializer/query runs.
    """
    def initial(self, request, *args, **kwargs):
        alias = _ensure_alias_ready(_get_tenant_from_request(request))
        set_current_tenant(alias)
        return super().initial(request, *args, **kwargs)

    def finalize_response(self, request, response, *args, **kwargs):
        try:
            return super().finalize_response(request, response, *args, **kwargs)
        finally:
            set_current_tenant(None)


class TenantSerializerContextMixin:
    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        alias = _ensure_alias_ready(_get_tenant_from_request(self.request))
        ctx["alias"] = alias
        ctx["request"] = self.request
        return ctx


class _TenantDBMixin:
    def _alias(self) -> str:
        return _ensure_alias_ready(_get_tenant_from_request(self.request))


# -------------------------------------------------------------------
# Register/Prepare DB for a client
# -------------------------------------------------------------------

class RegisterDBByClientAPIView(APIView):
    authentication_classes = []
    permission_classes = []
    parser_classes = [JSONParser]

    def post(self, request):
        client_id = (request.data or {}).get("client_id")
        client_username = (request.data or {}).get("client_username")

        if not client_id and not client_username:
            return Response({"detail": "Provide client_id or client_username."}, status=400)

        try:
            alias = ensure_alias_for_client(
                client_id=int(client_id) if str(client_id).isdigit() else None,
                client_username=client_username if not client_id else None,
            )

            if settings.DEBUG or str(os.getenv("ASSET_AUTO_MIGRATE", "0")) == "1":
                out = StringIO()
                call_command("migrate", "api", database=alias, interactive=False, verbosity=1, stdout=out)
                logger.info("Migrated app 'api' on %s\n%s", alias, out.getvalue())

            try:
                connections[alias].close()
            except Exception:
                pass

            return Response({"detail": "Alias ready", "alias": alias}, status=201)

        except Exception as e:
            logger.exception("RegisterDBByClient failed")
            return Response({"detail": str(e)}, status=400)


class LocationListCreateAPIView(RouterTenantContextMixin,
                                TenantSerializerContextMixin,
                                _TenantDBMixin,
                                generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LocationSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["site_id", "building_id", "floor_id", "unit_id"]
    search_fields = ["name"]
    ordering_fields = ["created_at", "site_id", "building_id", "floor_id", "unit_id", "name"]
    ordering = ["site_id", "building_id", "floor_id", "unit_id"]

    def get_queryset(self):
        alias = self._alias()
        return Location.objects.using(alias).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Location(created_by=getattr(request.user, "id", None), **s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)

    # 🔹 custom action to fetch by site_id
    @action(detail=False, methods=["get"], url_path="by-site/(?P<site_id>[^/.]+)")
    def by_site(self, request, site_id=None):
        alias = self._alias()
        qs = Location.objects.using(alias).filter(site_id=site_id)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class GlobalLocationListCreateAPIView(generics.ListCreateAPIView):
    """
    Global Location API – only requires authentication (not tenant alias).
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LocationSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["site_id", "building_id", "floor_id", "unit_id"]
    search_fields = ["name"]
    ordering_fields = ["created_at", "site_id", "building_id", "floor_id", "unit_id", "name"]
    ordering = ["site_id", "building_id", "floor_id", "unit_id"]

    def get_queryset(self):
        return Location.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=getattr(self.request.user, "id", None))


class GlobalLocationBySiteAPIView(
    RouterTenantContextMixin,          # sets router to tenant before any work
    TenantSerializerContextMixin,      # injects {"alias": <tenant_alias>, "request": request}
    _TenantDBMixin,                    # provides self._alias()
    generics.ListAPIView
):
    """
    GET /api/Global-locations/by-site/<site_id>/
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = LocationSerializer
    pagination_class = StandardResultsSetPagination

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name"]
    ordering_fields = ["created_at", "site_id", "building_id", "floor_id", "unit_id", "name"]
    ordering = ["site_id", "building_id", "floor_id", "unit_id"]

    def get_queryset(self):
        alias = self._alias()
        site_id = self.kwargs.get("site_id")
        return Location.objects.using(alias).filter(site_id=site_id)


# -------------------------------------------------------------------
# Asset Bundle Create (accepts same payload; maps site/build/floor/unit -> Location)
# -------------------------------------------------------------------

class AssetBundleCreateAPIView(RouterTenantContextMixin, APIView):
    """
    POST /api/assets/bundle/

    Payload keeps SAME structure you already use:

    {
      "Asset": {
         "asset_name": "...",
         ...
         // EITHER provide location id directly:
         "location": 123,

         // OR provide the previous fields (same as earlier):
         "site_id": 1,
         "building_id": 2,
         "floor_id": 3,
         "unit_id": 301,

         // the rest of Asset fields as before...
      },
      "AssetPurchaseInfo": {...},               # optional
      "AssetWarrantyAMC": {...},                # optional
      "AssetMeasure": { "consumption": [...], "non_consumption": [...] }  # or flat list with kind
      "AssetAttachment": [{...}, ...]           # optional (metadata-only here)
    }
    """
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    # ---------- helpers ----------
    @staticmethod
    def _dbg(msg, **kw):
        kv = " ".join(f"{k}={repr(v)}" for k, v in kw.items())
        line = f"🟨 AssetBundle | {msg} | {kv}"
        print(line)
        bundle_logger.debug(line)

    @staticmethod
    def _fail(detail, status=400, exc: Exception | None = None, **extra):
        payload = {"detail": detail}
        if exc is not None:
            payload.update({
                "error": str(exc),
                "type": exc.__class__.__name__,
                "trace": traceback.format_exc(),
            })
        if extra:
            payload.update(extra)
        if exc:
            bundle_logger.exception("%s | %s", detail, exc)
            print("🟥", detail, repr(exc))
        else:
            bundle_logger.error(detail)
            print("🟥", detail)
        return Response(payload, status=status)

    def _parse_json_field(self, value, field_name):
        if value is None or value == "":
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except Exception as exc:
            raise ValueError(f"'{field_name}' must be valid JSON") from exc

    def _normalize_measures(self, raw):
        if not raw:
            return []
        if isinstance(raw, dict):
            cons = raw.get("consumption") or raw.get("consumption_measures") or []
            nonc = raw.get("non_consumption") or raw.get("nonConsumption") or raw.get("non_consumption_measures") or []

            def tag(lst, kind):
                out = []
                for m in lst or []:
                    m = dict(m or {})
                    m.setdefault("kind", kind)
                    out.append(m)
                return out

            return tag(cons, "consumption") + tag(nonc, "non_consumption")
        if isinstance(raw, list):
            return [dict(m or {}) for m in raw]
        raise ValueError("'AssetMeasure' must be a list or an object with 'consumption' and 'non_consumption'.")

    # Create or resolve Location for the given Asset sub-payload (in-place mutates asset_data)
    def _inject_location_id(self, alias: str, asset_data: dict, uid: int | None):
        # If a direct location id is provided, trust it.
        loc_id = asset_data.get("location")
        if loc_id:
            return int(loc_id)

        site_id = asset_data.pop("site_id", None)
        b = asset_data.pop("building_id", None)
        f = asset_data.pop("floor_id", None)
        u = asset_data.pop("unit_id", None)

        # for backwards-compat: allow strings
        def to_int_or_none(v):
            try:
                return int(v) if v is not None and str(v).strip() != "" else None
            except Exception:
                return None

        site_id = to_int_or_none(site_id)
        b = to_int_or_none(b)
        f = to_int_or_none(f)
        u = to_int_or_none(u)

        if site_id is None or b is None or f is None or u is None:
            raise DRFValidationError({"location": "Provide either 'location' id OR (site_id, building_id, floor_id, unit_id)."})

        # get_or_create on tenant DB
        loc, _ = Location.objects.using(alias).get_or_create(
            site_id=site_id, building_id=b, floor_id=f, unit_id=u,
            defaults={"created_by": uid, "name": f"Site {site_id} / B{b} / F{f} / U{u}"}
        )
        return loc.id

    def post(self, request):
        # Permission check
        perms = getattr(request.user, "permissions", {}) or {}
        ap = perms.get("asset", {}) or {}
        if not (ap.get("add") or ap.get("all")):
            return self._fail("You do not have permission to add assets.", status=403, stage="permission")

        try:
            alias = _ensure_alias_ready(_get_tenant_from_request(request))
            self._dbg("Tenant alias ready", alias=alias)
            with connections[alias].cursor() as c:
                c.execute("select current_database(), inet_server_addr()::text, inet_server_port()")
                dbinfo = c.fetchone()
                self._dbg("Tenant DB connection ok", dbinfo=dbinfo)
        except Exception as db_err:
            return self._fail("Tenant DB connection failed", exc=db_err, stage="db_connect")

        # Parse payload
        try:
            asset_data = self._parse_json_field(request.data.get("Asset"), "Asset")
            if not asset_data:
                return self._fail("Missing 'Asset' object.", stage="parse")

            purchase_data = self._parse_json_field(request.data.get("AssetPurchaseInfo"), "AssetPurchaseInfo")
            warranty_data = self._parse_json_field(request.data.get("AssetWarrantyAMC"), "AssetWarrantyAMC")
            measures_raw = self._parse_json_field(request.data.get("AssetMeasure"), "AssetMeasure") or []
            measures_data = self._normalize_measures(measures_raw)
            attachments_data = self._parse_json_field(request.data.get("AssetAttachment"), "AssetAttachment") or []
            if attachments_data and not isinstance(attachments_data, list):
                return self._fail("'AssetAttachment' must be a list.", stage="parse")
        except ValueError as ve:
            return self._fail("Payload parsing failed", exc=ve, stage="parse")

        uid = getattr(request.user, "id", None)

        try:
            with transaction.atomic(using=alias):
                # Resolve/Inject location id
                location_id = self._inject_location_id(alias, asset_data, uid)
                asset_data["location"] = location_id

                # Validate & create Asset
                ctx = {"alias": alias, "request": request}
                self._dbg("Validating Asset serializer")
                a_ser = AssetSerializer(data=asset_data, context=ctx)
                a_ser.is_valid(raise_exception=True)

                asset = Asset(created_by=uid, **a_ser.validated_data)
                asset.full_clean(validate_unique=False)
                asset.save(using=alias)
                self._dbg("Asset saved", asset_id=asset.id)

                # Purchase
                if purchase_data:
                    pi_ser = AssetPurchaseInfoSerializer(data=purchase_data, context=ctx)
                    pi_ser.is_valid(raise_exception=True)
                    purchase_info = AssetPurchaseInfo(asset=asset, created_by=uid, **pi_ser.validated_data)
                    purchase_info.full_clean(validate_unique=False)
                    purchase_info.save(using=alias)

                # Warranty/AMC
                if warranty_data:
                    wa_ser = AssetWarrantyAMCSerializer(data=warranty_data, context=ctx)
                    wa_ser.is_valid(raise_exception=True)
                    warranty = AssetWarrantyAMC(asset=asset, created_by=uid, **wa_ser.validated_data)
                    warranty.full_clean(validate_unique=False)
                    warranty.save(using=alias)

                # Measures
                if measures_data:
                    objs = []
                    for m in measures_data:
                        mm = dict(m)
                        if "measure_type" not in mm:
                            k = (mm.get("kind") or "").strip()
                            if k == "consumption":
                                mm["measure_type"] = "consumption"
                            elif k in ("non_consumption", "nonConsumption"):
                                mm["measure_type"] = "nonConsumption"  # matches model choices
                            else:
                                raise DRFValidationError({"AssetMeasure": "Invalid measure kind/type. Use 'consumption' or 'non_consumption'."})
                        ms = AssetMeasureSerializer(data=mm, context=ctx)
                        ms.is_valid(raise_exception=True)
                        obj = AssetMeasure(asset=asset, created_by=uid, **ms.validated_data)
                        obj.full_clean(validate_unique=False)
                        objs.append(obj)
                    AssetMeasure.objects.using(alias).bulk_create(objs)

                # Attachments (metadata-only here)
                if attachments_data:
                    aobjs = []
                    for a in attachments_data:
                        aser = AssetAttachmentSerializer(data=a, context=ctx)
                        aser.is_valid(raise_exception=True)
                        obj = AssetAttachment(asset=asset, created_by=uid, **aser.validated_data)
                        obj.full_clean(validate_unique=False)
                        aobjs.append(obj)
                    AssetAttachment.objects.using(alias).bulk_create(aobjs)

                return Response({"detail": "Asset bundle created successfully.", "asset_id": asset.id}, status=201)

        except DRFValidationError as ve:
            return Response({"detail": "Serializer validation failed.", "errors": ve.detail, "stage": "serializer"}, status=400)
        except DjangoValidationError as ve:
            errors = getattr(ve, "message_dict", None) or {"non_field_errors": ve.messages}
            return Response({"detail": "Validation failed.", "errors": errors, "stage": "model_clean"}, status=400)
        except IntegrityError as ie:
            return self._fail("Database integrity error", exc=ie, stage="integrity")
        except Exception as e:
            return self._fail("Creation failed", exc=e, stage="unknown")


# -------------------------------------------------------------------
# Asset CRUD + analytics
# -------------------------------------------------------------------
class AssetViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = AssetSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # Filters now use Location FK
    filterset_fields = [
        "location", "location__site_id", "location__building_id", "location__floor_id", "location__unit_id",
        "asset_type", "category", "group", "subgroup", "department", "critical", "in_use"
    ]
    search_fields = ["asset_name", "brand", "model", "serial"]
    ordering_fields = ["created_at", "asset_name", "asset_type", "location"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Asset.objects.using(self._alias()).select_related("location").all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = Asset(created_by=getattr(request.user, "id", None), **s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        return Response(self.get_serializer(obj).data, status=201)

    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete(user_id=request.user.id)
        return Response(status=204)

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        alias = self._alias()
        try:
            qs = Asset.objects.using(alias)
            total_assets = qs.count()
            critical_assets = qs.filter(critical=True).count()
            assets_in_use = qs.filter(in_use=True).count()
            assets_under_maintenance = qs.filter(breakdown=True).count()

            asset_type_distribution = list(
                qs.values('asset_type').annotate(count=Count('id')).order_by('-count')
            )
            dept_distribution = list(
                qs.values('department').annotate(count=Count('id')).order_by('-count')
            )

            return Response({
                'total_assets': total_assets,
                'critical_assets': critical_assets,
                'assets_in_use': assets_in_use,
                'assets_under_maintenance': assets_under_maintenance,
                'asset_type_distribution': asset_type_distribution,
                'department_distribution': dept_distribution,
                'generated_at': timezone.now().isoformat(),
            })
        except Exception:
            logger.exception("dashboard_stats failed")
            return Response({'error': 'Failed to fetch dashboard statistics'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def by_location(self, request):
        """
        Filter by:
          - location_id
          - OR site_id (optionally with building_id/floor_id/unit_id)
        Returns grouped counts per (site, building, floor, unit).
        """
        alias = self._alias()
        try:
            qs = Asset.objects.using(alias).select_related("location")

            location_id = request.query_params.get('location_id')
            site_id = request.query_params.get('site_id')
            building_id = request.query_params.get('building_id')
            floor_id = request.query_params.get('floor_id')
            unit_id = request.query_params.get('unit_id')

            if location_id:
                qs = qs.filter(location_id=location_id)
            else:
                if site_id:
                    qs = qs.filter(location__site_id=site_id)
                if building_id:
                    qs = qs.filter(location__building_id=building_id)
                if floor_id:
                    qs = qs.filter(location__floor_id=floor_id)
                if unit_id:
                    qs = qs.filter(location__unit_id=unit_id)

            data = list(
                qs.values(
                    'location__site_id', 'location__building_id', 'location__floor_id', 'location__unit_id'
                ).annotate(
                    asset_count=Count('id'),
                    critical_count=Count('id', filter=Q(critical=True)),
                    in_use_count=Count('id', filter=Q(in_use=True)),
                ).order_by('location__site_id', 'location__building_id', 'location__floor_id', 'location__unit_id')
            )
            return Response(data)
        except Exception:
            logger.exception("by_location failed")
            return Response({'error': 'Failed to fetch location-based assets'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'])
    def asset_analytics(self, request):
        alias = self._alias()
        try:
            qs = Asset.objects.using(alias)
            with_purchase = qs.select_related('purchase_info').filter(
                purchase_info__purchase_date__isnull=False
            )

            totals = with_purchase.aggregate(total_cost=Sum('purchase_info__cost'))
            total_assets = qs.count()
            in_use = qs.filter(in_use=True).count()
            utilization_rate = (in_use / total_assets * 100) if total_assets else 0
            maintenance_assets = qs.filter(breakdown=True).count()

            return Response({
                'total_assets': total_assets,
                'avg_asset_cost': float(totals['total_cost'] or 0) / with_purchase.count() if with_purchase.exists() else 0,
                'utilization_rate': round(utilization_rate, 2),
                'maintenance_assets': maintenance_assets,
                'assets_with_purchase_info': with_purchase.count(),
            })
        except Exception:
            logger.exception("asset_analytics failed")
            return Response({'error': 'Failed to fetch analytics'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# -------------------------------------------------------------------
# Other ViewSets (unchanged except alias plumbing)
# -------------------------------------------------------------------
class AssetPurchaseInfoViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = AssetPurchaseInfoSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['purchase_date', 'vendor_name']
    search_fields = ['po_number', 'vendor_name']

    def get_queryset(self):
        return AssetPurchaseInfo.objects.using(self._alias()).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = AssetPurchaseInfo(created_by=request.user.id, **s.validated_data)
            obj.full_clean()
            obj.save(using=alias)
        return Response(self.get_serializer(obj).data, status=201)

    @action(detail=False, methods=['get'])
    def purchase_summary(self, request):
        alias = self._alias()
        try:
            qs = AssetPurchaseInfo.objects.using(alias)
            total_cost = qs.aggregate(total=Sum('cost'))['total'] or 0
            vendor_summary = list(
                qs.values('vendor_name').annotate(
                    total_cost=Sum('cost'),
                    asset_count=Count('asset')
                ).order_by('-total_cost')
            )
            return Response({'total_purchase_cost': total_cost, 'vendor_summary': vendor_summary})
        except Exception:
            logger.exception("purchase_summary failed")
            return Response({'error': 'Failed to fetch purchase summary'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AssetWarrantyAMCViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = AssetWarrantyAMCSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['warranty_type', 'amc_type', 'under_warranty']
    search_fields = ['amc_provider']

    def get_queryset(self):
        return AssetWarrantyAMC.objects.using(self._alias()).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = AssetWarrantyAMC(created_by=request.user.id, **s.validated_data)
            obj.full_clean()
            obj.save(using=alias)
        return Response(self.get_serializer(obj).data, status=201)

    @action(detail=False, methods=['get'])
    def expiring_soon(self, request):
        alias = self._alias()
        try:
            days_ahead = int(request.query_params.get('days', 30))
            future_date = timezone.now().date() + timedelta(days=days_ahead)

            qs = AssetWarrantyAMC.objects.using(alias)
            exp_warranty = qs.filter(
                warranty_end__lte=future_date, warranty_end__gte=timezone.now().date()
            ).select_related('asset')
            exp_amc = qs.filter(
                amc_end__lte=future_date, amc_end__gte=timezone.now().date()
            ).select_related('asset')

            return Response({
                'expiring_warranty': AssetWarrantyAMCSerializer(exp_warranty, many=True).data,
                'expiring_amc': AssetWarrantyAMCSerializer(exp_amc, many=True).data,
            })
        except Exception:
            logger.exception("expiring_soon failed")
            return Response({'error': 'Failed to fetch expiring warranties/AMCs'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AssetMeasureViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = AssetMeasureSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['measure_type', 'unit_type']
    search_fields = ['name']

    def get_queryset(self):
        return AssetMeasure.objects.using(self._alias()).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = AssetMeasure(created_by=request.user.id, **s.validated_data)
            obj.full_clean()
            obj.save(using=alias)
        return Response(self.get_serializer(obj).data, status=201)

    @action(detail=False, methods=['get'])
    def critical_measures(self, request):
        alias = self._alias()
        try:
            qs = AssetMeasure.objects.using(alias).filter(
                Q(alert_below__isnull=False) | Q(alert_above__isnull=False)
            ).select_related('asset')
            return Response(AssetMeasureSerializer(qs, many=True).data)
        except Exception:
            logger.exception("critical_measures failed")
            return Response({'error': 'Failed to fetch critical measures'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AssetAttachmentViewSet(RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet):
    serializer_class = AssetAttachmentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['attachment_type']
    search_fields = ['attachment_type']

    def get_queryset(self):
        return AssetAttachment.objects.using(self._alias()).all()

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = AssetAttachment(created_by=request.user.id, **s.validated_data)
            obj.full_clean()
            obj.save(using=alias)
        return Response(self.get_serializer(obj).data, status=201)


# -------------------------------------------------------------------
# Taxonomy list/create (unchanged, alias-safe)
# -------------------------------------------------------------------
class AssetTypeListCreateAPIView(RouterTenantContextMixin,
                                 TenantSerializerContextMixin,
                                 _TenantDBMixin,
                                 generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AssetTypeSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "code", "description"]
    ordering_fields = ["created_at", "name", "code"]
    ordering = ["name"]

    def get_queryset(self):
        alias = self._alias()
        qs = AssetType.objects.using(alias).all().order_by("name")
        site_id = self.request.query_params.get("site_id")
        if site_id:
            qs = qs.filter(site_id=site_id)
        return qs

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = AssetType(created_by=getattr(request.user, "id", None), **s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)


class AssetCategoryListCreateAPIView(RouterTenantContextMixin,
                                     TenantSerializerContextMixin,
                                     _TenantDBMixin,
                                     generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AssetCategorySerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["asset_type"]
    search_fields = ["name", "code", "description"]
    ordering_fields = ["created_at", "name", "code"]
    ordering = ["name"]

    def get_queryset(self):
        alias = self._alias()
        qs = AssetCategory.objects.using(alias).all()
        at = self.request.query_params.get("asset_type_id")
        if at:
            qs = qs.filter(asset_type_id=at)
        return qs

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = AssetCategory(created_by=getattr(request.user, "id", None), **s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)


class AssetGroupListCreateAPIView(RouterTenantContextMixin,
                                  TenantSerializerContextMixin,
                                  _TenantDBMixin,
                                  generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AssetGroupSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["category"]
    search_fields = ["name", "code", "description"]
    ordering_fields = ["created_at", "name", "code"]
    ordering = ["name"]

    def get_queryset(self):
        alias = self._alias()
        qs = AssetGroup.objects.using(alias).all()
        cat = self.request.query_params.get("category_id")
        if cat:
            qs = qs.filter(category_id=cat)
        return qs

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = AssetGroup(created_by=getattr(request.user, "id", None), **s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)


class AssetSubgroupListCreateAPIView(RouterTenantContextMixin,
                                     TenantSerializerContextMixin,
                                     _TenantDBMixin,
                                     generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AssetSubgroupSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["group"]
    search_fields = ["name", "code", "description"]
    ordering_fields = ["created_at", "name", "code"]
    ordering = ["name"]

    def get_queryset(self):
        alias = self._alias()
        qs = AssetSubgroup.objects.using(alias).all()
        gid = self.request.query_params.get("group_id")
        if gid:
            qs = qs.filter(group_id=gid)
        return qs

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = AssetSubgroup(created_by=getattr(request.user, "id", None), **s.validated_data)
            obj.full_clean(validate_unique=False)
            obj.save(using=alias)
        s.instance = obj
        return Response(s.data, status=status.HTTP_201_CREATED)


class AssetsByLocationAPIView(
    RouterTenantContextMixin,       # sets router to the tenant early
    TenantSerializerContextMixin,   # injects {"alias": ..., "request": ...}
    _TenantDBMixin,                 # gives self._alias()
    generics.ListAPIView
):
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    # same search & ordering keys you already use
    search_fields = ["asset_name", "serial", "model", "brand"]
    ordering_fields = ["created_at", "asset_name", "id"]
    ordering = ["-created_at"]

    # switch serializer with ?summary=true to reuse your lightweight list serializer
    def get_serializer_class(self):
        summary = (self.request.query_params.get("summary") or "").lower()
        return AssetListSerializer if summary in {"1", "true", "yes"} else AssetSerializer

    def get_queryset(self):
        alias = self._alias()
        location_id = self.kwargs.get("location_id")

        try:
            location_id = int(str(location_id).strip().rstrip("/"))
        except (TypeError, ValueError):
            raise exceptions.ValidationError({"location_id": "Must be an integer."})

        return (
            Asset.objects.using(alias)
            .select_related("location", "asset_type", "category", "group", "subgroup")
            .filter(is_deleted=False, location_id=location_id)
        )


class AssetListAPIView(APIView):
    """
    GET /api/all-assets/

    Query params:
      site_id      (int)
      asset_type   (int)
      category     (int)
      group        (int)
      subgroup     (int)
      search       (str)
      ordering     (str)
      page         (int)
      page_size    (int)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = getattr(request.user, "tenant", None)

        # support dict- or object-like user.tenant
        if isinstance(tenant, dict):
            client_username = tenant.get("client_username")
            alias_hint = tenant.get("alias")
        else:
            client_username = getattr(tenant, "client_username", None)
            alias_hint = getattr(tenant, "alias", None)

        if not client_username and alias_hint:
            # allow direct alias from token if provided (no network call)
            alias = alias_hint
        elif client_username:
            # 👇 username route only — will log: /api/master/user-dbs/by-username/<client_username>
            alias = ensure_alias_for_client(client_username=client_username)
        else:
            return Response(
                {"detail": "Tenant info missing on user; expected client_username."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        try:
            with connections[alias].cursor() as c:
                c.execute("SELECT 1")
        except Exception as e:
            return Response(
                {"detail": "Tenant DB resolution failed.", "error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ---- Queryset on tenant DB ----
        qs = (
            Asset.objects.using(alias)
            .select_related("location", "asset_type", "category", "group", "subgroup")
            .filter(is_deleted=False)
        )

        # ---- Filters ----
        def to_int(v):
            try:
                # tolerate trailing slash like site_id=1/
                s = (v or "").strip().rstrip("/")
                return int(s) if s else None
            except Exception:
                return None

        site_id  = to_int(request.query_params.get("site_id"))
        atype_id = to_int(request.query_params.get("asset_type") or request.query_params.get("assettype"))
        cat_id   = to_int(request.query_params.get("category") or request.query_params.get("asset_category"))
        grp_id   = to_int(request.query_params.get("group") or request.query_params.get("asset_group"))
        sgrp_id  = to_int(request.query_params.get("subgroup") or request.query_params.get("asset_subgroup"))
        search   = (request.query_params.get("search") or "").strip()
        ordering = (request.query_params.get("ordering") or "-created_at").strip()

        if site_id is not None:
            qs = qs.filter(location__site_id=site_id)
        if atype_id is not None:
            qs = qs.filter(asset_type_id=atype_id)
        if cat_id is not None:
            qs = qs.filter(category_id=cat_id)
        if grp_id is not None:
            qs = qs.filter(group_id=grp_id)
        if sgrp_id is not None:
            qs = qs.filter(subgroup_id=sgrp_id)

        if search:
            qs = qs.filter(
                Q(asset_name__icontains=search) |
                Q(serial__icontains=search) |
                Q(model__icontains=search) |
                Q(brand__icontains=search)
            )

        allowed = {"created_at", "asset_name", "id"}
        if ordering.lstrip("-") not in allowed:
            ordering = "-created_at"
        qs = qs.order_by(ordering)

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = AssetListSerializer(page, many=True).data
        return paginator.get_paginated_response(data)


class AssetAMCCreateAPIView(
    RouterTenantContextMixin,
    TenantSerializerContextMixin,
    _TenantDBMixin,
    APIView
):
    """
    Supports either:
      - POST /api/assets/<asset_id>/amc/
      - POST /api/Create-AMC-inAsset/   (with 'asset' in request data)
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, asset_id: int = None):
        print("---- [AMC Create Debug] Incoming request ----")
        print("asset_id (from URL):", asset_id)
        print("request.data:", dict(request.data))

        # ---- permission check ----
        perms = getattr(request.user, "permissions", {}) or {}
        ap = perms.get("asset", {}) or {}
        print("User perms (asset):", ap)

        if not (ap.get("add") or ap.get("all")):
            print("❌ Permission denied")
            return Response(
                {"detail": "You do not have permission to add assets."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ---- resolve asset_id: from URL or body ----
        if asset_id is None:
            body_asset = request.data.get("asset")
            print("asset_id not provided in URL, got from body:", body_asset)
            try:
                asset_id = int(body_asset)
            except (TypeError, ValueError):
                print("❌ Invalid asset id in body:", body_asset)
                return Response(
                    {"detail": "Missing or invalid 'asset' in request body."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        alias = self._alias()
        print("Using DB alias:", alias)

        # ---- ensure asset exists in tenant DB ----
        asset = Asset.objects.using(alias).filter(pk=asset_id).first()
        if not asset:
            print(f"❌ Asset {asset_id} not found in alias {alias}")
            return Response({"detail": f"Asset {asset_id} not found."}, status=404)

        print(f"✅ Asset {asset_id} found:", asset.asset_name)

        # OneToOne: block duplicate AMC
        if getattr(asset, "warranty_amc_id", None):
            print(f"❌ AMC already exists for asset {asset_id}")
            return Response({"detail": "AMC already exists for this asset."}, status=400)

        # ---- build payload for serializer ----
        data = request.data.copy()
        data["asset"] = asset.id  # ensure serializer sees it
        print("Serializer input data:", data)

        s = AssetWarrantyAMCCreateSerializer(
            data=data, context={"request": request, "alias": alias}
        )
        if not s.is_valid():
            print("❌ Serializer validation failed:", s.errors)
            return Response(
                {"detail": "Serializer validation failed.", "errors": s.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        print("✅ Serializer valid")

        try:
            with transaction.atomic(using=alias):
                obj = AssetWarrantyAMC(
                    **s.validated_data, created_by=getattr(request.user, "id", None)
                )
                obj.full_clean(validate_unique=False)
                obj.save(using=alias)
                print("✅ AMC object created:", obj.id)
        except Exception as e:
            print("❌ Exception while saving AMC:", str(e))
            raise

        out = AssetWarrantyAMCSerializer(
            obj, context={"request": request, "alias": alias}
        ).data
        print("✅ AMC creation success. Response:", out)
        return Response(out, status=201)


class AMCStatusListAPIView(
    RouterTenantContextMixin,      
    TenantSerializerContextMixin,     
     _TenantDBMixin,        
    generics.ListAPIView
):
    """
    GET /api/asset/status/

    Returns either AMC rows or distinct Assets filtered by site and optional criteria.

    Auth:
      - Authorization: Bearer <JWT>

    Required:
      - site_id (int): Site to filter on.

    Optional core filters:
      - status: one of ["expired", "active", "all"]   (default: "expired")
          * expired → (amc_end < date) OR (warranty_end < date), depending on "kind"
          * active  → (start <= date <= end) OR (start is null and end >= date)
          * all     → no date-based status filter
      - kind: one of ["amc", "warranty", "both"]      (default: "amc")
          * amc      → only AMC dates are considered
          * warranty → only warranty dates are considered
          * both     → AMC OR warranty matches are included
      - as: one of ["amcs", "assets"]                 (default: "amcs")
          * amcs   → list of AMC rows (AssetWarrantyAMCListSerializer)
          * assets → distinct assets (AssetListSerializer)
      - date: YYYY-MM-DD                              (default: today in server TZ)
          * Pivot date used for "expired"/"active" evaluation

    Optional extra filters (any combination; all are AND-ed):
      - building_id (int)
      - floor_id    (int)
      - unit_id     (int)
      - asset_type  (int)       # asset_type id
      - category    (int)       # category id
      - group       (int)       # group id
      - subgroup    (int)       # subgroup id
      - vendor      (str)       # alias of amc_provider (icontains)
      - amc_type    (str)       # exact match
      - warranty_type (str)     # exact match
      - under_warranty: one of ["true","false","1","0","yes","no"]

    Search / ordering / pagination:
      - search: free text on ["asset__asset_name", "amc_provider"]
      - ordering: one of ["amc_end","amc_start","warranty_end","warranty_start","created_at"]
                  (prefix with "-" for descending; default: "amc_end")
      - page, page_size: standard pagination (default page size: see StandardResultsSetPagination)

    Response shape:
      - as=amcs   → AssetWarrantyAMCListSerializer with:
          id, asset_id, asset_name,
          site_id/building_id/floor_id/unit_id,
          site_name/building_name/floor_name/unit_name (resolved internally; null if lookup fails),
          amc_provider, amc_type, amc_start, amc_end,
          warranty_type, warranty_start, warranty_end,
          under_warranty, amc_terms, created_at
      - as=assets → AssetListSerializer with:
          id, asset_name, brand, model, serial,
          site_id/building_id/floor_id/unit_id + their *_name fields,
          asset_type_id/name, category_id/name, group_id/name, subgroup_id/name,
          department, critical, asset_reading, compliance, breakdown, in_use, created_at

    Examples:
      # Core
      GET /api/asset/status/?site_id=1
      GET /api/asset/status/?site_id=1&status=active&kind=amc
      GET /api/asset/status/?site_id=1&status=expired&kind=warranty
      GET /api/asset/status/?site_id=1&status=expired&kind=both

      # Distinct assets instead of AMC rows
      GET /api/asset/status/?site_id=1&status=expired&kind=amc&as=assets

      # Custom pivot date
      GET /api/asset/status/?site_id=1&status=active&kind=both&date=2025-08-01

      # Location filters
      GET /api/asset/status/?site_id=1&building_id=12
      GET /api/asset/status/?site_id=1&floor_id=5
      GET /api/asset/status/?site_id=1&unit_id=301

      # Taxonomy filters
      GET /api/asset/status/?site_id=1&asset_type=4
      GET /api/asset/status/?site_id=1&category=10
      GET /api/asset/status/?site_id=1&group=22
      GET /api/asset/status/?site_id=1&subgroup=35

      # Vendor / type / flags
      GET /api/asset/status/?site_id=1&search=ACME
      GET /api/asset/status/?site_id=1&vendor=ACME
      GET /api/asset/status/?site_id=1&amc_type=Comprehensive
      GET /api/asset/status/?site_id=1&warranty_type=OEM
      GET /api/asset/status/?site_id=1&under_warranty=true

      # Ordering & pagination
      GET /api/asset/status/?site_id=1&ordering=-created_at
      GET /api/asset/status/?site_id=1&page=2&page_size=50

      # Combo
      GET /api/asset/status/?site_id=1&status=expired&kind=both&as=assets&building_id=12&search=ACME&ordering=-created_at&page=1&page_size=25
    """
    permission_classes = [permissions.IsAuthenticated]
    pagination_class   = StandardResultsSetPagination
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    search_fields   = ["asset__asset_name", "amc_provider"]
    ordering_fields = ["amc_end", "amc_start", "warranty_end", "warranty_start", "created_at"]
    ordering        = ["amc_end"]

    def get_serializer_class(self):
        # If caller wants DISTINCT ASSETS back
        as_mode = (self.request.query_params.get("as") or "amcs").lower()
        if as_mode in {"asset", "assets"}:
            return AssetListSerializer
        return AssetWarrantyAMCListSerializer

    def _pivot_date(self):
        s = self.request.query_params.get("date")
        if not s:
            return timezone.now().date()
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            raise exceptions.ValidationError({"date": "Use YYYY-MM-DD."})

    def get_queryset(self):
        alias = self._alias()

        # ---- required site_id ----
        site_id = self.request.query_params.get("site_id")
        if site_id is None:
            raise exceptions.ValidationError({"site_id": "This parameter is required."})
        try:
            site_id = int(str(site_id).strip().rstrip("/"))
        except (TypeError, ValueError):
            raise exceptions.ValidationError({"site_id": "Must be an integer."})

        status_param = (self.request.query_params.get("status") or "expired").lower()
        kind         = (self.request.query_params.get("kind") or "amc").lower()
        as_mode      = (self.request.query_params.get("as") or "amcs").lower()
        ref_date     = self._pivot_date()

        # Base: AMC rows in this site
        amc_qs = (
            AssetWarrantyAMC.objects.using(alias)
            .select_related("asset", "asset__location")
            .filter(asset__location__site_id=site_id)
        )

        # Build conditions
        conds = []
        if kind in {"amc", "both"}:
            if status_param == "expired":
                conds.append(Q(amc_end__isnull=False, amc_end__lt=ref_date))
            elif status_param == "active":
                # active if today between start..end (or start null but end in future)
                conds.append(
                    (Q(amc_start__isnull=True) & Q(amc_end__gte=ref_date))
                    | (Q(amc_start__lte=ref_date) & Q(amc_end__gte=ref_date))
                )
            elif status_param == "all":
                pass

        if kind in {"warranty", "both"}:
            if status_param == "expired":
                conds.append(Q(warranty_end__isnull=False, warranty_end__lt=ref_date))
            elif status_param == "active":
                conds.append(
                    (Q(warranty_start__isnull=True) & Q(warranty_end__gte=ref_date))
                    | (Q(warranty_start__lte=ref_date) & Q(warranty_end__gte=ref_date))
                )
            elif status_param == "all":
                pass

        if status_param != "all" and conds:
            q_or = conds[0]
            for c in conds[1:]:
                q_or = q_or | c
            amc_qs = amc_qs.filter(q_or)

        # Return AMC rows or distinct ASSETS
        if as_mode in {"asset", "assets"}:
            asset_ids = amc_qs.values_list("asset_id", flat=True).distinct()
            return (
                Asset.objects.using(alias)
                .select_related("location", "asset_type", "category", "group", "subgroup")
                .filter(is_deleted=False, id__in=asset_ids)
            )
        return amc_qs


# views.py

class AMCDueSoonListAPIView(
    RouterTenantContextMixin,
    TenantSerializerContextMixin,
    _TenantDBMixin,
    generics.ListAPIView
):
    """
    GET /api/asset/amc-due/?site_id=<int>&days=<int>&as=<assets|amcs>&search=<q>&ordering=<...>

    Purpose:
      List assets (default) whose AMC will expire within the next N days (default 90),
      not including already-expired ones. Optionally, return AMC rows instead.

    Auth:
      - Authorization: Bearer <JWT>

    Required:
      - site_id (int)

    Optional:
      - days: integer window from today (default: 90)
      - as:   "assets" (default) or "amcs"
      - search: free text on asset name / vendor (amc_provider)
      - ordering:
          * if as=amcs: "amc_end", "amc_start", "created_at" (prefix "-" for desc)
          * if as=assets: "next_amc_end" (annotated), "created_at" (default: "next_amc_end")
      - page, page_size: pagination (StandardResultsSetPagination)

    Extra filters (ANDed, all optional):
      - building_id, floor_id, unit_id (ints)
      - asset_type, category, group, subgroup (ints)
      - vendor (icontains amc_provider), amc_type (exact), under_warranty (true/false/1/0/yes/no)

    ----------------------------------------------------------------------
    3) How to use (examples)

    Defaults: next 90 days, return assets, ordered by soonest.

    AMC due within 90 days (assets)
      GET /api/asset/amc-due/?site_id=1

    Custom window (e.g., 30 days)
      GET /api/asset/amc-due/?site_id=1&days=30

    Return AMC rows instead of assets
      GET /api/asset/amc-due/?site_id=1&days=90&as=amcs

    Search by asset name or vendor
      GET /api/asset/amc-due/?site_id=1&search=ACME

    Filter by location or taxonomy
      GET /api/asset/amc-due/?site_id=1&building_id=12&asset_type=4&category=10

    Only those marked under_warranty
      GET /api/asset/amc-due/?site_id=1&under_warranty=true

    Ordering
      Assets (default next_amc_end):
        GET /api/asset/amc-due/?site_id=1&ordering=-next_amc_end

      AMCs (default amc_end):
        GET /api/asset/amc-due/?site_id=1&as=amcs&ordering=-amc_end

    Pagination
      GET /api/asset/amc-due/?site_id=1&page=2&page_size=50
    ----------------------------------------------------------------------
    """

    permission_classes = [permissions.IsAuthenticated]
    pagination_class   = StandardResultsSetPagination
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields      = ["asset__asset_name", "amc_provider"]  # applies when returning AMCs

    # Ordering allowed for DRF's OrderingFilter (we also enforce in code)
    ordering_fields_amcs   = ["amc_end", "amc_start", "created_at"]
    ordering_fields_assets = ["next_amc_end", "created_at"]

    def get_serializer_class(self):
        as_mode = (self.request.query_params.get("as") or "assets").lower()
        if as_mode in {"amc", "amcs"}:
            return AssetWarrantyAMCListSerializer
        return AssetListSerializer

    def _to_int(self, v):
        try:
            s = (v or "").strip().rstrip("/")
            return int(s) if s else None
        except Exception:
            return None

    def get_queryset(self):
        alias = self._alias()

        # --- required site_id ---
        site_id = self._to_int(self.request.query_params.get("site_id"))
        if site_id is None:
            raise exceptions.ValidationError({"site_id": "This parameter is required and must be an integer."})

        # --- window (days) ---
        days_raw = self.request.query_params.get("days") or "90"
        try:
            days = max(1, int(days_raw))
        except ValueError:
            raise exceptions.ValidationError({"days": "Must be an integer (>=1)."})

        today = timezone.now().date()
        until = today + timedelta(days=days)

        # Base AMC queryset for this window: amc_end within [today, until]
        amc_qs = (
            AssetWarrantyAMC.objects.using(alias)
            .select_related("asset", "asset__location")
            .filter(
                asset__location__site_id=site_id,
                amc_end__isnull=False,
                amc_end__gte=today,
                amc_end__lte=until,
            )
        )

        # ---- optional filters ----
        building_id = self._to_int(self.request.query_params.get("building_id"))
        floor_id    = self._to_int(self.request.query_params.get("floor_id"))
        unit_id     = self._to_int(self.request.query_params.get("unit_id"))

        asset_type  = self._to_int(self.request.query_params.get("asset_type"))
        category    = self._to_int(self.request.query_params.get("category"))
        group       = self._to_int(self.request.query_params.get("group"))
        subgroup    = self._to_int(self.request.query_params.get("subgroup"))

        vendor      = (self.request.query_params.get("vendor") or "").strip()
        amc_type    = (self.request.query_params.get("amc_type") or "").strip()

        uw_raw      = (self.request.query_params.get("under_warranty") or "").strip().lower()
        under_warranty = True if uw_raw in {"1","true","yes"} else False if uw_raw in {"0","false","no"} else None

        if building_id is not None:
            amc_qs = amc_qs.filter(asset__location__building_id=building_id)
        if floor_id is not None:
            amc_qs = amc_qs.filter(asset__location__floor_id=floor_id)
        if unit_id is not None:
            amc_qs = amc_qs.filter(asset__location__unit_id=unit_id)

        if asset_type is not None:
            amc_qs = amc_qs.filter(asset__asset_type_id=asset_type)
        if category is not None:
            amc_qs = amc_qs.filter(asset__category_id=category)
        if group is not None:
            amc_qs = amc_qs.filter(asset__group_id=group)
        if subgroup is not None:
            amc_qs = amc_qs.filter(asset__subgroup_id=subgroup)

        if vendor:
            amc_qs = amc_qs.filter(amc_provider__icontains=vendor)
        if amc_type:
            amc_qs = amc_qs.filter(amc_type=amc_type)
        if under_warranty is not None:
            amc_qs = amc_qs.filter(under_warranty=under_warranty)

        # --- return shape ---
        as_mode  = (self.request.query_params.get("as") or "assets").lower()
        ordering = (self.request.query_params.get("ordering") or "").strip()

        if as_mode in {"amc", "amcs"}:
            # Allow only AMC ordering fields
            if ordering.lstrip("-") not in self.ordering_fields_amcs:
                ordering = "amc_end"
            return amc_qs.order_by(ordering)

        # DISTINCT assets with an AMC due within window; annotate next_amc_end for ordering
        asset_ids = amc_qs.values_list("asset_id", flat=True).distinct()
        assets_qs = (
            Asset.objects.using(alias)
            .select_related("location", "asset_type", "category", "group", "subgroup")
            .filter(is_deleted=False, id__in=asset_ids)
            .annotate(next_amc_end=Min("warranty_amc__amc_end"))
        )

        # Only allow the supported ordering fields for assets here
        if ordering.lstrip("-") not in self.ordering_fields_assets:
            ordering = "next_amc_end"
        return assets_qs.order_by(ordering)


# views.py
from .models import AssetMeasureReading, AssetMeasure
from .serializers import AssetMeasureReadingSerializer

class AssetMeasureReadingViewSet(
    RouterTenantContextMixin, TenantSerializerContextMixin, _TenantDBMixin, viewsets.ModelViewSet
):
    serializer_class = AssetMeasureReadingSerializer
    filter_backends  = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["measure", "measure__asset"]   # filter by measure or by asset
    search_fields    = ["measure__name"]
    ordering_fields  = ["created_at", "reading_value"]
    ordering         = ["-created_at"]

    def get_queryset(self):
        alias = self._alias()
        return (
            AssetMeasureReading.objects.using(alias)
            .select_related("measure", "measure__asset")
            .all()
        )

    def create(self, request, *args, **kwargs):
        alias = self._alias()
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic(using=alias):
            obj = AssetMeasureReading(created_by=getattr(request.user, "id", None), **s.validated_data)
            obj.full_clean()                  # triggers model.clean() min/max checks too
            obj.save(using=alias)
        return Response(self.get_serializer(obj).data, status=201)

    @action(detail=False, methods=["get"], url_path="latest")
    def latest(self, request):
        """
        GET /api/measure-readings/latest/?measure=<id>
        Returns the latest reading for a measure.
        """
        alias = self._alias()
        try:
            measure_id = int(request.query_params.get("measure"))
        except (TypeError, ValueError):
            return Response({"detail": "measure is required (int)."}, status=400)

        obj = (
            AssetMeasureReading.objects.using(alias)
            .filter(measure_id=measure_id)
            .order_by("-created_at")
            .select_related("measure", "measure__asset")
            .first()
        )
        if not obj:
            return Response({"detail": "No readings found."}, status=404)
        return Response(self.get_serializer(obj).data, status=200)
