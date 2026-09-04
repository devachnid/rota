from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        user = self.model(email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

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

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        # is_staff keeps Django's meaning — "can log into this admin site" —
        # but nobody sets it by hand: it follows admin status, so unfold's
        # command palette (which checks is_staff) appears for exactly the
        # people who can use the admin. RotaAdminSite itself admits by
        # is_rota_admin, never by this flag.
        self.is_staff = self.is_rota_admin or self.is_superuser
        super().save(*args, **kwargs)
