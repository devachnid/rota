from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """A rota admin (not a superuser) can open this changelist through
    RotaAdminBackend's blanket accounts.* grant. Without the guards below,
    that grant would let them edit is_staff/is_superuser on any account —
    including their own — through the ordinary change form, and reach a
    superuser's delete/password views. Only a superuser requester sees or
    can touch those fields or accounts; the guards defer to Django's normal
    checks for everyone else."""

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

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)   # add_fieldsets when obj is None
        if obj is None or request.user.is_superuser:
            return fieldsets
        # A rota admin: the account, the rota flag, and is_active alone — never
        # is_staff / is_superuser (Task 2's boundary), but a manager must still
        # be able to deactivate a leaver's login.
        return (fieldsets[0], fieldsets[1], ("Status", {"fields": ("is_active",)}))

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            fields = tuple(fields) + ("is_staff", "is_superuser")
        return fields

    def has_view_permission(self, request, obj=None):
        # Django's changeform_view checks has_view_OR_change_permission on a
        # GET, so has_change_permission alone would still hand a rota admin
        # a read-only look at (and, per the check below, a working change
        # form URL for) a superuser's account. Blocking view too closes that.
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)
