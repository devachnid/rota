# Signing in with the practice account

**Where:** `/etc/rota.env` (environment variables). The one thing in the
admin is each login account's **Practice account id**, which sign-in sets
itself — see [What happens on first sign-in](#what-happens-on-first-sign-in).

The practice's HR system (`practice-hr`) is an OpenID Connect provider. Once
it is configured, the rota's login page offers **Sign in with the practice
account**: a person authenticates against HR, and the rota trusts who HR
says they are. Nothing about this is required — with no `PRACTICE_HR_URL`
set the login page is exactly as it was, local password (and passkey)
only.

## The three environment variables

```
PRACTICE_HR_URL=https://hr.example.org
OIDC_RP_CLIENT_ID=…
OIDC_RP_CLIENT_SECRET=…
```

`PRACTICE_HR_URL` is the HR system's base URL, no trailing slash needed —
the rota builds `/o/authorize/`, `/o/token/`, `/o/userinfo/`,
`/o/.well-known/jwks.json` and the sign-out address `/o/logout/` from it. `OIDC_RP_CLIENT_ID` and
`OIDC_RP_CLIENT_SECRET` come from registering the rota as a client on the
HR box (below). Add all three to `/etc/rota.env` and restart gunicorn — see
the README's Deploy section for the file's format (root-only, `chmod 600`,
no unquoted `<` or trailing comments).

The rest is fixed in `config/settings.py` and never needs changing: RS256
signatures (`OIDC_RP_SIGN_ALGO`), the `openid email` scope
(`OIDC_RP_SCOPES`), PKCE, and keeping the ID token in the session
(`OIDC_STORE_ID_TOKEN`) for signing out — matching what the HR system's
provider issues and expects.

## Registering the rota as a client

This step runs on the **HR box**, not here — its `manage.py` opens its own
database, not the rota's. From the `practice-hr` checkout there, its
`register_oidc_client` command takes `--name rota`, `--redirect-uri` (the
exact URL the rota will be sent back to after signing in,
`https://rota.example.org/oidc/callback/`) and, optionally,
`--post-logout-redirect-uri` (where signing out of the rota lands after
signing out of HR too). Left out, that is the redirect URI's origin plus
`/accounts/login/` — `https://rota.example.org/accounts/login/`, the rota's
login page — which is what the rota sends; pass it only if the rota is
reached at a different address. See that project's own deploy docs for how
commands are run on that box.

It prints a `client_id` and a `client_secret` **once** — the secret is
stored hashed on the HR side and cannot be shown again. Paste both into
`/etc/rota.env` as `OIDC_RP_CLIENT_ID` and `OIDC_RP_CLIENT_SECRET`, then
restart the rota (`systemctl restart rota`). If the secret is lost, run the
command again with the same `--name` and add `--rotate`: that prints a new
secret, and the old one stops working at once, so update
`OIDC_RP_CLIENT_SECRET` straight away. Without `--rotate`, running it again
only updates the redirect addresses and keeps the secret; it never creates
a second registration.

## What happens on first sign-in

The HR system's `sub` (its own id for the person's login), `email` and
`employee_id` claims come back after authentication.

- **The first time**, the rota matches `email` against existing login
  accounts, case-insensitively, exactly like the local login form does. A
  match signs that person in as themselves and stores the HR system's `sub`
  on their account (**Practice account id**, shown to superusers in the
  account's System section). No match creates a new login account for that
  email, with no usable password, `is_active=True`, and the `sub` stored.
- **Every time after that**, the rota matches on the stored `sub` alone. An
  email changed on the HR side — by accident, or by an HR admin trying to
  sign in as someone else — cannot move anyone into a different rota
  account: an account already bound to one `sub` is never matched by email
  for another, and no second account is made for its address. That sign-in
  is refused, and the person lands back on the login page.
- **The superuser is never signed in this way**, whatever the HR system
  says. It signs in with the rota's own password form (below).

If someone's login on the HR system is replaced by a new one, they cannot
sign in with the practice account until a superuser clears **Practice
account id** on their rota account; their next sign-in binds the new one.

`employee_id` is read but not stored: it exists to identify the person on
the HR side, not to grant anything here.

**`is_rota_admin` is never touched by sign-in.** A new account created this
way is not an admin. Whether someone is a rota admin, and whether they are
linked to a Clinician, are both still set by hand in **People › Login
accounts** — see [Login accounts](people.md#login-accounts). Signing in with
the practice account only proves who someone is; what they can do in the
rota is exactly what it always was.

## Signing out

With `PRACTICE_HR_URL` set, **Log out** (and the admin's own) signs the
person out of the rota and then sends them to the HR system's sign-out,
which ends their session there too and returns them to the rota's login
page. Without that second step, on a shared PC, the next person to press
**Sign in with the practice account** would be signed straight in as the
last one: the HR system skips its consent screen for the rota, and its
session was still open. Someone who signed in with the practice account is
signed out of HR without a question; anyone else (the superuser, with the
rota password) is asked by HR whether to sign out there too.

## The rota's password form is for the superuser

With `PRACTICE_HR_URL` set, the login page leads with **Sign in with the
practice account**, and the rota's own password form is folded away under
**Rota password (superusers only)**, with **Forgotten your password?**
beside it. It is for the superuser created by `createsuperuser` — that
account has no HR record and never will — and it is the way in if HR is
ever unreachable. Everyone else's password, lockout and leaving date live
on the HR system, so the rota never checks their password at all:

- **The login form** turns anyone but the superuser away before looking at
  the password — *"Sign in with the practice account; the rota password is
  for the superuser only."* — and it reads the same whether the password
  was right, wrong, or the address has no account. Because no password is
  checked, nothing is counted towards the login lockout: staff typing their
  old rota password out of habit cannot lock the surgery's address (and the
  superuser, and the practice-account sign-in with it) out. The superuser's
  own wrong passwords still count, as before.
- **Password links** — *Forgotten your password?*, and invitations or reset
  links sent from **Login accounts** — work for the superuser only. The
  reset form sends nobody else anything, and a link for anyone else, even
  one sent before `PRACTICE_HR_URL` was set, opens the *link no longer
  valid* page instead of signing them in. Otherwise a leaver disabled on
  the HR system would keep a way in here. Sending an invitation to a new
  account from the admin is therefore pointless while the practice account
  is on: the account is made for them at their first practice-account
  sign-in.
- **Adding a passkey** more than ten minutes after signing in asks the
  superuser for their password, as before; anyone else is asked to sign in
  again with the practice account first, and a password sent anyway is
  refused without being checked.

With no `PRACTICE_HR_URL` the page is as it always was, the password form
and its links open to everyone. Passkeys, described in
[Login accounts](people.md#signing-in-and-lockouts), still sign in either
way until they are retired.
