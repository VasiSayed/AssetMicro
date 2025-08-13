from django.db import models

# 1. ASSET MASTER & ASSOCIATED DATA

class Asset(models.Model):
    """
    Stores all asset details. References to building, floor, unit, vendor, PO are just integer IDs from external microservices.
    """
    # External entity IDs (NOT ForeignKeys)
    building_id = models.IntegerField()
    floor_id = models.IntegerField()
    unit_id = models.IntegerField()
    vendor_id = models.IntegerField(blank=True, null=True)
    po_id = models.IntegerField(blank=True, null=True)  # Purchase Order from another service

    # Core fields
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

    # Status/radio/boolean
    critical = models.CharField(max_length=5, default="No")      # "Yes" or "No"
    asset_reading = models.CharField(max_length=5, default="No") # "Yes" or "No"
    compliance = models.CharField(max_length=5, default="No")    # "Yes" or "No"
    breakdown = models.BooleanField(default=False)
    in_use = models.BooleanField(default=False)

    # Location (geo)
    latitude = models.CharField(max_length=50, blank=True, null=True)
    longitude = models.CharField(max_length=50, blank=True, null=True)
    altitude = models.CharField(max_length=50, blank=True, null=True)

    # Additional info
    maintained_by = models.CharField(max_length=100, blank=True, null=True)
    monitored_by = models.CharField(max_length=100, blank=True, null=True)
    managed_by = models.CharField(max_length=100, blank=True, null=True)

    # Created timestamp
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.asset_name

class AssetPurchaseInfo(models.Model):
    """
    Stores purchase information for each asset (one-to-one).
    """
    asset = models.OneToOneField(Asset, on_delete=models.CASCADE, related_name='purchase_info')
    cost = models.DecimalField(max_digits=12, decimal_places=2)
    po_number = models.CharField(max_length=100)
    purchase_date = models.DateField(blank=True, null=True)
    end_of_life = models.CharField(max_length=100, blank=True, null=True)
    vendor_name = models.CharField(max_length=200, blank=True, null=True)

class AssetWarrantyAMC(models.Model):
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

class AssetMeasure(models.Model):
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

class AssetAttachment(models.Model):
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

class InventoryMaster(models.Model):
    """
    Master table for inventory items.
    Used for both Masters and as a basis for Stocks.
    """
    STATUS_CHOICES = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=100, unique=True)
    serial_number = models.CharField(max_length=100, blank=True, null=True)
    inventory_type = models.CharField(max_length=100)
    category = models.CharField(max_length=100)
    expiry_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class StockEntry(models.Model):
    """
    Represents the physical stock, with quantity, linked to a master.
    """
    STATUS_CHOICES = (
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    )
    master = models.ForeignKey(InventoryMaster, on_delete=models.CASCADE, related_name='stocks')
    code = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=100, blank=True, null=True)
    inventory_type = models.CharField(max_length=100)
    category = models.CharField(max_length=100)
    expiry_date = models.DateField(blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Active')
    location_id = models.IntegerField(blank=True, null=True)  # External location
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.master.name} ({self.quantity})"

class GRN(models.Model):
    """
    Goods Receipt Note for received stock (linked to stock and external PO/supplier).
    """
    purchase_order_id = models.IntegerField()  # External PO reference
    supplier_id = models.IntegerField()        # External Supplier reference
    invoice_number = models.CharField(max_length=100)
    invoice_date = models.DateField()
    invoice_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_mode = models.CharField(max_length=100)
    stock_entry = models.ForeignKey(StockEntry, on_delete=models.SET_NULL, null=True, blank=True, related_name='grns')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"GRN-{self.invoice_number}"

class GDN(models.Model):
    """
    Goods Dispatch Note for dispatched stock (linked to stock and external receiver).
    """
    gdn_number = models.CharField(max_length=100)
    stock_entry = models.ForeignKey(StockEntry, on_delete=models.CASCADE, related_name='gdns')
    dispatched_date = models.DateField()
    quantity_dispatched = models.PositiveIntegerField()
    receiver_id = models.IntegerField()  # If receiver is managed externally
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"GDN-{self.gdn_number}"


class Checklist(models.Model):
    """
    Top-level checklist, can be associated to any entity (asset/unit/group) via IDs in a JSON array.
    """
    name = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    group_count = models.PositiveIntegerField(default=1)
    frequency = models.CharField(max_length=50)
    priority = models.CharField(max_length=50)
    associations = models.JSONField(default=list, blank=True)  # Store related asset/unit/group IDs as list of dicts
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class ChecklistItem(models.Model):
    """
    Each checklist consists of items/tasks to be done, completed or not, and remarks.
    """
    checklist = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name='items')
    description = models.TextField()
    completed = models.BooleanField(default=False)
    remarks = models.TextField(blank=True, null=True)

class PPMTask(models.Model):
    """
    Stores both Routine and PPM Activity tasks.
    Reference asset_id is an integer (from Asset service).
    """
    ROUTINE = "routine"
    ACTIVITY = "activity"
    TASK_TYPE_CHOICES = [
        (ROUTINE, "Routine Task"),
        (ACTIVITY, "PPM Activity"),
    ]
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=TASK_TYPE_CHOICES)
    asset_id = models.IntegerField()    # reference to Asset in your asset service
    frequency = models.CharField(max_length=50)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=50, default="Scheduled")
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
