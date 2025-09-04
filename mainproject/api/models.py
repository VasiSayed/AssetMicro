from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.db import router
from decimal import Decimal

class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class DeletedManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=True)


class BaseModel(models.Model):
    created_by = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    deleted_by = models.IntegerField(blank=True, null=True)

    objects = ActiveManager()
    deleted_objects = DeletedManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, user_id=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if user_id:
            self.deleted_by = user_id
        self.save()

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)


class AssetType(BaseModel):
    site_id = models.IntegerField(db_index=True, null=True, blank=True)
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=64, blank=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['site_id', 'name'], name='uniq_type_name_per_site'),
            models.UniqueConstraint(fields=['site_id', 'code'], name='uniq_type_code_per_site'),
        ]
        indexes = [
            models.Index(fields=['site_id', 'name']),
            models.Index(fields=['site_id', 'code']),
        ]

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or router.db_for_write(self.__class__, instance=self)

        if not self.code:
            base = (slugify(self.name) or "type")[:64]
            code = base
            i = 1
            qs = AssetType.all_objects.using(using).filter(site_id=self.site_id, code=code)
            while qs.exclude(pk=self.pk).exists():
                i += 1
                code = f"{base}-{i}"[:64]
                qs = AssetType.all_objects.using(using).filter(site_id=self.site_id, code=code)
            self.code = code

        super().save(*args, **kwargs)

    def __str__(self):
        return f"[site={self.site_id or '-'}] {self.name}"


class AssetCategory(BaseModel):
    asset_type = models.ForeignKey(
        AssetType, on_delete=models.CASCADE, related_name='categories', db_index=True
    )
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=64, blank=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['asset_type', 'name'], name='uniq_category_name_per_type'),
            models.UniqueConstraint(fields=['asset_type', 'code'], name='uniq_category_code_per_type'),
        ]
        indexes = [
            models.Index(fields=['asset_type', 'name']),
            models.Index(fields=['asset_type', 'code']),
        ]

    def clean(self):
        if not (self.name or "").strip():
            raise ValidationError({"name": "Name cannot be blank."})
        
    def save(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or router.db_for_write(self.__class__, instance=self)
        if not self.code:
            base = (slugify(self.name) or "category")[:64]
            code = base
            i = 1
            qs = AssetCategory.all_objects.using(using).filter(asset_type=self.asset_type, code=code)
            while qs.exclude(pk=self.pk).exists():
                i += 1
                code = f"{base}-{i}"[:64]
                qs = AssetCategory.all_objects.using(using).filter(asset_type=self.asset_type, code=code)
            self.code = code
        super().save(*args, **kwargs)
    def __str__(self):
        return f"{self.asset_type.name if self.asset_type else '-'} / {self.name}"


class AssetGroup(BaseModel):
    category = models.ForeignKey(
        AssetCategory, on_delete=models.CASCADE, related_name='groups', db_index=True
    )
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=64, blank=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['category', 'name'], name='uniq_group_name_per_category'),
            models.UniqueConstraint(fields=['category', 'code'], name='uniq_group_code_per_category'),
        ]
        indexes = [
            models.Index(fields=['category', 'name']),
            models.Index(fields=['category', 'code']),
        ]

    def clean(self):
        if not (self.name or "").strip():
            raise ValidationError({"name": "Name cannot be blank."})

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or router.db_for_write(self.__class__, instance=self)
        if not self.code:
            base = (slugify(self.name) or "group")[:64]
            code = base
            i = 1
            qs = AssetGroup.all_objects.using(using).filter(category=self.category, code=code)
            while qs.exclude(pk=self.pk).exists():
                i += 1
                code = f"{base}-{i}"[:64]
                qs = AssetGroup.all_objects.using(using).filter(category=self.category, code=code)
            self.code = code
        super().save(*args, **kwargs)

    def __str__(self):
        cat = self.category
        return f"{cat.asset_type.name if cat and cat.asset_type else '-'} / {cat.name if cat else '-'} / {self.name}"


class AssetSubgroup(BaseModel):
    group = models.ForeignKey(
        AssetGroup, on_delete=models.CASCADE, related_name='subgroups', db_index=True
    )
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=64, blank=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['group', 'name'], name='uniq_subgroup_name_per_group'),
            models.UniqueConstraint(fields=['group', 'code'], name='uniq_subgroup_code_per_group'),
        ]
        indexes = [
            models.Index(fields=['group', 'name']),
            models.Index(fields=['group', 'code']),
        ]

    def clean(self):
        if not (self.name or "").strip():
            raise ValidationError({"name": "Name cannot be blank."})

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or self._state.db or router.db_for_write(self.__class__, instance=self)
        if not self.code:
            base = (slugify(self.name) or "subgroup")[:64]
            code = base
            i = 1
            qs = AssetSubgroup.all_objects.using(using).filter(group=self.group, code=code)
            while qs.exclude(pk=self.pk).exists():
                i += 1
                code = f"{base}-{i}"[:64]
                qs = AssetSubgroup.all_objects.using(using).filter(group=self.group, code=code)
            self.code = code
        super().save(*args, **kwargs)

    def __str__(self):
        grp = self.group
        cat = grp.category if grp else None
        atype = cat.asset_type if cat else None
        return f"{atype.name if atype else '-'} / {cat.name if cat else '-'} / {grp.name if grp else '-'} / {self.name}"


class Location(BaseModel):
    site_id = models.IntegerField(db_index=True)   
    name = models.CharField(max_length=200)
    building_id = models.IntegerField()
    floor_id = models.IntegerField()
    unit_id = models.IntegerField()


    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['site_id', 'building_id', 'floor_id', 'unit_id'],
                name='uniq_location_per_site_building_floor_unit'
            ),
        ]
        indexes = [
            models.Index(fields=['site_id', 'building_id', 'floor_id', 'unit_id']),
        ]

    def __str__(self):
        return f"Site {self.site_id} / B{self.building_id} / F{self.floor_id} / U{self.unit_id}"


class Asset(BaseModel):
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name="assets"
    )
    vendor_id = models.IntegerField(blank=True, null=True)
    po_id = models.IntegerField(blank=True, null=True)

    latitude = models.CharField(max_length=50, blank=True, null=True)
    longitude = models.CharField(max_length=50, blank=True, null=True)
    altitude = models.CharField(max_length=50, blank=True, null=True)

    asset_name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, blank=True, null=True)
    model = models.CharField(max_length=100, blank=True, null=True)
    serial = models.CharField(max_length=100, blank=True, null=True)

    asset_type = models.ForeignKey(AssetType, on_delete=models.SET_NULL, null=True, blank=True, related_name="assets")
    category   = models.ForeignKey(AssetCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="assets")
    group      = models.ForeignKey(AssetGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="assets")
    subgroup   = models.ForeignKey(AssetSubgroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="assets")

    capacity = models.CharField(max_length=100, blank=True, null=True)
    capacity_unit = models.CharField(max_length=50, blank=True, null=True)
    department = models.CharField(max_length=50)

    critical = models.BooleanField(default=False)
    asset_reading = models.BooleanField(default=False)
    compliance = models.BooleanField(default=False)
    breakdown = models.BooleanField(default=False)
    in_use = models.BooleanField(default=False)

    maintained_by = models.IntegerField(blank=True, null=True)
    monitored_by = models.IntegerField(blank=True, null=True)
    managed_by = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return self.asset_name

    def clean(self):
        if not self.asset_name or not self.asset_name.strip():
            raise ValidationError({"asset_name": "Asset name cannot be empty."})
        if not self.serial and not self.model:
            raise ValidationError("Either serial number or model must be provided.")

        try:
            if self.latitude and not (-90 <= float(self.latitude) <= 90):
                raise ValidationError({"latitude": "Latitude must be between -90 and 90."})
            if self.longitude and not (-180 <= float(self.longitude) <= 180):
                raise ValidationError({"longitude": "Longitude must be between -180 and 180."})
        except ValueError:
            raise ValidationError("Latitude/Longitude must be numeric values.")

        if self.category and (not self.asset_type or self.category.asset_type_id != self.asset_type_id):
            raise ValidationError({"category": "Category must belong to the selected asset type."})

        if self.group and (not self.category or self.group.category_id != self.category_id):
            raise ValidationError({"group": "Group must belong to the selected category."})
        if self.subgroup and (not self.group or self.subgroup.group_id != self.group_id):
            raise ValidationError({"subgroup": "Subgroup must belong to the selected group."})



class AssetPurchaseInfo(BaseModel):
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name='purchase_info')
    cost = models.DecimalField(max_digits=12, decimal_places=2)
    po_number = models.CharField(max_length=100)
    purchase_date = models.DateField(blank=True, null=True)
    end_of_life = models.CharField(max_length=100, blank=True, null=True)
    vendor_name = models.CharField(max_length=200, blank=True, null=True)

    def clean(self):
        if self.cost < 0:
            raise ValidationError({"cost": "Cost must be a positive value."})


class AssetWarrantyAMC(BaseModel):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='warranty_amc')
    warranty_type = models.CharField(max_length=100, blank=True, null=True)
    warranty_start = models.DateField(blank=True, null=True)
    warranty_end = models.DateField(blank=True, null=True)
    under_warranty = models.BooleanField(default=False)
    amc_type = models.CharField(max_length=100, blank=True, null=True)
    amc_start = models.DateField(blank=True, null=True)
    amc_end = models.DateField(blank=True, null=True)
    amc_provider = models.CharField(max_length=200, blank=True, null=True)
    amc_terms = models.FileField(upload_to="amc_terms/%Y/%m/", null=True, blank=True)

    def clean(self):
        if self.warranty_start and self.warranty_end and self.warranty_end < self.warranty_start:
            raise ValidationError("Warranty end date cannot be before start date.")
        if self.amc_start and self.amc_end and self.amc_end < self.amc_start:
            raise ValidationError("AMC end date cannot be before start date.")


class AssetMeasure(BaseModel):
    MEASURE_TYPE = (
        ("consumption", "Consumption"),
        ("nonConsumption", "Non Consumption"),
    )
    asset = models.ForeignKey(
        Asset, on_delete=models.CASCADE, related_name="measures"
    )
    measure_type = models.CharField(max_length=20, choices=MEASURE_TYPE)
    name = models.CharField(max_length=100)
    unit_type = models.CharField(max_length=50)

    # Store limits as decimals (better than CharField for numeric validation)
    min_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    alert_below = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    alert_above = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    multiplier = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    check_previous = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["asset", "name"], name="uq_asset_measure_name")
        ]

    def clean(self):
        # Ensure min <= max
        if self.min_value is not None and self.max_value is not None:
            if Decimal(self.min_value) > Decimal(self.max_value):
                raise ValidationError("min_value cannot be greater than max_value.")

    def __str__(self):
        return f"{self.asset} - {self.name} ({self.unit_type})"
    
    def clean(self):
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValidationError("min_value cannot be greater than max_value.")

        if self.alert_below is not None and self.min_value is not None and self.alert_below < self.min_value:
            raise ValidationError({"alert_below": "Must be ≥ min_value."})
        if self.alert_above is not None and self.max_value is not None and self.alert_above > self.max_value:
            raise ValidationError({"alert_above": "Must be ≤ max_value."})


class AssetMeasureReading(BaseModel):
    measure = models.ForeignKey(
        AssetMeasure, on_delete=models.CASCADE, related_name="readings"
    )
    reading_value = models.DecimalField(max_digits=14, decimal_places=4)
    # recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["measure", "created_at"]),
        ]

    def clean(self):
        """Validate that reading_value is within measure's min/max range."""
        if not self.measure:
            return

        if self.measure.min_value is not None and self.reading_value < self.measure.min_value:
            raise ValidationError(f"Reading below min value ({self.measure.min_value}).")

        if self.measure.max_value is not None and self.reading_value > self.measure.max_value:
            raise ValidationError(f"Reading above max value ({self.measure.max_value}).")

    def __str__(self):
        return f"Reading {self.reading_value} {self.measure.unit_type} for {self.measure.name} at {self.created_at}"



class AssetAttachment(BaseModel):
    ATTACHMENT_TYPES = (("invoice", "Purchase Invoice"), ("insurance", "Insurance"),
                        ("manuals", "Manuals"), ("other", "Other"))
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='attachments')
    attachment_type = models.CharField(max_length=50, choices=ATTACHMENT_TYPES)
    file = models.FileField(upload_to='asset_attachments/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if not self.file:
            raise ValidationError({"file": "Attachment file cannot be empty."})
