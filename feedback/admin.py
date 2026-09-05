"""Triage. The report half is read-only — the app wrote it; the admin sets a
status, keeps a note nobody else sees, and can send the reporter a reply."""

from django.contrib import admin, messages
from django.utils import timezone
from unfold.admin import ModelAdmin
from unfold.decorators import action

from .mail import send_reply as mail_reply
from .models import Feedback


@admin.register(Feedback)
class FeedbackAdmin(ModelAdmin):
    list_display = ("kind", "summary", "reporter", "page", "created_at", "status", "replied")
    list_filter = ("status", "kind")
    search_fields = ("message", "reporter__email", "page")
    list_select_related = ("reporter", "replied_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("kind", "reporter", "created_at", "page", "viewport", "user_agent",
                       "message", "replied_at", "replied_by")
    fieldsets = (
        ("Report", {"fields": ("kind", "reporter", "created_at", "page", "viewport",
                               "user_agent", "message")}),
        ("Triage", {"fields": ("status", "admin_note"),
                    "description": "The note is for admins only — it is never sent."}),
        ("Reply", {"fields": ("reply", "replied_at", "replied_by"),
                   "description": "Write the reply and press Send reply. Sending does not "
                                  "change the status — set that above."}),
    )
    actions = ("mark_seen", "mark_done")
    actions_submit_line = ("send_reply",)

    def has_add_permission(self, request):
        # Feedback arrives from the app; nobody types it in here.
        return False

    @admin.display(description="Message")
    def summary(self, obj):
        text = " ".join(obj.message.split())
        return text if len(text) <= 60 else text[:59] + "…"

    @admin.display(boolean=True, description="Replied")
    def replied(self, obj):
        return obj.replied_at is not None

    def get_actions_submit_line(self, request, object_id):
        """No button when there is nobody to reply to — and a button name
        smuggled into the POST then does nothing, because unfold only runs
        the actions this returns."""
        obj = self.get_object(request, object_id)
        if obj is None or obj.reporter_id is None:
            return []
        return super().get_actions_submit_line(request, object_id)

    @action(description="Send reply")
    def send_reply(self, request, obj):
        # Runs after unfold has saved the form, so obj.reply is what was typed.
        if not obj.reply.strip():
            messages.error(request, "Write the reply first.")
            return
        reason = mail_reply(request, obj)
        if reason is None:
            obj.replied_at = timezone.now()
            obj.replied_by = request.user
            obj.save(update_fields=["replied_at", "replied_by"])
            messages.success(request, f"Reply sent to {obj.reporter.email}.")
        else:
            messages.error(request, f"Reply saved but not sent: {reason}.")

    @admin.action(description="Mark as seen", permissions=["change"])
    def mark_seen(self, request, queryset):
        n = queryset.update(status=Feedback.Status.SEEN)
        messages.success(request, f"{n} marked as seen.")

    @admin.action(description="Mark as done", permissions=["change"])
    def mark_done(self, request, queryset):
        n = queryset.update(status=Feedback.Status.DONE)
        messages.success(request, f"{n} marked as done.")
