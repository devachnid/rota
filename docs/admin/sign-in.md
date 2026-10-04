# Signing in with the practice account

**Where:** `/etc/rota.env` (environment variables). The one thing in the
admin is each login account's **Practice account id**, which sign-in sets
itself — see [What happens on first sign-in](#what-happens-on-first-sign-in).

The practice's HR system (`practice-hr`) is an OpenID Connect provider. Once
it is configured, the rota's login page offers **Sign in with the practice
account** and nothing else: a person authenticates against HR, and the rota
trusts who HR says they are. Nothing about this is required — with no
`PRACTICE_HR_URL` set the login page is exactly as it was, local password
(and passkey) only.

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

The HR system's `sub` (its own id for the person's login), `email`,
`employee_id` and `admin` claims come back after authentication.

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
- **Superusers sign in this way too**, like everyone else: the superuser
  needs a login on the HR system with the same email
  ([Moving the rota's logins to the HR system](#moving-the-rotas-logins-to-the-hr-system)
  makes one). **Superuser status** itself stays a rota flag, set only here
  by a superuser, for the feedback emails and the sign-in records in the
  admin's System group. Like anyone's, the superuser's rota account is
  bound by the *first* practice-account sign-in whose email matches it —
  so the superuser should sign in through HR promptly after the switch,
  before anyone else's HR login could be given that email.

If someone's login on the HR system is replaced by a new one, they cannot
sign in with the practice account until a superuser clears **Practice
account id** on their rota account; their next sign-in binds the new one.

`employee_id` is read but not stored: it exists to identify the person on
the HR side, not to grant anything here.

**Rota admin comes from the `admin` claim**, at every sign-in, superusers
included. The HR system sends it as true for a login with **Admin of rota**
ticked under **Apps** on its Login accounts page, and false otherwise; an
HR system too old to send it at all counts as false. So whether someone is
a rota admin is set on the HR system, and **Admin status** on the rota's
**People › Login accounts** page is read-only while `PRACTICE_HR_URL` is
set. A change there takes effect at the person's next sign-in to the rota.
Tick **Admin of rota** for the superuser's HR login too, or their first
practice-account sign-in takes rota admin away from them. Whether someone
is linked to a Clinician is still set here — see
[Login accounts](people.md#login-accounts).

## Moving the rota's logins to the HR system

Before turning the practice account on, the rota's logins can be copied to
the HR system, so nobody has to be set up there by hand and everyone keeps
the password they have:

    deploy/manage export_logins --file /var/lib/rota/rota-logins.json

writes every login account — inactive ones and superusers too — with its
email, its password exactly as stored (a one-way hash, never the password
itself), and whether it is active, a rota admin and a superuser.
`deploy/manage` runs it as the `rota` user, so the file goes in the rota's
own directory, which root can read too. It is created readable by its owner
only, and the command refuses to write over a file that is already there. It
prints how many logins it wrote and where, nothing else. Copy the file to
the HR box, run the HR system's `import_logins` on it (that project's
sign-in docs, *Migrating logins from the rota*), then delete both copies:
the hashes in it are worth guarding like the database.

## Signing out

With `PRACTICE_HR_URL` set, **Log out** (and the admin's own) signs the
person out of the rota and then sends them to the HR system's sign-out,
which ends their session there too and returns them to the rota's login
page. Without that second step, on a shared PC, the next person to press
**Sign in with the practice account** would be signed straight in as the
last one: the HR system skips its consent screen for the rota, and its
session was still open. Someone who signed in with the practice account is
signed out of HR without a question; a session that began some other way
(with the rota password, before `PRACTICE_HR_URL` was set) is asked by HR
whether to sign out there too.

## There is no rota password while the practice account is on

With `PRACTICE_HR_URL` set, the login page offers **Sign in with the
practice account** and nothing else: no password form, no *Forgotten your
password?*, no passkey button. Everyone signs in through the HR system,
superusers included. Their password, passkeys, lockout and leaving date
all live there, so the rota never checks a password at all:

- **A password sent to the login form anyway** — an old bookmark, a
  password manager — is refused before it is looked at: *"Sign in with the
  practice account."* It reads the same whether the password was right,
  wrong, or the address has no account. Because no password is checked,
  nothing is counted towards the login lockout: staff typing their old rota
  password out of habit cannot lock the surgery's address (and the
  practice-account sign-in with it) out.
- **Password links** — *Forgotten your password?*, and invitations or reset
  links sent from **Login accounts** — work for nobody, and **Change
  password** is gone too: a password set here, from a borrowed session say,
  would work again the day the practice account is turned off. The reset form
  sends nothing, and any link, even one sent before `PRACTICE_HR_URL` was
  set, opens the *link no longer valid* page instead of signing anyone in.
  Otherwise a leaver disabled on the HR system would keep a way in here.
  Adding a login account sends no invitation while the practice account is
  on — the admin says *"This person signs in with the practice account; no
  invitation is needed."* — and an account is made anyway at the person's
  first practice-account sign-in.
- **A lockout** left over from before shows *Too many attempts* with only
  the **Sign in with the practice account** button: no passkey or
  password-link routes, since neither exists.
- **Passkeys are retired.** The rota's passkey sign-in and enrolment
  answer *not found*, and the **Account** page replaces its password button
  and Passkeys section with *"You sign in with the practice account.
  Passwords and passkeys are managed on the HR system."*, linking to the
  HR system's own account page. Passkeys already enrolled are kept, not
  deleted, and work again if `PRACTICE_HR_URL` is removed.

With no `PRACTICE_HR_URL` the page is as it always was, the password form,
its links and passkeys open to everyone.

## If the HR system is unreachable

Nobody can sign in to the rota while the HR system is down, the superuser
included. To let people back in, remove the `PRACTICE_HR_URL` line from
`/etc/rota.env` and restart the rota (`systemctl restart rota`). The local
password form, *Forgotten your password?* and passkeys return for the
accounts that still have them: the superuser's, and anyone whose rota
password or passkeys were never cleared. Someone who has only ever signed in
with the practice account has no rota password; a password link from
**Login accounts** gives them one. Rota admin stays as the last sign-in
left it, and **Admin status** can be ticked here again meanwhile.

**While the line is out, the HR system is no longer the gatekeeper.** A
leaver deactivated only on HR can sign in with a rota password or passkey
they still have here. Untick **Active** on their rota login account too,
for every leaver, until the HR system is back.

Put the line back, and restart, once the HR system is up. Everyone is back
to the practice account at their next sign-in, and rota admin follows the
HR system again from then on.
