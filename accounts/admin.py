from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.forms import (AdminPasswordChangeForm, UserChangeForm,
                          UserCreationForm)

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin, ModelAdmin):
    """A rota admin (not a superuser) can open this changelist through
    RotaAdminBackend's blanket accounts.* grant. Without the guards below,
    that grant would let them edit is_staff/is_superuser on any account —
    including their own — through the ordinary change form, and reach a
    superuser's delete/password views. Only a superuser requester sees or
    can touch those fields or accounts; the guards defer to Django's normal
    checks for everyone else."""

    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    ordering = ("email",)
    list_display = ("email", "is_rota_admin", "is_active", "clinician_name")
    list_filter = ("is_rota_admin", "is_active")
    search_fields = ("email",)
    readonly_fields = ("clinician_name",)
    list_select_related = ("clinician",)
    add_fieldsets = (
        (None, {"fields": ("email", "password1", "password2", "is_rota_admin")}),
    )

    def get_queryset(self, request):
        """The changelist a rota admin sees excludes superuser rows
        entirely — see the docstring above. get_object() below does NOT
        go through this filtered queryset: a pk lookup (change/delete/
        password views) must still find a superuser's row so has_view_
        permission/has_change_permission/has_delete_permission can turn
        it away with their own 403, rather than this filter making
        Django treat the row as not existing (a redirect instead)."""
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            qs = qs.filter(is_superuser=False)
        return qs

    def get_object(self, request, object_id, from_field=None):
        queryset = admin.ModelAdmin.get_queryset(self, request)
        model = queryset.model
        field = model._meta.pk if from_field is None else model._meta.get_field(from_field)
        try:
            object_id = field.to_python(object_id)
            return queryset.get(**{field.name: object_id})
        except (model.DoesNotExist, ValidationError, ValueError):
            return None

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self.add_fieldsets
        sets = [
            ("Account", {"fields": ("email", "password")}),
            ("Rota", {
                "fields": ("is_rota_admin", "clinician_name"),
                "description": "A rota admin can publish weeks, run the fill, and "
                               "use this admin. Link a clinician on their record "
                               "under People › Clinicians.",
            }),
        ]
        if request.user.is_superuser:
            sets.append(("System", {"fields": ("is_active", "is_staff", "is_superuser")}))
        else:
            sets.append(("Status", {"fields": ("is_active",)}))
        return sets

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

    @admin.display(description="Clinician")
    def clinician_name(self, obj):
        clinician = getattr(obj, "clinician", None)
        if clinician is None:
            return "—"
        url = reverse("admin:rota_clinician_change", args=[clinician.pk])
        return format_html('<a href="{}">{}</a>', url, clinician.name)
