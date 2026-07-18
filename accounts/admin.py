from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    ordering = ("email",)
    list_display = ("email", "is_rota_admin", "is_active")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Rota", {"fields": ("is_rota_admin",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = (
        (None, {"fields": ("email", "password1", "password2", "is_rota_admin")}),
    )
