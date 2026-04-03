from django.db import models

from fundamentals.bases import BaseModel


class GroupPermissionProfile(BaseModel):
    group = models.ForeignKey(
        "groups.Group",
        on_delete=models.CASCADE,
        related_name="permission_profiles",
    )
    code = models.SlugField(max_length=100)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)
    decorators = models.ManyToManyField(
        "groups.MembershipDecorator",
        through="GroupPermissionProfileItem",
        related_name="group_permission_profiles",
        blank=True,
    )

    class Meta:
        db_table = "groups_grouppermissionprofile"
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["group", "code"],
                name="groups_profile_unique_code_per_group",
            ),
            models.UniqueConstraint(
                fields=["group"],
                condition=models.Q(is_default=True),
                name="groups_one_default_permission_profile_per_group",
            ),
        ]

    def __str__(self):
        return f"{self.group.slug} → {self.name}"


class GroupPermissionProfileItem(models.Model):
    profile = models.ForeignKey(
        GroupPermissionProfile,
        on_delete=models.CASCADE,
        related_name="items",
    )
    decorator = models.ForeignKey(
        "groups.MembershipDecorator",
        on_delete=models.CASCADE,
        related_name="group_permission_profile_items",
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "groups_grouppermissionprofileitem"
        ordering = ["sort_order", "id"]
        unique_together = [("profile", "decorator")]

    def __str__(self):
        return f"{self.profile} → {self.decorator.code}"
