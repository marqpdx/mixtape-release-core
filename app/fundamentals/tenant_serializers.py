"""
TenantScopedSerializerMixin — validates tenant context at serializer init.

Raises at construction time (before any field validation) if no tenant is
in context. This surfaces the error as close to the cause as possible rather
than allowing a partially-constructed serializer to operate without a tenant.

Usage:
    class WritingPieceSerializer(TenantScopedSerializerMixin, ModelSerializer):
        class Meta:
            model = WritingPiece
            fields = [...]

The mixin must come before ModelSerializer in the MRO so __init__ runs first.
"""
from fundamentals.managers import MissingTenantContextError
from mixtape.tenant import get_current_tenant


class TenantScopedSerializerMixin:

    def __init__(self, *args, **kwargs):
        tenant = get_current_tenant()
        if tenant is None:
            raise MissingTenantContextError(
                f"{self.__class__.__name__} requires tenant context. "
                "Ensure TenantContextRequired is in the view's permission_classes "
                "and TenantMiddleware is active."
            )
        self._tenant = tenant
        super().__init__(*args, **kwargs)

    @property
    def current_tenant(self):
        return self._tenant
