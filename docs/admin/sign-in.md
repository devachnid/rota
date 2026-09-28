# Signing in with the practice account

**Where:** `/etc/rota.env` (environment variables only — nothing here is set
in the admin).

The practice's HR system (`practice-hr`) is an OpenID Connect provider. Once
it is configured, the rota's login page offers **Sign in with the practice
account** above the local password form: a person authenticates against HR,
and the rota trusts its `email` claim. Nothing about this is required —
with no `PRACTICE_HR_URL` set the login page is exactly as it was, local
password (and passkey) only.

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

The HR system's `email` and `employee_id` claims come back after
authentication. The rota matches `email` against existing login accounts,
case-insensitively, exactly like the local login form does. A match signs
that person in as themselves. No match creates a new login account for that
email, with no usable password — they can never fall back to a local
password sign-in unless an admin sets one — and `is_active=True`.
`employee_id` is read but not stored: it exists to identify the person on
the HR side, not to grant anything here.

**`is_rota_admin` is never touched by sign-in.** A new account created this
way is not an admin. Whether someone is a rota admin, and whether they are
linked to a Clinician, are both still set by hand in **People › Login
accounts** — see [Login accounts](people.md#login-accounts). Signing in with
the practice account only proves who someone is; what they can do in the
rota is exactly what it always was.

## The local password form stays

The password form below the practice-account link never goes away. It is
how the superuser created by `createsuperuser` signs in — that account has
no HR record and never will — and it is the fallback if HR is ever
unreachable. Passkeys, described in
[Login accounts](people.md#signing-in-and-lockouts), work alongside both.
