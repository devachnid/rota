"""Sign in with the practice account: the HR system is the OpenID Connect
provider. On first sign-in the email claim is matched to an existing rota
user, case-insensitively, or a user is created with no usable password.
is_rota_admin stays local to the rota."""

from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from .models import User


class PracticeAccountBackend(OIDCAuthenticationBackend):
    def filter_users_by_claims(self, claims):
        email = claims.get("email")
        if not email:
            return User.objects.none()
        return User.objects.filter(email__iexact=email)

    def create_user(self, claims):
        user = User(email=claims["email"])
        user.set_unusable_password()
        user.save()
        return user

    def update_user(self, user, claims):
        return user
