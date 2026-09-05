"""Registration only, so admin:feedback_feedback_change resolves for the
notification email. The full FeedbackAdmin (list, triage, Send reply)
replaces this file in a later task."""

from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Feedback

admin.site.register(Feedback, ModelAdmin)
