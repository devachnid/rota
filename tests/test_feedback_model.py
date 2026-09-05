"""The feedback record: what it says about itself, and who may touch it in
the admin."""

import pytest
from django.utils import timezone

from feedback.models import Feedback

pytestmark = pytest.mark.django_db


def test_str_names_the_kind_the_reporter_and_the_day(gp_user):
    fb = Feedback.objects.create(kind="BUG", message="The week grid is blank", reporter=gp_user)
    day = timezone.localdate(fb.created_at)
    assert str(fb) == f"Bug report from gp@example.com on {day:%-d %b %Y}"


def test_str_survives_a_deleted_reporter(gp_user):
    fb = Feedback.objects.create(kind="IDEA", message="Dark mode for print", reporter=gp_user)
    gp_user.delete()
    fb.refresh_from_db()
    assert fb.reporter is None
    assert str(fb).startswith("Idea from someone who has left on ")


def test_kind_word_is_the_phrase_used_in_emails_and_the_thanks():
    assert Feedback(kind="BUG").kind_word == "bug report"
    assert Feedback(kind="IDEA").kind_word == "idea"


def test_new_feedback_is_new_and_lists_newest_first(gp_user):
    older = Feedback.objects.create(kind="BUG", message="one", reporter=gp_user)
    newer = Feedback.objects.create(kind="BUG", message="two", reporter=gp_user)
    assert older.status == Feedback.Status.NEW
    assert list(Feedback.objects.all()) == [newer, older]


def test_a_rota_admin_may_change_feedback_and_a_gp_may_not(admin_user, gp_user):
    # accounts/backends.py answers yes to every permission on the apps the
    # rota owns, for rota admins. The new app must be one of them, or every
    # admin page for it 403s.
    assert admin_user.has_perm("feedback.change_feedback")
    assert admin_user.has_module_perms("feedback")
    assert not gp_user.has_perm("feedback.change_feedback")
