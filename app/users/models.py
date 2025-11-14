# users/models.py

import uuid
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from fundamentals.bases import BaseModel
from django.contrib.contenttypes.models import ContentType



# Note, the default fields from django core user model are:
# username password email first_name last_name
class CustomUserManager(UserManager):
    pass


class Role(BaseModel):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('steward', 'Steward'),
        ('member', 'Member'),
    ]

    name = models.CharField(max_length=50, choices=ROLE_CHOICES, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        app_label = "users"
        verbose_name = "Role"
        verbose_name_plural = "Roles"


class CustomUser(AbstractUser, BaseModel):
    users = CustomUserManager() # instead of the default name 'objects'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    roles = models.ManyToManyField(Role, related_name='users')

    autocomplete_search_field = 'first_name'

    def autocomplete_label(self):
        return self.first_name

    def has_role(self, *role_names):
        """
        Helper method to check for one or more roles.
        Example: user.has_role('admin', 'steward')
        """
        user_roles = self.roles.values_list('name', flat=True)
        print(f"[DEBUG] Checking roles: {role_names} against user roles: {list(user_roles)}")
        return any(role in user_roles for role in role_names)

    def active_groups(self):
        from groups.models import Group
        ct = ContentType.objects.get_for_model(self.__class__)
        return Group.objects.filter(
            memberships__member_content_type=ct,
            memberships__member_object_id=self.id,
            memberships__is_active=True,
            memberships__is_banned=False,
            memberships__is_evicted=False,
        ).distinct()

    def __str__(self):
        return f"CustomUser - {self.username}: {self.first_name} {self.last_name}"

    class Meta:
        app_label = "users"
        verbose_name = "Custom User"
        verbose_name_plural = "Custom Users"
