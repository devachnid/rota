from django.contrib.admin.apps import AdminConfig


class RotaAdminConfig(AdminConfig):
    """Makes `admin.site` an instance of our RotaAdminSite — an unfold site
    with our access rule — so every @admin.register in every app (ours,
    django-axes', auth's) lands on it. Unfold's own DefaultAppConfig would
    replace admin.site with a plain UnfoldAdminSite; we use its
    BasicAppConfig instead and let Django's default_site mechanism do the
    replacing with our subclass."""
    default_site = "rota.admin_site.RotaAdminSite"
