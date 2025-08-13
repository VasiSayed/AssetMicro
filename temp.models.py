from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.models import AbstractUser


class SoftDeleteModel(models.Model):
    """Abstract base: soft delete + created_by."""
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_created"
    )

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"])

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)


class User(AbstractUser):
    """
    Custom user extending AbstractUser.
    Adds is_client flag to distinguish client logins.
    """
    is_client = models.BooleanField(default=False)

    def __str__(self):
        return self.username


class Organization(SoftDeleteModel):
    name = models.CharField(max_length=200, unique=True)
    code = models.SlugField(max_length=64, unique=True)
    user = models.ForeignKey(User,on_delete=models.SET_NULL)

    class Meta:
        indexes = [models.Index(fields=["code"])]

    def __str__(self):
        return self.name


class Company(SoftDeleteModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, related_name="entities"
    )
    name = models.CharField(max_length=200)
    user = models.ForeignKey(User,on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["entity", "name"], name="uniq_company_name_per_entity"
            ),
        ]
        indexes = [models.Index(fields=["entity", "name"])]

    def __str__(self):
        return f"{self.entity.organization.code} / {self.entity.code} / {self.name}"


class Entity(SoftDeleteModel):
    company = models.ForeignKey(
        Company,on_delete=models.SET_NUL, related_name="sites", null=True, blank=True
    )

    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=64)
    user = models.ForeignKey(User,on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="uniq_entity_name_per_org"
            ),
            models.UniqueConstraint(
                fields=["organization", "code"], name="uniq_entity_code_per_org"
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "name"]),
            models.Index(fields=["organization", "code"]),
        ]

    def __str__(self):
        return f"{self.organization.code} / {self.code}"



class Site(SoftDeleteModel):
    name = models.CharField(max_length=200)
    code = models.SlugField(max_length=64)
    address = models.TextField(blank=True, null=True)

    company = models.ForeignKey(
        Company,on_delete=models.SET_NUL, related_name="sites", null=True, blank=True
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.SET_NULL, null=True, blank=True, related_name="sites"
    )
    entity = models.ForeignKey(
        Entity, on_delete=models.SET_NULL, null=True, blank=True, related_name="sites"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="uniq_site_name_per_company"
            ),
            models.UniqueConstraint(
                fields=["company", "code"], name="uniq_site_code_per_company"
            ),
        ]
        indexes = [
            models.Index(fields=["company", "name"]),
            models.Index(fields=["company", "code"]),
        ]

    def __str__(self):
        return f"{self.company} / {self.code}"




class Module(SoftDeleteModel):
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, related_name="modules")
    code = models.CharField(max_length=50)  
    name = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["site", "code"], name="uniq_module_code_per_site")
        ]
        indexes = [
            models.Index(fields=["site", "code"]),
        ]

    def __str__(self):
        return f"{self.site.code} :: {self.code} - {self.name}"


class Department(SoftDeleteModel):
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, related_name="modules")
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Role(SoftDeleteModel):
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, related_name='roles')
    name = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['department', 'name'], name='uniq_role_per_department')
        ]

    def __str__(self):
        return f"{self.department.name} / {self.name}"


class RoleModulePermission(SoftDeleteModel):
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        related_name='role_module_perms' 
    )
    role   = models.ForeignKey(Role, on_delete=models.SET_NULL, related_name='module_perms')
    module = models.ForeignKey(Module, on_delete=models.SET_NULL, related_name='role_perms')

    for_all   = models.BooleanField(default=False)
    can_view   = models.BooleanField(default=False)
    can_create = models.BooleanField(default=False)
    can_update = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['role', 'module'], name='uniq_role_module_perm'),
            models.Index(fields=['department', 'role']),
            models.Index(fields=['module']),
        ]

    def clean(self):
        if self.role and self.department and self.role.department_id != self.department_id:
            raise ValidationError("Role.department must match RoleModulePermission.department")

    def __str__(self):
        return f"{self.role} → {self.module.code}"
