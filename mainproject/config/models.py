from django.db import models
from django.utils import timezone
from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

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


class UserDatabase(models.Model):
    user_id   = models.IntegerField()
    username  = models.CharField(max_length=150, unique=True,null=True)  
    db_name   = models.CharField(max_length=100)
    db_user   = models.CharField(max_length=100)
    db_password = models.CharField(max_length=100)
    db_host   = models.CharField(max_length=100, default='localhost')
    db_port   = models.CharField(max_length=10, default='5432')
    db_type   = models.CharField(
        max_length=20,
        choices=[('self_hosted', 'Self Hosted'), ('client_hosted', 'Client Hosted')],
        default='self_hosted'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower('username'),
                name='uniq_userdatabase_username_ci'
            )
        ]

    def __str__(self):
        return f"[{self.username}] {self.db_name}@{self.db_host}:{self.db_port}"
