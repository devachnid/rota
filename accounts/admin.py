from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import action
from unfold.forms import AdminPasswordChangeForm, UserChangeForm

from .mail import link_expires, send_password_link
from .models import User


class InviteForm(forms.ModelForm):
    """The add form: who, and whether they run the rota. No password — the
    person chooses their own from the emailed link (save_model below)."""

    class Meta:
        model = User
        fields = ("email", "is_rota_admin")


def _report(request, user, result, *, invite):
    """The three outcomes of a send, as the message the admin reads. A link
    is shown here, once, and nowhere else."""
    what = "Invitation" if invite else "Password-reset link"
    if result is None:
        messages.success(request, f"{what} sent to {user.email}.")
    elif not result.reason:
        messages.warning(request, format_html(
            "Email isn't set up — copy this link and send it to {} yourself: "
            '<a href="{}">{}</a>', user.email, result.link, result.link))
    else:
        messages.error(request, format_html(
            "Sending to {} failed ({}) — copy this link and send it yourself: "
            '<a href="{}">{}</a>', user.email, result.reason, result.link, result.link))


@admin.register(User)
class CustomUserAdmin(UserAdmin, ModelAdmin):
    """A rota admin (not a superuser) can open this changelist through
    RotaAdminBackend's blanket accounts.* grant. Without the guards below,
    that grant would let them edit is_staff/is_superuser on any account —
    including their own — through the ordinary change form, and reach a
    superuser's delete/password views. Only a superuser requester sees or
    can touch those fields or accounts; the guards defer to Django's normal
    checks for everyone else.

    Passwords: an admin never types one. Adding an account sends an
    invitation; the change page offers one send button, chosen by state;
    the direct set-password form stays for superusers only."""

    form = UserChangeForm
    add_form = InviteForm
    change_password_form = AdminPasswordChangeForm
    ordering = ("email",)
    list_display = ("email", "is_rota_admin", "is_active", "is_set_up", "clinician_name")
    list_filter = ("is_rota_admin", "is_active")
    search_fields = ("email",)
    readonly_fields = ("clinician_name", "account_state")
    list_select_related = ("clinician",)
    add_fieldsets = (
        (None, {"fields": ("email", "is_rota_admin")}),
    )
    actions = ("send_links",)
    actions_submit_line = ("send_invitation", "send_reset_link")

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
        # `password` is Django's hash field with the link to the direct
        # set-password form — a superuser's tool, so only they see it.
        account = (("email", "password", "account_state") if request.user.is_superuser
                   else ("email", "account_state"))
        sets = [
            ("Account", {"fields": account}),
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

    # --- invitations ---------------------------------------------------------

    def save_model(self, request, obj, form, change):
        if not change:
            obj.set_unusable_password()
        # unfold's save_model runs whichever submit-line button was pressed,
        # after the save — so the two send_* methods below fire from here.
        super().save_model(request, obj, form, change)
        if not change:
            _report(request, obj, send_password_link(request, obj, invite=True), invite=True)

    def get_actions_submit_line(self, request, object_id):
        """One button, chosen by state: an account with no usable password
        can be invited again; one with a password can be sent a reset."""
        obj = self.get_object(request, object_id)
        want = ("send_reset_link" if obj is not None and obj.has_usable_password()
                else "send_invitation")
        return [a for a in super().get_actions_submit_line(request, object_id)
                if a.action_name.endswith(want)]

    @action(description="Send invitation again")
    def send_invitation(self, request, obj):
        _report(request, obj, send_password_link(request, obj, invite=True), invite=True)

    @action(description="Send password-reset link")
    def send_reset_link(self, request, obj):
        _report(request, obj, send_password_link(request, obj, invite=False), invite=False)

    @admin.action(description="Send invitation or reset link")
    def send_links(self, request, queryset):
        """Onboard a practice at once. Each row gets whichever it needs;
        rows the requester may not change (a superuser's, for a rota
        admin) are skipped — the changelist filter hides them anyway."""
        sent = copies = 0
        for user in queryset:
            if not self.has_change_permission(request, user):
                continue
            invite = not user.has_usable_password()
            result = send_password_link(request, user, invite=invite)
            if result is None:
                sent += 1
            else:
                copies += 1
                _report(request, user, result, invite=invite)
        messages.info(request, f"{sent} sent, {copies} to copy.")

    @admin.display(description="Set up?", boolean=True)
    def is_set_up(self, obj):
        return obj.has_usable_password()

    @admin.display(description="State")
    def account_state(self, obj):
        if obj.has_usable_password():
            return "Set up"
        sent = obj.password_link_sent_at
        if sent is None:
            return "Not yet invited"
        expires = link_expires(sent)
        if timezone.now() < expires:
            return (f"Invited {timezone.localtime(sent):%-d %b}, "
                    f"link expires {timezone.localtime(expires):%-d %b}")
        return "Invitation expired — send another"

    def user_change_password(self, request, id, form_url=""):
        """Django's direct set-password form. A rota admin sends links
        instead — so this is a superuser's tool, whatever has_change_
        permission says about the account."""
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().user_change_password(request, id, form_url)

    @admin.display(description="Clinician")
    def clinician_name(self, obj):
        clinician = getattr(obj, "clinician", None)
        if clinician is None:
            return "—"
        url = reverse("admin:rota_clinician_change", args=[clinician.pk])
        return format_html('<a href="{}">{}</a>', url, clinician.name)
