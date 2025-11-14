# /users/admin.py
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from profiles.models import UserProfile
from .models import Role

# ✅ Custom Action for Promotion
def promote_to_steward(modeladmin, request, queryset):
    steward_role = Role.objects.get(name="steward")
    for user in queryset:
        if not user.roles.filter(name="steward").exists():
            user.roles.add(steward_role)
            print(f"✅ {user.username} has been promoted to Steward.")

promote_to_steward.short_description = "Promote selected users to Steward"

# ✅ Custom User Admin
@admin.register(get_user_model())
class CustomUserAdmin(BaseUserAdmin):
    ordering = ('username',)
    list_display = ('username', 'email', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_active', 'roles')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_staff', 'is_active', 'roles')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'is_staff', 'is_active')}
         ),
    )
    search_fields = ('username', 'email')
    ordering = ('username',)

    class Meta:
        verbose_name = "Custom User"
        verbose_name_plural = "Custom Users"
        # app_label = "User Management"


# ✅ UserProfile Admin
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'slug', 'display_name', 'quick_intro']
    search_fields = ['user__username', 'slug', 'display_name']

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"
        # app_label = "User Management"


# ✅ Role Admin
@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['name']
    search_fields = ['name']

    class Meta:
        verbose_name = "Role"
        verbose_name_plural = "Roles"
        # app_label = "User Management"

