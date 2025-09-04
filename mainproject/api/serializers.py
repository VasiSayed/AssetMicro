from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator, UniqueValidator
from .models import (
    Asset, AssetPurchaseInfo, AssetWarrantyAMC, AssetMeasure, AssetAttachment,
    AssetType, AssetCategory, AssetGroup, AssetSubgroup, Location,AssetMeasureReading
)
from .utils import resolve_name  



class AliasContextMixin:
    @property
    def alias(self) -> str:
        alias = self.context.get("alias")
        if not alias:
            raise RuntimeError("Serializer context missing 'alias'.")
        return alias


class AliasModelSerializer(AliasContextMixin, serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Serializer-level unique validators
        for v in self.validators:
            if isinstance(v, (UniqueTogetherValidator, UniqueValidator)) and getattr(v, "queryset", None) is not None:
                v.queryset = v.queryset.using(self.alias)

        # Field-level unique validators
        for field in self.fields.values():
            for val in getattr(field, "validators", []):
                if isinstance(val, UniqueValidator) and getattr(val, "queryset", None) is not None:
                    val.queryset = val.queryset.using(self.alias)


class LocationSerializer(AliasModelSerializer):
    site_id = serializers.IntegerField(required=True)

    class Meta:
        model = Location
        fields = ["id", "site_id", "building_id", "floor_id", "unit_id", "name", "created_at"]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        user = getattr(self.context.get("request"), "user", None)
        obj = Location(created_by=getattr(user, "id", None), **validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj


# ---------- Asset hierarchy ----------
class AssetTypeSerializer(AliasModelSerializer):
    site_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = AssetType
        fields = ["id", "site_id", "name", "code", "description", "created_at"]
        read_only_fields = ["id", "code", "created_at"]

    def create(self, validated_data):
        user = getattr(self.context.get("request"), "user", None)
        obj = AssetType(created_by=getattr(user, "id", None), **validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj


class AssetCategorySerializer(AliasModelSerializer):
    asset_type = serializers.PrimaryKeyRelatedField(queryset=AssetType.objects.none())

    class Meta:
        model = AssetCategory
        fields = ["id", "asset_type", "name", "code", "description", "created_at"]
        read_only_fields = ["id", "code", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset_type"].queryset = AssetType.objects.using(self.alias).all()

    def create(self, validated_data):
        user = getattr(self.context.get("request"), "user", None)
        obj = AssetCategory(created_by=getattr(user, "id", None), **validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj


class AssetGroupSerializer(AliasModelSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=AssetCategory.objects.none())

    class Meta:
        model = AssetGroup
        fields = ["id", "category", "name", "code", "description", "created_at"]
        read_only_fields = ["id", "code", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = AssetCategory.objects.using(self.alias).all()

    def create(self, validated_data):
        user = getattr(self.context.get("request"), "user", None)
        obj = AssetGroup(created_by=getattr(user, "id", None), **validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj


class AssetSubgroupSerializer(AliasModelSerializer):
    group = serializers.PrimaryKeyRelatedField(queryset=AssetGroup.objects.none())

    class Meta:
        model = AssetSubgroup
        fields = ["id", "group", "name", "code", "description", "created_at"]
        read_only_fields = ["id", "code", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = AssetGroup.objects.using(self.alias).all()

    def create(self, validated_data):
        user = getattr(self.context.get("request"), "user", None)
        obj = AssetSubgroup(created_by=getattr(user, "id", None), **validated_data)
        obj.full_clean(validate_unique=False)
        obj.save(using=self.alias)
        return obj


class AssetSerializer(AliasModelSerializer):
    location   = serializers.PrimaryKeyRelatedField(queryset=Location.objects.none())
    asset_type = serializers.PrimaryKeyRelatedField(queryset=AssetType.objects.none(), required=False, allow_null=True)
    category   = serializers.PrimaryKeyRelatedField(queryset=AssetCategory.objects.none(), required=False, allow_null=True)
    group      = serializers.PrimaryKeyRelatedField(queryset=AssetGroup.objects.none(), required=False, allow_null=True)
    subgroup   = serializers.PrimaryKeyRelatedField(queryset=AssetSubgroup.objects.none(), required=False, allow_null=True)

    class Meta:
        model = Asset
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["location"].queryset   = Location.objects.using(self.alias).all()
        self.fields["asset_type"].queryset = AssetType.objects.using(self.alias).all()
        self.fields["category"].queryset   = AssetCategory.objects.using(self.alias).all()
        self.fields["group"].queryset      = AssetGroup.objects.using(self.alias).all()
        self.fields["subgroup"].queryset   = AssetSubgroup.objects.using(self.alias).all()


class AssetPurchaseInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetPurchaseInfo
        exclude = ("asset",)


class AssetWarrantyAMCSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetWarrantyAMC
        exclude = ("asset",)


class AssetMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetMeasure
        exclude = ("asset",)


class AssetAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetAttachment
        exclude = ("asset",)



class AssetWarrantyAMCCreateSerializer(serializers.ModelSerializer):
    amc_terms = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = AssetWarrantyAMC
        fields = [
            "asset",
            "amc_provider", "amc_start", "amc_end", "amc_type",
            "under_warranty",
            "warranty_type", "warranty_start", "warranty_end",
            "amc_terms",
        ]
        extra_kwargs = {
            "asset": {"required": True},
            "amc_provider": {"required": True},  # vendor is compulsory
            "amc_start": {"required": True},
            "amc_end": {"required": True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        alias = self.context.get("alias")
        if not alias:
            raise RuntimeError("Serializer context missing 'alias'.")
        # queryset must point to the tenant DB
        self.fields["asset"].queryset = Asset.objects.using(alias).all()

    def validate(self, attrs):
        asset = attrs.get("asset")
        # location mandatory (through asset)
        if not getattr(asset, "location_id", None):
            raise serializers.ValidationError(
                {"asset": "Selected asset has no location; location is required."}
            )

        s, e = attrs.get("amc_start"), attrs.get("amc_end")
        if s and e and e < s:
            raise serializers.ValidationError({"amc_end": "AMC end date cannot be before start date."})

        ws, we = attrs.get("warranty_start"), attrs.get("warranty_end")
        if ws and we and we < ws:
            raise serializers.ValidationError({"warranty_end": "Warranty end date cannot be before start date."})

        return attrs



class AssetListSerializer(serializers.ModelSerializer):
    site_id      = serializers.IntegerField(source="location.site_id", read_only=True)
    building_id  = serializers.IntegerField(source="location.building_id", read_only=True)
    floor_id     = serializers.IntegerField(source="location.floor_id", read_only=True)
    unit_id      = serializers.IntegerField(source="location.unit_id", read_only=True)

    site_name      = serializers.SerializerMethodField()
    building_name  = serializers.SerializerMethodField()
    floor_name     = serializers.SerializerMethodField()
    unit_name      = serializers.SerializerMethodField()

    asset_type_id   = serializers.IntegerField(source="asset_type.id", read_only=True)
    asset_type_name = serializers.CharField(source="asset_type.name", read_only=True)
    category_id     = serializers.IntegerField(source="category.id", read_only=True)
    category_name   = serializers.CharField(source="category.name", read_only=True)
    group_id        = serializers.IntegerField(source="group.id", read_only=True)
    group_name      = serializers.CharField(source="group.name", read_only=True)
    subgroup_id     = serializers.IntegerField(source="subgroup.id", read_only=True)
    subgroup_name   = serializers.CharField(source="subgroup.name", read_only=True)

    class Meta:
        model = Asset
        fields = (
            "id", "asset_name", "brand", "model", "serial",
            "site_id", "building_id", "floor_id", "unit_id",
            "site_name", "building_name", "floor_name", "unit_name",
            "asset_type_id", "asset_type_name",
            "category_id", "category_name",
            "group_id", "group_name",
            "subgroup_id", "subgroup_name",
            "department", "critical", "asset_reading", "compliance",
            "breakdown", "in_use", "created_at",
        )

    def _req(self):
        return self.context.get("request")

    def get_site_name(self, obj):
        sid = getattr(getattr(obj, "location", None), "site_id", None)
        return resolve_name("sites", sid, self._req()) if sid else None

    def get_building_name(self, obj):
        bid = getattr(getattr(obj, "location", None), "building_id", None)
        return resolve_name("buildings", bid, self._req()) if bid else None

    def get_floor_name(self, obj):
        fid = getattr(getattr(obj, "location", None), "floor_id", None)
        return resolve_name("floors", fid, self._req()) if fid else None

    def get_unit_name(self, obj):
        uid = getattr(getattr(obj, "location", None), "unit_id", None)
        return resolve_name("units", uid, self._req()) if uid else None



class AssetWarrantyAMCListSerializer(serializers.ModelSerializer):
    asset_id     = serializers.IntegerField(source="asset.id", read_only=True)
    asset_name   = serializers.CharField(source="asset.asset_name", read_only=True)

    site_id      = serializers.IntegerField(source="asset.location.site_id", read_only=True)
    building_id  = serializers.IntegerField(source="asset.location.building_id", read_only=True)
    floor_id     = serializers.IntegerField(source="asset.location.floor_id", read_only=True)
    unit_id      = serializers.IntegerField(source="asset.location.unit_id", read_only=True)

    # NEW: name fields (resolved internally, fallback to None if error)
    site_name      = serializers.SerializerMethodField()
    building_name  = serializers.SerializerMethodField()
    floor_name     = serializers.SerializerMethodField()
    unit_name      = serializers.SerializerMethodField()

    class Meta:
        model  = AssetWarrantyAMC
        fields = [
            "id",
            "asset_id", "asset_name",
            "site_id", "building_id", "floor_id", "unit_id",
            "site_name", "building_name", "floor_name", "unit_name",
            "amc_provider",
            "amc_type", "amc_start", "amc_end",
            "warranty_type", "warranty_start", "warranty_end",
            "under_warranty",
            "amc_terms",
            "created_at",
        ]

    # ---- name resolvers (use the same token via request header) ----
    def _req(self):
        return self.context.get("request")

    def get_site_name(self, obj):
        sid = getattr(getattr(obj.asset, "location", None), "site_id", None)
        return resolve_name("sites", sid, self._req()) if sid else None

    def get_building_name(self, obj):
        bid = getattr(getattr(obj.asset, "location", None), "building_id", None)
        return resolve_name("buildings", bid, self._req()) if bid else None

    def get_floor_name(self, obj):
        fid = getattr(getattr(obj.asset, "location", None), "floor_id", None)
        return resolve_name("floors", fid, self._req()) if fid else None

    def get_unit_name(self, obj):
        uid = getattr(getattr(obj.asset, "location", None), "unit_id", None)
        return resolve_name("units", uid, self._req()) if uid else None


class AssetMeasureReadingSerializer(AliasModelSerializer):
    # write with measure_id, read with measure info
    measure_id = serializers.PrimaryKeyRelatedField(
        queryset=AssetMeasure.objects.none(), source="measure", write_only=True
    )
    measure_name = serializers.CharField(source="measure.name", read_only=True)
    unit_type    = serializers.CharField(source="measure.unit_type", read_only=True)
    asset_id     = serializers.IntegerField(source="measure.asset_id", read_only=True)

    class Meta:
        model  = AssetMeasureReading
        fields = ["id", "measure_id", "measure_name", "unit_type", "asset_id",
                  "reading_value", "created_at"]
        read_only_fields = ["id", "created_at", "measure_name", "unit_type", "asset_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # FK must query the tenant DB
        self.fields["measure_id"].queryset = AssetMeasure.objects.using(self.alias).all()

    def validate(self, attrs):
        measure = attrs.get("measure") or getattr(self.instance, "measure", None)
        value   = attrs.get("reading_value")
        if measure:
            if measure.min_value is not None and value < measure.min_value:
                raise serializers.ValidationError(
                    {"reading_value": f"Reading below min value ({measure.min_value})."}
                )
            if measure.max_value is not None and value > measure.max_value:
                raise serializers.ValidationError(
                    {"reading_value": f"Reading above max value ({measure.max_value})."}
                )
        return attrs

