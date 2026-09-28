# Signing in with the practice account

**Where:** `/etc/rota.env` (environment variables only — nothing here is set
in the admin).

The practice's HR system (`practice-hr`) is an OpenID Connect provider. Once
it is configured, the rota's login page offers **Sign in with the practice
account**: a person authenticates against HR, and the rota trusts who HR
says they are. Nothing about this is required — with no `PRACTICE_HR_URL`
set the login page is exactly as it was, local password (and passkey)
only.

## The four environment variables

```
PRACTICE_HR_URL=https://hr.example.org
OIDC_RP_CLIENT_ID=…
OIDC_RP_CLIENT_SECRET=…
```

`PRACTICE_HR_URL` is the HR system's base URL, no trailing slash needed —
the rota builds `/o/authorize/`, `/o/token/`, `/o/userinfo/` and
`/o/.well-known/jwks.json` from it. `OIDC_RP_CLIENT_ID` and
`OIDC_RP_CLIENT_SECRET` come from registering the rota as a client on the
HR box (below). Add all three to `/etc/rota.env` and restart gunicorn — see
the README's Deploy section for the file's format (root-only, `chmod 600`,
no unquoted `<` or trailing comments).

A fourth pair of settings, `OIDC_RP_SIGN_ALGO`, `OIDC_RP_SCOPES` and PKCE, is
fixed in `config/settings.py` and never needs changing: RS256 signatures,
the `openid email` scope, and PKCE are required, matching what the HR
system's provider issues.

## Registering the rota as a client

This step runs on the **HR box**, not here — its `manage.py` opens its own
database, not the rota's. From the `practice-hr` checkout there, its
`register_oidc_client` command takes `--name rota` and `--redirect-uri`
(the exact URL the rota will be sent back to,
`https://rota.example.org/oidc/callback/`); see that project's own deploy
docs for how commands are run on that box.

It prints a `client_id` and a `client_secret` **once** — the secret is
stored hashed on the HR side and cannot be shown again. Paste both into
`/etc/rota.env` as `OIDC_RP_CLIENT_ID` and `OIDC_RP_CLIENT_SECRET`, then
restart the rota (`systemctl restart rota`). If the secret is lost, run the
command again with the same `--name`: it replaces the registration rather
than creating a second one.

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

## The rota's password form is for the superuser

With `PRACTICE_HR_URL` set, the login page leads with **Sign in with the
practice account**, and the rota's own password form is folded away under
**Rota password (superusers only)**. It is for the superuser created by
`createsuperuser` — that account has no HR record and never will — and it
is the way in if HR is ever unreachable. Anyone else's password is refused
there (`accounts/backends.py`), even a right one, and the refusal counts
towards the login lockout like a wrong password: everyone else's password,
lockout and leaving date live on the HR system.

With no `PRACTICE_HR_URL` the page is as it always was, the password form
open for everyone. Passkeys, described in
[Login accounts](people.md#signing-in-and-lockouts), work either way until
they are retired.
