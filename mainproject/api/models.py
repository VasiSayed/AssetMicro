from django.db import models
from django.utils import timezone

class SoftDeleteModel(models.Model):
    """
    Abstract base class for soft delete.
    Adds is_deleted and deleted_at fields.
    """
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    created_by = models.IntegerField(blank=True,null=True)

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()

    def hard_delete(self, using=None, keep_parents=False):
        """Actually delete from DB."""
        super().delete(using=using, keep_parents=keep_parents)


class Asset(SoftDeleteModel):
    """
    Stores all asset details. References to building, floor, unit, vendor, PO are just integer IDs from external microservices.
    """
    building_id = models.IntegerField()
    floor_id = models.IntegerField()
    unit_id = models.IntegerField()
    vendor_id = models.IntegerField(blank=True, null=True)
    po_id = models.IntegerField(blank=True, null=True)  
    latitude = models.CharField(max_length=50, blank=True, null=True)
    longitude = models.CharField(max_length=50, blank=True, null=True)
    altitude = models.CharField(max_length=50, blank=True, null=True)

    asset_name = models.CharField(max_length=200)
    brand = models.CharField(max_length=100, blank=True, null=True)
    model = models.CharField(max_length=100, blank=True, null=True)
    serial = models.CharField(max_length=100, blank=True, null=True)

    asset_type = models.CharField(max_length=50)
    category = models.CharField(max_length=50)
    group = models.CharField(max_length=50)
    subgroup = models.CharField(max_length=50)
    capacity = models.CharField(max_length=100, blank=True, null=True)
    capacity_unit = models.CharField(max_length=50, blank=True, null=True)
    department = models.CharField(max_length=50)

    critical = models.BooleanField(default=False)  
    asset_reading = models.BooleanField(default=False)      
    compliance =  breakdown = models.BooleanField(default=False)    
    breakdown = models.BooleanField(default=False)
    in_use = models.BooleanField(default=False)

    maintained_by = models.IntegerField(blank=True, null=True)
    monitored_by = models.IntegerField(blank=True, null=True)
    managed_by = models.IntegerField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.asset_name


class AssetPurchaseInfo(SoftDeleteModel):
    """
    Stores purchase information for each asset (one-to-one).
    """
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name='purchase_info')
    cost = models.DecimalField(max_digits=12, decimal_places=2)
    po_number = models.CharField(max_length=100)
    purchase_date = models.DateField(blank=True, null=True)
    end_of_life = models.CharField(max_length=100, blank=True, null=True)
    vendor_name = models.CharField(max_length=200, blank=True, null=True)


class AssetWarrantyAMC(SoftDeleteModel):
    """
    Stores warranty and AMC details for each asset (one-to-one).
    You will filter on amc_end, amc_start for "expired"/"expiring in 90 days" in your API/queryset.
    """
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name='warranty_amc')
    warranty_type = models.CharField(max_length=100, blank=True, null=True)
    warranty_start = models.DateField(blank=True, null=True)
    warranty_end = models.DateField(blank=True, null=True)
    under_warranty = models.CharField(max_length=5, default="No")  # "Yes" or "No"
    amc_type = models.CharField(max_length=100, blank=True, null=True)
    amc_start = models.DateField(blank=True, null=True)
    amc_end = models.DateField(blank=True, null=True)
    amc_provider = models.CharField(max_length=200, blank=True, null=True)


class AssetMeasure(SoftDeleteModel):
    """
    Stores measurement configuration for each asset.
    Used for both consumption and non-consumption measures.
    """
    MEASURE_TYPE = (
        ("consumption", "Consumption"),
        ("nonConsumption", "Non Consumption"),
    )
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='measures')
    measure_type = models.CharField(max_length=20, choices=MEASURE_TYPE)
    name = models.CharField(max_length=100)
    unit_type = models.CharField(max_length=50)
    min_value = models.CharField(max_length=50, blank=True, null=True)
    max_value = models.CharField(max_length=50, blank=True, null=True)
    alert_below = models.CharField(max_length=50, blank=True, null=True)
    alert_above = models.CharField(max_length=50, blank=True, null=True)
    multiplier = models.CharField(max_length=50, blank=True, null=True)
    check_previous = models.BooleanField(default=False)


class AssetAttachment(SoftDeleteModel):
    """
    Stores asset-related files (invoice, insurance, manuals, others).
    """
    ATTACHMENT_TYPES = (
        ("invoice", "Purchase Invoice"),
        ("insurance", "Insurance"),
        ("manuals", "Manuals"),
        ("other", "Other"),
    )
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='attachments')
    attachment_type = models.CharField(max_length=50, choices=ATTACHMENT_TYPES)
    file = models.FileField(upload_to='asset_attachments/')
    uploaded_at = models.DateTimeField(auto_now_add=True)