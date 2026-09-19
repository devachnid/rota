from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def get_by_natural_key(self, email):
        """The login lookup — ModelBackend calls this with whatever was
        typed. An address is not case-sensitive to anyone who uses one, so
        neither is this; the constraint below is what makes `get` safe."""
        return self.get(email__iexact=email)

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_rota_admin", True)
        return self._create(email, password, **extra)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    is_rota_admin = models.BooleanField(
        "admin status", default=False,
        help_text="Can use this admin, publish weeks, run the fill and approve requests.",
    )

    # When the last invitation or password-reset link was handed out — sent,
    # or shown to an admin to copy. For an account with no usable password
    # this is its invitation date; for any account it throttles the public
    # reset form (accounts/mail.py). Null until the first link.
    password_link_sent_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta(AbstractUser.Meta):
        verbose_name = "login account"
        verbose_name_plural = "login accounts"
        constraints = [
            # `unique=True` on the field is exact-case; this is the one that
            # matters. Two accounts differing only by case would make the
            # case-insensitive login lookup ambiguous, and are two logins
            # for one person besides. The message is what the admin's add
            # form shows when it validates the constraint.
            models.UniqueConstraint(
                Lower("email"), name="accounts_user_email_ci_unique",
                violation_error_message="A login account with this email address already exists.",
            ),
        ]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        # Django's own normalisation, applied wherever the row is written
        # and not only in create_user: the domain is lower-cased (it is
        # never case-sensitive), the local part is kept as given.
        self.email = self.__class__.objects.normalize_email(self.email)
        # is_staff keeps Django's meaning — "can log into this admin site" —
        # but nobody sets it by hand: it follows admin status, so unfold's
        # command palette (which checks is_staff) appears for exactly the
        # people who can use the admin. RotaAdminSite itself admits by
        # is_rota_admin, never by this flag.
        self.is_staff = self.is_rota_admin or self.is_superuser
        super().save(*args, **kwargs)


class Passkey(models.Model):
    """A WebAuthn credential — a person's phone, laptop or security key.
    Text rather than BinaryField so rows read plainly in the admin; the
    ids are base64url exactly as the browser sends them, so a lookup by
    the browser's `credential.id` is a plain equality."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="passkeys")
    credential_id = models.CharField(max_length=1024, unique=True)
    public_key = models.TextField()
    sign_count = models.PositiveIntegerField(default=0)
    transports = models.CharField(max_length=200, blank=True)
    aaguid = models.UUIDField(null=True, blank=True)
    name = models.CharField(max_length=60)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at",)
        verbose_name = "passkey"

    def __str__(self):
        return f"{self.name} ({self.user.email})"
