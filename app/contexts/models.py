from django.db import models

# Create your models here.
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from fundamentals.models import BaseData

class ContextDefinition(BaseData):
    """
    The 'idea' vocabulary for contexts, e.g.:
      - course-default-chat
      - group-default-chat
      - cohort-chat
      - office-hours
    """
    slug = models.SlugField(unique=True)        # machine name
    name = models.CharField(max_length=120)     # human-readable label
    description = models.TextField(blank=True)

    def __str__(self):
        return self.slug


class ContextManager(models.Manager):
    def for_model_instance(self, definition_slug, instance):
        """
        Get (or filter for) contexts for a specific model instance and idea/definition.
        """
        ct = ContentType.objects.get_for_model(instance.__class__)
        return self.filter(
            definition__slug=definition_slug,
            content_type=ct,
            object_id=str(instance.pk),
        )

    def defaults_for_instance(self, instance, contains="default"):
        """
        Get all *contexts* for an instance whose definition slug contains a marker
        (e.g., 'default'). This does NOT guarantee a default conversation exists;
        it’s a vocabulary filter. Use Context.get_default_conversation() to resolve.
        """
        ct = ContentType.objects.get_for_model(instance.__class__)
        return self.filter(
            content_type=ct,
            object_id=str(instance.pk),
            definition__slug__icontains=contains,
        )


class Context(BaseData):
    """
    Context = (idea/definition) + (anchor: a concrete object via GFK)
    Example: definition='course-default-chat' @ Course#42
    """
    definition = models.ForeignKey(
        ContextDefinition, on_delete=models.PROTECT, related_name="contexts"
    )

    # Generic anchor
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64, db_index=True)  # str supports UUID or int
    anchor = GenericForeignKey("content_type", "object_id")

    label = models.CharField(max_length=140, blank=True)  # optional display label
    meta = models.JSONField(default=dict, blank=True)

    objects = ContextManager()

    class Meta:
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["definition", "content_type"]),
        ]
        unique_together = [("definition", "content_type", "object_id")]

    def __str__(self):
        return f"{self.definition.slug} @ {self.content_type.model}:{self.object_id}"

    # ---------- convenience ----------
    @classmethod
    def for_anchor(cls, definition_slug, anchor_obj, label=None):
        """
        Get or create a Context for (definition_slug, anchor).
        """
        definition = ContextDefinition.objects.get(slug=definition_slug)
        ct = ContentType.objects.get_for_model(anchor_obj.__class__)
        ctx, _ = cls.objects.get_or_create(
            definition=definition,
            content_type=ct,
            object_id=str(anchor_obj.pk),
            defaults={"label": label or str(anchor_obj)},
        )
        return ctx

    def get_default_conversation(self):
        """
        Resolve the default Conversation for this context (if any).
        """
        rel = self.conversation_contexts.filter(is_default_for_context=True).select_related("conversation").first()
        return rel.conversation if rel else None

    def create_default_conversation(self, **conversation_kwargs):
        """
        Create and bind a default Conversation to this context.
        """
        # late import to avoid cycles
        from chat.models import Conversation, ConversationContext

        if self.get_default_conversation():
            raise ValidationError(f"Context {self} already has a default conversation")

        conversation = Conversation.objects.create(**conversation_kwargs)
        ConversationContext.objects.create(
            conversation=conversation,
            context=self,
            is_default_for_context=True,
        )
        return conversation
