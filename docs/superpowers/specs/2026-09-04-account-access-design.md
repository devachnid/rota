# Account access — design

**Date:** 2026-09-04
**Status:** approved in conversation; spec for review
**Branches:** `feature/account-invites` (§1–§4), then `feature/passkeys` (§5)

Today an admin creating a login account types a password for the new person
and passes it on by some other channel, and nobody can change or recover a
password without an admin. `/accounts/password_reset/` is already routed —
`config/urls.py` includes `django.contrib.auth.urls` — but nothing links to
it, it renders the raw Django-admin template, and its submit would 500 in
production because the app has no outgoing email at all: no `EMAIL_*`
setting, no mail keys in `/etc/rota.env`.

This work makes an account something a person sets up themselves from an
emailed link, lets them reset or change their own password, and adds
passkeys as a second way in.

## Decisions made in conversation

1. **An admin creates the account; the person sets the password.** The add
   form loses its password fields. A rota admin never knows anyone's
   password; only a superuser keeps the direct set-password form. This
   settles the question parked by the admin overhaul (a rota admin could
   reset any non-superuser's password): now they send a link instead.
2. **Mailjet is the relay.** It is plain authenticated SMTP, so it is
   configuration in `/etc/rota.env`, not code — Django's own SMTP backend,
   no package. Nothing in the repo names Mailjet except two headers that
   turn its link-tracking off (§1).
3. **The `webauthn` dependency is acceptable** — Tom's ruling. The honest
   count: `webauthn==3.0.0` plus seven transitive packages (`cbor2`,
   `cryptography`, `cffi`, `pycparser`, `pyasn1`, `pyasn1_modules`,
   `pyOpenSSL`), two of them compiled with manylinux wheels for this
   x86_64 box. Every one is pinned exactly in `requirements.txt`. The
   alternative — CBOR parsing and ECDSA verification by hand — was
   rejected: hand-rolled crypto has no place in a solo-maintained app.
4. **Two branches.** Invites and self-service are pure Django and can reach
   staging while passkeys are built; passkeys need real devices to try, and
   they need the email flow as their recovery path regardless.
5. **Calls made by the controller, for Tom to amend:** links last 7 days,
   not Django's 3 (accounts are made ahead of a start date); setting a
   password from a link signs the person straight in; no second link to the
   same account within 5 minutes; user verification is required for
   passkeys; a rota admin can remove anyone's passkey (a lost phone is a
   practice-manager job).

## Global constraints

- No build step, no node. New dependencies: exactly the eight named in
  decision 3, and only on the `feature/passkeys` branch. The invites branch
  adds none.
- Secrets live in `/etc/rota.env` and nowhere else. `EMAIL_HOST_PASSWORD`
  (the Mailjet secret key) never appears in a repo file, fixture, test, log
  or ledger. The existing scan for the Breathe `prod-…` pattern cannot match
  a hex key, so this rule is procedural: reviewers check for it.
- Every colour from `static/css/tokens.css`; the new pages reuse the
  `.auth-wrap`/`.auth-card` vocabulary the login page already uses, in the
  same three theme states.
- No pre-existing test assertion is weakened. The two add-form tests change
  shape (no password fields to post) and keep their `is_rota_admin` /
  `is_superuser` assertions.
- `rota/services/*`, `cell_state()` and every rota screen are untouched.
  The app's own chrome changes in exactly two places: the login page gains
  links, and the signed-in email in the header becomes a link to the
  Account page.

## 1. Outgoing email

`config/settings.py` reads the standard Django keys from the environment:
`EMAIL_HOST`, `EMAIL_PORT` (default 587), `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` (default on), `DEFAULT_FROM_EMAIL`,
and sets `EMAIL_TIMEOUT = 10` so a stalled relay cannot hold an admin's
save past gunicorn's worker timeout. **`EMAIL_HOST` being set is what
"email is configured" means** — one test, used everywhere below. There is
no console backend for a dev box: with no host, a dev box behaves as
production does and the admin is shown each link — a second definition of
"configured" would contradict the one above. Under pytest, pytest-django's
locmem backend collects them in `mail.outbox`.

Every message the app sends carries `X-Mailjet-TrackClick: 0` and
`X-Mailjet-TrackOpen: 0`. Mailjet rewrites links through `mjt.lu` for click
tracking by default; a password link that arrives as a tracking redirect
looks like phishing and hands a third party the click. The headers are
inert on any other relay. The deploy notes also say to switch tracking off
account-wide in Mailjet, as belt and braces.

Messages are plain text, from `DEFAULT_FROM_EMAIL`, which Mailjet requires
to be a validated sender or domain — the deploy notes recommend an address
on a domain Tom controls (`rota@devachnid.co.uk`, validated by SPF and DKIM
records in Cloudflare DNS). The sending name is "Practice Rota".

**Sending is one function**, `accounts/mail.py::send_password_link(request,
user, *, invite: bool) -> str | None`. It builds the link from the request
(host and scheme, so it is right behind the tunnel and on a dev box alike),
renders the subject and body templates, sends, stamps
`user.password_link_sent_at`, and returns `None`. If email is not
configured, or the send raises (`smtplib.SMTPException`, `OSError`), it
returns the link instead, so the caller can show it. Nothing else in the
app calls `send_mail` directly.

**Deploy check.** In `rota/checks.py`'s existing `@register(deploy=True)`
pattern: a **warning** when `DEBUG` is off and `EMAIL_HOST` is unset
("Invitations and password resets will show as links for the admin to copy
until EMAIL_HOST is set"), and an **error** when `EMAIL_HOST` is set and
`DEFAULT_FROM_EMAIL` is Django's `webmaster@localhost` default.

**Dashboard.** `setup_steps()` gains a ninth step, "Outgoing email", done
when email is configured; its detail names the env keys. The health panel
is unchanged.

## 2. Invitations

**Model.** `User.password_link_sent_at` (`DateTimeField`, null) — migration
`accounts 0003`. One field serves both invitations and resets: for an
account with no usable password it is when the invitation went out; for
any account it drives the throttle in §4.

**The add form** is email and *Rota admin*, nothing else, for superusers
and rota admins alike. Saving creates the account with an unusable
password and sends the invitation in the same request. The admin then sees
one of three messages: *Invitation sent to x@y* · *Email isn't set up — copy
this link and send it to x@y yourself:* followed by the link · *Sending to
x@y failed (<reason>) — copy this link and send it yourself:* followed by
the link. The link is shown once, in that message, and nowhere else.

**The change page** shows the account's state as a read-only field:
*Invited 3 Sep, link expires 10 Sep* / *Invitation expired — send another* /
*Set up*. The submit line carries one extra button, POST like the rest of
the form: **Send invitation again** when there is no usable password,
**Send password-reset link** when there is. Both call
`send_password_link` and show the same three messages. The changelist
gains a *Set up?* column and a bulk action, **Send invitation or reset
link**, for onboarding a whole practice at once — it skips rows the
requester may not change and reports how many were sent and how many
became links to copy.

**Permissions** follow the existing guards unchanged: a rota admin cannot
see, change or send anything to a superuser's account (403 on a direct
POST); a superuser can. The superuser-only set-password form stays at
`/admin/accounts/user/<pk>/password/`; rota admins no longer have any way
to set a password.

**Typo risk, recorded rather than solved:** an invitation to a mistyped
address lets whoever holds that mailbox set a password for an account
whose email *is* that address. The state field makes an unexpected
"Set up" visible, and deleting the account closes it.

## 3. Setting a password from a link

The link is Django's `PasswordResetTokenGenerator` token at
`/accounts/reset/<uidb64>/<token>/`: single-use, because it is keyed on
the password hash and setting a password changes it; expiring, with
`PASSWORD_RESET_TIMEOUT = 7 days`. Django's confirm view already moves the
token out of the URL and into the session before showing the form, so it
never sits in browser history.

`accounts/views.py::SetPasswordFromLinkView` subclasses
`PasswordResetConfirmView`: it renders `registration/password_reset_confirm.html`
in the app's design system; its heading and copy depend on
`user.has_usable_password()` — *Welcome — choose a password* for an
invitation, *Choose a new password* for a reset; it only resolves **active**
users (Django's default does not check); and it signs the person in on
success (`post_reset_login = True`, backend
`django.contrib.auth.backends.ModelBackend`, landing on
`LOGIN_REDIRECT_URL`). An invalid or expired link renders the same template's
*This link is no longer valid* state with a link to request another.
Password rules are the existing `AUTH_PASSWORD_VALIDATORS`.

## 4. Self-service

- **Forgotten your password?** on the login page →
  `/accounts/password_reset/`. `accounts/views.py::RequestPasswordLinkView`
  subclasses `PasswordResetView` with the app's templates and a form whose
  `get_users` drops Django's usable-password filter, so an expired
  invitation self-heals without an admin, while keeping `is_active`. The
  page after submit says the same thing whether or not the address exists.
- **Throttle.** The form's send goes through `send_password_link`; the
  function silently does nothing when `password_link_sent_at` is within the
  last 5 minutes and the caller is the public form. The admin buttons in §2
  are not throttled but tell the admin when the last link went.
- **Change password** — Django's `/accounts/password_change/` with the app's
  template, reached from the Account page.
- **Account page** at `/accounts/account/` (login required): the signed-in
  email, a *Change password* link, and — on the passkeys branch — the
  passkeys list. The email shown in the header and in the tab bar's More
  sheet becomes the link to it; nothing else moves in the nav.
- `accounts/urls.py` is included at `/accounts/` *before*
  `django.contrib.auth.urls`, so the app's views take the reset names and
  Django's remain for login, logout and password change.

Emails (`templates/registration/`): `invitation_subject.txt` /
`invitation_email.txt` and `password_reset_subject.txt` /
`password_reset_email.txt` — the link, when it expires, who to contact
(the address the admin asks for, from the message context, not a literal),
and "if you weren't expecting this, ignore it".

## 5. Passkeys

**What a person gets:** on the Account page, *Add a passkey* names the
device and runs the browser's prompt; on the login page, *Sign in with a
passkey* lets them in with Face ID, a fingerprint or a phone held to the
laptop, no password typed. A password still exists behind every account —
set from the invitation — and remains the recovery path.

**Model.** `accounts.Passkey` — migration `accounts 0004`: `user` (FK,
`CASCADE`, `related_name="passkeys"`), `credential_id` (base64url text,
unique), `public_key` (base64url text), `sign_count` (positive int),
`transports` (comma-separated text, may be blank), `aaguid` (UUID, null),
`name` (60 chars), `created_at`, `last_used_at` (null). Text, not
`BinaryField`, so rows read plainly in the admin.

**Registration** (signed in): `POST /accounts/passkeys/register/options/`
returns `generate_registration_options` as JSON — RP id is the request host
without port, RP name "Practice Rota", user handle the user's pk as bytes,
`resident_key=REQUIRED` (discoverable, so login needs no email typed),
`user_verification=REQUIRED`, `attestation=NONE`, existing credentials
excluded. The challenge and its issue time go in the session; a
verification more than 5 minutes later, or with no challenge stored, is
refused. `POST /accounts/passkeys/register/` verifies with
`verify_registration_response` and stores the row. The name is what the
person typed; blank falls back to a small AAGUID→name map in
`accounts/passkeys.py` (iCloud Keychain, Google Password Manager, Windows
Hello, 1Password, Bitwarden — a dozen entries, no more), then to "Passkey".

**Login** (anonymous): `POST /accounts/passkeys/login/options/` returns
`generate_authentication_options` with no `allowCredentials` and
`user_verification=REQUIRED`; challenge to the session as above. `POST
/accounts/passkeys/login/` looks the credential id up, refuses an inactive
user, verifies with `verify_authentication_response` against the stored key
and sign count, updates `sign_count` and `last_used_at`, calls
`django.contrib.auth.login(request, user, backend="django.contrib.auth.backends.ModelBackend")`,
and answers `{"next": …}` — `?next=` honoured through
`url_has_allowed_host_and_scheme`, else `LOGIN_REDIRECT_URL`. **axes:** the
`user_logged_in` signal resets the account's counters as it does for a
password login. A failed verification for a *known* credential sends
`user_login_failed` with the account's email so axes counts it; an unknown
credential id is a plain 400. A password lockout does not block a passkey
login — a passkey proves possession, which is the stronger claim — and the
docs say so.

**Management.** The Account page lists passkeys (name, added, last used)
with a POST *Remove* per row, own rows only. The admin's login-account
change page gets a read-only `Passkey` inline with delete, so a rota admin
can revoke a lost phone; it inherits the superuser guard from its parent.

**Front end:** `static/js/passkeys.js`, vanilla, no library — base64url
helpers, `fetch` with the CSRF token read from the form's hidden input
(`CSRF_COOKIE_HTTPONLY` is on, so the cookie is not readable), and feature
detection: the buttons render only when `window.PublicKeyCredential`
exists. Errors from the browser prompt (cancelled, no authenticator) show
inline next to the button, never as a page reload. Conditional UI
(passkeys offered in the email field's autofill) is deliberately left out
of this piece.

**Identity.** Passkeys bind to the RP id, which is the domain. Moving the
app off `rota.devachnid.co.uk` means every passkey is re-enrolled; the
upgrade notes record this beside the unfold ones.

## 6. Security notes

- The reset link is the only secret the emails carry; the relay sees it in
  transit, which is true of any relay, and tracking off means Mailjet keeps
  no record of the click.
- Anti-enumeration is Django's: the reset form's response does not depend
  on whether the address exists. Its *timing* does, because sending is
  synchronous; accepted for a practice-sized user base, and noted.
- `login()` cycles the session key (Django) on both link and passkey sign-in.
- Inactive accounts: no invitations sent, no links honoured, no passkey
  sign-in.
- The on-screen link fallback shows a rota admin a credential-equivalent
  for one account, once — the same trust the old form gave them for every
  account, every time.

## 7. Testing

Each behaviour above has a test that exercises the mechanism, not a
comment about it; where a guard is added, the plan removes the mechanism
and watches the guard fail.

- Every send lands in `mail.outbox`: recipient, subject, the two tracking
  headers, and a link that parses back into a uid and a token the
  generator accepts.
- Invite → follow link → set password → signed in → `/rota/`. Used link
  refused. Expired link (`PASSWORD_RESET_TIMEOUT` overridden to 0) shows
  the no-longer-valid state.
- Unconfigured email → message carries the link; configured and the
  backend raises (monkeypatched) → message carries the link and the reason.
- Rota admin POSTs a send for a superuser → 403 and no mail; superuser →
  sent. Bulk action skips superuser rows for a rota admin.
- Public reset for an unset account sends; a second within 5 minutes sends
  nothing; inactive account sends nothing; unknown address sends nothing
  and renders the same page.
- Deploy check warns and errors as §1 says; dashboard step flips with
  `EMAIL_HOST`.
- Passkeys: one real registration and one real authentication response
  from py_webauthn's own test vectors (Apache-2.0), with their challenge
  seeded into the session and RP id `localhost`, run through the real
  verify path — so the wiring is proven against real authenticator output,
  not a stub. View tests otherwise stub the verifier at the module
  boundary. Remove is own-rows-only; the admin inline follows the superuser
  guard; a failed known-credential verification fires `user_login_failed`.
- Real-device passkey enrolment and sign-in are Tom's to check on staging;
  Chrome's DevTools virtual authenticator is the fallback if the browser
  tools are available at the time.

## 8. Documentation

- `docs/admin/people.md` › Login accounts: the invite flow, the three
  messages, what the state field means, the bulk action, and — on the
  passkeys branch — revoking a passkey.
- `README.md` › Deploy: the six email keys for `/etc/rota.env`, the Mailjet
  setup in four lines (validate the sender domain with SPF and DKIM in
  Cloudflare, create an API key, turn click and open tracking off, paste
  key and secret), and the note that the app works without any of it.
- `docs/admin/upgrading-unfold.md` gains a sibling paragraph on the RP-id
  binding (passkeys branch).

## 9. What Tom does

Before the invites branch can send real mail on staging: a Mailjet account,
a validated sender (`rota@devachnid.co.uk` or the domain), tracking off,
and the six keys into `/etc/rota.env`. None of it blocks the merge — until
`EMAIL_HOST` is set the admin copies links, and the dashboard says so.

## Out of scope, recorded

Conditional-UI passkey autofill; passkey enrolment from the invitation
page itself (password first, passkey second); passkey-only accounts;
sending mail asynchronously; SMS.

## Amended after the final review (2026-09-04)

- §1's console backend for `DEBUG` is gone: every send path returns before
  the backend when `EMAIL_HOST` is unset, so it could never have fired, and
  it contradicted "`EMAIL_HOST` being set is what configured means".
- §4's "tell the admin when the last link went" is the state field's
  *Set up — last link sent 4 Sep 14:02* for an account with a password.
- The link an admin is shown to copy stays a clickable `<a>`: on a phone a
  long-press offers *Copy link*, which is the point; clicking it instead
  lands on someone else's set-password page, which is visible and undone by
  logging out.

## Amended after staging (2026-09-04, Tom)

- §2's password hash field is gone from every change page, a superuser's
  included — it added nothing. The superuser-only direct set-password view
  stays reachable by URL, unlinked, for emergencies.
- The *Staff status* toggle is gone and `is_rota_admin` is labelled
  **Admin status**. Django's `is_staff` is now derived on save (admin status
  or superuser) rather than set by hand: its only effect here is unfold's
  command palette, which previously never appeared for an invited rota
  admin, and Django's own help text under the toggle claimed it controlled
  admin login, which in this app it never did.
- §8's passkeys-and-domain paragraph lives in README › Deploy (where a
  domain change is done) and docs/admin/people.md, not in
  upgrading-unfold.md — that page is about unfold.
- Found by the passkeys branch's final review: with a custom `USERNAME_FIELD`,
  django-axes keyed attempts on `credentials["email"]` while Django's login
  form sends `credentials["username"]`, so the username half of the lockout
  had never locked anything. `AXES_USERNAME_FORM_FIELD = "username"` fixes
  both ways in; a test with axes enabled now asserts the row carries the
  email. A duplicate credential id is refused as *That passkey is already
  registered here.*; a credential id over 1023 bytes is refused; the
  browser's timeout matches the five-minute challenge.
