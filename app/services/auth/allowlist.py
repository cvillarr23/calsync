from app.services.auth.identity import Identity
from app.settings import Settings


def is_allowed(settings: Settings, identity: Identity) -> bool:
    """A verified email, on `CALSYNC_ALLOWED_EMAILS` when that list is set.

    An unverified address could belong to anyone, so it never passes, even with no list.
    """
    if not identity.email_verified:
        return False
    return not settings.allowed_emails or identity.email.lower() in settings.allowed_emails
