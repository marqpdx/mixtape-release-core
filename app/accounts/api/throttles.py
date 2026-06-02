from rest_framework.throttling import AnonRateThrottle


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class SignupThrottle(AnonRateThrottle):
    scope = "signup"


class PasswordResetThrottle(AnonRateThrottle):
    scope = "password_reset"


class TokenRefreshThrottle(AnonRateThrottle):
    scope = "token_refresh"


class IntakeThrottle(AnonRateThrottle):
    scope = "intake"


class IntakeUploadThrottle(AnonRateThrottle):
    scope = "intake_upload"


class InviteThrottle(AnonRateThrottle):
    scope = "invite"
