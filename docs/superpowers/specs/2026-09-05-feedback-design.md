# Feedback — design

**Date:** 2026-09-05
**Status:** approved in conversation; spec for review
**Branch:** `feature/feedback`

Nobody using the rota has a way to say "this is wrong" or "it would help
if…" short of finding Tom in the corridor. This adds a Feedback control to
every signed-in page: a short form in the app's own modal, a record in the
admin to triage, an email to the people who maintain the app, and a reply
that reaches the reporter by email.

## Decisions made in conversation

1. **Built in-house, no new dependency.** Tom allowed one; none fits. The
   maintained Django packages bring their own markup (GOV.UK, crispy-forms
   1.x) or store nothing; hosted widgets put a third-party script on pages
   that show staff rotas; GitHub Issues is public and a report may name a
   colleague. The app already has an htmx modal, a mail door with Mailjet's
   tracking turned off, and an admin with a Records group.
2. **Unobtrusive, everywhere.** A quiet "Feedback" control beside Theme in
   the desktop nav and in the mobile "More" sheet — both already on every
   page — not a floating tab that would fight the sticky header or the
   bottom bar.
3. **Reply to the reporter is in the first cut** — Tom's addition. An admin
   types a reply on the record and clicks **Send reply**; the reporter gets
   it by email and can answer it, because the email's Reply-To is the admin.
4. **No screenshots.** For twenty users the page and a description reproduce
   nearly everything on staging; a screenshot needs a vendored library and
   captures staff names. Revisit if reports keep lacking context.
5. **Calls made by the controller, for Tom to amend:** new reports notify
   every active **superuser** (the developer role here — rota admins run
   the practice, not the code); ten reports per person per hour is the
   ceiling; the page is taken from htmx's `HX-Current-URL` header and the
   viewport from an `hx-vals` expression, so no new JavaScript file.

## 1. Where it lives

A new app, `feedback`, alongside `rota` and `accounts`: `models.py`,
`forms.py`, `views.py`, `urls.py`, `admin.py`, `mail.py`, one migration,
templates under `templates/feedback/`. Nothing in `rota` imports it except
the two integration points below (sidebar item, dashboard line).

`config/urls.py` includes it at `feedback/`; `config/settings.py` adds
`"feedback"` to `INSTALLED_APPS` after `"rota"`.

## 2. The record

```python
class Feedback(models.Model):
    class Kind(models.TextChoices):
        BUG = "BUG", "Something's wrong"
        IDEA = "IDEA", "An idea"

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        SEEN = "SEEN", "Seen"
        DONE = "DONE", "Done"

    kind = models.CharField(max_length=4, choices=Kind.choices)
    message = models.TextField()
    page = models.CharField(max_length=300, blank=True)          # same-origin path + query
    viewport = models.CharField(max_length=20, blank=True)       # "390x844"
    user_agent = models.CharField(max_length=300, blank=True)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="feedback")
    created_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=4, choices=Status.choices, default=Status.NEW)
    admin_note = models.TextField(blank=True)                    # never sent
    reply = models.TextField(blank=True)                         # sent by "Send reply"
    replied_at = models.DateTimeField(null=True, blank=True)
    replied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "feedback"
        verbose_name_plural = "feedback"
```

`__str__` is the kind label, the reporter's email (or "someone who has
left") and the date. No IP address is stored: the reporter is signed in, so
it adds nothing.

## 3. The control and the form

**Trigger.** In `templates/base.html`, inside the `{% if user.is_authenticated %}`
block of the desktop nav, a `<button type="button" id="feedback-open"
class="btn btn-quiet" hx-get="{% url 'feedback-form' %}" hx-target="#modal">Feedback</button>`
sits beside the Theme toggle and shares its `font-size: var(--fs-xs)` rule.
In the mobile "More" sheet the same request is a `<button class="tabbar-link">`
that also closes its `<details>` on click. The login page renders neither:
the nav's authenticated block is the guard.

**The modal moves to `base.html`.** `<div id="modal"></div>` is today in
`templates/rota/grid.html` only. It moves to `base.html` after `<main>`,
inside `{% if user.is_authenticated %}`, and leaves `grid.html`, so every
signed-in page has exactly one `#modal` and the grid's cell, note and locum
forms keep working unchanged. `#modal:empty { display: none }` already hides
it when idle.

**The form** (`templates/feedback/_form.html`, rendered into `#modal` with
no `{% extends %}`, the same shape as `_daynote_form.html`):

```html
<form hx-post="{% url 'feedback-send' %}" hx-target="#modal" hx-swap="innerHTML"
      hx-vals='js:{"viewport": window.innerWidth + "x" + window.innerHeight}'
      hx-disabled-elt="find button[type=submit]">
  <div class="modal-head">Feedback</div>
  <div class="modal-body">
    <fieldset class="field">
      <legend>What is it?</legend>
      <div class="radio-row">
        <label><input type="radio" name="kind" value="BUG" checked> Something's wrong</label>
        <label><input type="radio" name="kind" value="IDEA"> An idea</label>
      </div>
    </fieldset>
    <div class="field">
      <label for="id_message">Tell us what happened, or what would help</label>
      <textarea name="message" id="id_message" rows="5" maxlength="2000" required autofocus
                placeholder="What you did, what you expected, what you saw"></textarea>
      {% if form.message.errors %}<p class="field-error" role="alert">{{ form.message.errors.0 }}</p>{% endif %}
    </div>
    {% if form.non_field_errors %}<p class="field-error" role="alert">{{ form.non_field_errors.0 }}</p>{% endif %}
  </div>
  <div class="modal-actions">
    <button type="submit" class="btn btn-primary">Send</button>
    <button type="button" class="btn btn-quiet" onclick="document.getElementById('modal').innerHTML=''">Cancel</button>
  </div>
</form>
```

The reporter's email is not asked for — they are signed in. `.radio-row` is
new in `components.css`: a flex row of labels with `gap: var(--sp-4)`, the
only CSS this work adds beyond the `#feedback-open` size rule.

**What is captured without asking.** `page` is the path and query of htmx's
`HX-Current-URL` header when its host is the request's own host, else `""`;
capped at 300 characters. `viewport` comes from the `hx-vals` expression,
validated as `\d{1,5}x\d{1,5}` and otherwise `""`. `user_agent` is the
request's header, capped at 300. All three are optional: a report with none
of them is still a report.

**After sending**, the response is `templates/feedback/_sent.html`:

```html
<form>
  <div class="modal-head">Thanks</div>
  <div class="modal-body">
    <p>Your {{ kind_label|lower }} is in. If it needs a reply you'll get an email at {{ email }}.</p>
  </div>
  <div class="modal-actions">
    <button type="button" class="btn btn-primary" onclick="document.getElementById('modal').innerHTML=''">Close</button>
  </div>
</form>
```

(A `<form>` wrapper, because `#modal form` in `components.css` is what lays
the modal out.) `kind_label` is "bug report" for BUG and "idea" for IDEA —
not the choice label, which is a sentence.

## 4. The views

Both in `feedback/views.py`, both `@login_required`:

- `feedback_form` (GET, `feedback/form/`, name `feedback-form`) renders the
  empty form.
- `feedback_send` (POST only, `feedback/send/`, name `feedback-send`) binds
  `FeedbackForm` (fields `kind`, `message`, `viewport`). Invalid → the form
  partial again with errors, **status 200** (htmx 2 does not swap 4xx into
  the target by default, and the modal must show the error). Valid → create
  the row with `reporter=request.user`, `page` and `user_agent` from the
  headers, then `notify_admins(request, feedback)`, then the thanks partial.

**Throttle.** `FeedbackForm.clean()` is not the place (it has no user); the
view checks `Feedback.objects.filter(reporter=user, created_at__gte=now - 1h).count() >= 10`
before saving and, if so, re-renders the form with the non-field error
"That's a lot of feedback in one hour — please try again later." Ten is a
ceiling against a stuck button or a script, not a quota anyone will meet.

Anonymous requests to either URL redirect to login, like every other page.

## 5. Email

`feedback/mail.py` reuses `accounts.mail.TRACKING_OFF` and
`accounts.mail.email_is_configured` — one door, one relay rule.

**Notification** (`notify_admins(request, feedback)`): recipients are
`User.objects.filter(is_superuser=True, is_active=True).exclude(email="")`.
With no recipients or no `EMAIL_HOST`, it returns without sending — the
record is already saved and the admin list shows it. Subject
`[Rota] Bug report from gp@example.com` / `[Rota] Idea from …`; plain-text
body from `templates/feedback/notify_email.txt`: kind, who, when (local
time), page, viewport and browser, the message, and the absolute admin
change URL (`request.build_absolute_uri(reverse("admin:feedback_feedback_change", args=[pk]))`).
`send(fail_silently=False)` inside `try/except Exception` with
`logger.exception(...)`: a relay failure is journaled, never shown to the
reporter, and never loses the report.

**Reply** (`send_reply(request, feedback)` → `None` on success, else a
reason string): to `feedback.reporter.email`, `reply_to=[request.user.email]`,
`TRACKING_OFF`. Subject `Reply to your rota bug report` / `… idea`; body
from `templates/feedback/reply_email.txt`:

```
Hello,

{{ reply }}

— {{ admin_email }}

You wrote on {{ created|date:"j F" }}{% if page %} (on {{ page }}){% endif %}:

{{ quoted }}

Reply to this email to reach {{ admin_email }}.
```

`quoted` is the original message with every line prefixed `> `, built in
Python before rendering. Not configured → returns "Email isn't set up"; a raise → logged and its
`str()` returned. Nothing is stamped unless the send succeeded.

## 6. The admin

`feedback/admin.py`, `FeedbackAdmin(unfold.admin.ModelAdmin)`:

- **List:** `kind` (label), `summary` (first 60 characters of the message),
  `reporter`, `page`, `created_at`, `status`, `replied` (boolean on
  `replied_at`). `list_filter = ("status", "kind")`,
  `search_fields = ("message", "reporter__email", "page")`,
  `list_select_related = ("reporter", "replied_by")`, `date_hierarchy = "created_at"`.
- **Change form fieldsets:** *Report* (kind, reporter, created_at, page,
  viewport, user_agent, message — all read-only: the app wrote them);
  *Triage* (status, admin_note, with help text "For admins only — never
  sent"); *Reply* (reply, replied_at, replied_by — the last two read-only).
- **No add page:** `has_add_permission` returns False; feedback comes from
  the app. Change and delete follow the site's normal rota-admin grants.
- **Send reply:** `actions_submit_line = ("send_reply",)`.
  `get_actions_submit_line` returns `[]` when the record has no reporter
  (account deleted). The action runs after unfold has saved the form:
  blank `reply` → `messages.error("Write the reply first.")`; otherwise
  `send_reply(...)`; `None` → stamp `replied_at`/`replied_by`, save those
  two fields, `messages.success("Reply sent to …")`; a reason →
  `messages.error("Reply saved but not sent: …")`. **Status is not changed
  by sending** — the admin sets it in the same form; the docs say so.
- **Bulk actions:** `mark_seen`, `mark_done` (`permissions=["change"]`),
  each an `update()` on the queryset.

**Sidebar:** `rota/admin_site.py` Records group gains
`_item("Feedback", "rate_review", rl("admin:feedback_feedback_changelist"))`
as its last item. Group count stays eight.

**Dashboard:** `rota/admin_dashboard.py::health()` gains
`{"label": "Feedback not yet looked at", "count": <NEW count>,
"url": reverse("admin:feedback_feedback_changelist") + "?status__exact=NEW",
"level": "warn"}` — red while anything is unread, grey at zero, like the
other lines.

## 7. Tests

pytest, the suite's fixtures (`gp_client`, `admin_client`, `staff_client`,
`configured`), locmem mail. Every assertion names a behaviour, not a value
copied from settings.

- **Form and send:** anonymous GET/POST redirect to login; a GP's GET renders
  the form with both radios; POST creates a row with kind, message,
  reporter, viewport, user agent (capped) and the page from
  `HX-Current-URL` — path and query kept, a foreign host dropped, a missing
  header stored as `""`; POST with an empty message re-renders the form with
  the error at status 200 and creates nothing; the eleventh report in an
  hour is refused with the throttle message and the count stays at ten; the
  response after a send is the thanks partial naming the reporter's email.
- **Notification:** with `configured` and two active superusers plus an
  inactive one, one message leaves to exactly the two, with both tracking
  headers, the kind and reporter in the subject, and the message, page and
  admin link in the body; with no `EMAIL_HOST`, nothing leaves and the row
  exists; when `EmailMessage.send` raises, the row exists, the reporter sees
  the thanks partial, and the exception is logged (caplog).
- **Reply:** a rota admin posting the change form with `reply` set and the
  `send_reply` button sends one message to the reporter with `Reply-To` the
  admin, the reply and the quoted original in the body, and stamps
  `replied_at`/`replied_by`; a blank reply sends nothing and shows the
  error; unconfigured email saves the reply, sends nothing, stamps nothing,
  shows the error; a record whose reporter is gone shows no button and a
  smuggled button name sends nothing; status posted in the same form is
  saved and unchanged by the send.
- **Admin:** the changelist and change form render for a rota admin (the
  render tripwire's `_models()` now includes `"feedback"` and its `rows`
  fixture has a `"feedback"` row); the add URL is refused; `mark_seen` and
  `mark_done` update selected rows; the sidebar shows Feedback under
  Records and every sidebar link still resolves; the dashboard line counts
  NEW only and its URL filters to the same rows and returns 200.
- **Chrome:** a signed-in page has exactly one `id="modal"` and the grid no
  longer carries its own; the Feedback control appears in the nav and in
  the tab-bar sheet for a signed-in GP and nowhere on the login page; the
  existing CSS cascade and responsive-nav tests still pass.

## 8. Documentation

- `docs/admin/day-to-day.md`: a `## Feedback` section after the audit log —
  what arrives, the three statuses, the note nobody sees, how a reply is
  sent and that sending does not close the item, and that notifications go
  to superusers.
- `docs/admin/README.md`: the Day to day row lists feedback.
- `README.md`: the *Outgoing email* section names the two new emails
  (notifications to superusers, replies to reporters) and that both need
  the same `EMAIL_*` keys and nothing more.
- `docs/backlog.md`: a Settled entry when the branch merges.

## 9. Deploy

`git pull`, `migrate` (feedback 0001), `collectstatic` (components.css),
restart. Nothing new in `/etc/rota.env`. Notifications reach whichever
superusers have an email on their account — check Tom's staging superuser
does.

## Out of scope

Screenshots or annotations; mirroring into a tracker; a reporter-facing
list of their own feedback; a focus trap or Escape-to-close on the shared
modal (pre-existing behaviour of every modal in the app); feedback from the
admin's own pages (the admin has the Records list; the app's nav is the
entry point).
