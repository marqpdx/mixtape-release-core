import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class BusinessProspect(models.Model):
    STATUS_CHOICES = [
        ("new", "New"),
        ("contacted", "Contacted"),
        ("intake_started", "Intake Started"),
        ("meeting_scheduled", "Meeting Scheduled"),
        ("proposal_stage", "Proposal Stage"),
        ("won", "Won"),
        ("lost", "Lost"),
        ("archived", "Archived"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=300)
    slug = models.SlugField(unique=True)
    business_type = models.CharField(max_length=200, blank=True)
    website = models.URLField(blank=True)
    primary_contact_name = models.CharField(max_length=200, blank=True)
    primary_contact_email = models.EmailField(blank=True)
    primary_contact_phone = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="new")
    summary = models.TextField(blank=True)
    org_description = models.TextField(blank=True)
    knowledge_goal = models.TextField(blank=True)
    converted_to_group = models.ForeignKey(
        "groups.Group",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="prospect_source",
    )
    sponsor_content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="sponsored_prospects",
    )
    sponsor_object_id = models.UUIDField(null=True, blank=True)
    sponsor = GenericForeignKey("sponsor_content_type", "sponsor_object_id")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ProspectIntakeSession(models.Model):
    MODE_CHOICES = [
        ("pre_meeting", "Pre-Meeting"),
        ("guided_live", "Guided Live"),
        ("hybrid", "Hybrid"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("in_progress", "In Progress"),
        ("submitted", "Submitted"),
        ("reviewed", "Reviewed"),
    ]
    ACCESS_CHOICES = [
        ("token_only", "Token Only"),
        ("authenticated", "Authenticated"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prospect = models.ForeignKey(BusinessProspect, on_delete=models.CASCADE, related_name="sessions")
    mode = models.CharField(max_length=30, choices=MODE_CHOICES, default="pre_meeting")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    access_mode = models.CharField(max_length=20, choices=ACCESS_CHOICES, default="token_only")
    resume_token = models.UUIDField(unique=True, default=uuid.uuid4)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    notify_on_submit = models.BooleanField(default=True)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_intake_sessions",
    )
    meeting_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.prospect.name} — {self.mode} ({self.status})"


class ProspectQuestion(models.Model):
    KIND_CHOICES = [
        ("long_text", "Long Text"),
        ("voice_or_text", "Voice or Text"),
        ("structured_followup", "Structured Followup"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prompt = models.TextField()
    help_text = models.TextField(blank=True)
    order_index = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    question_kind = models.CharField(max_length=30, choices=KIND_CHOICES, default="long_text")
    triggers_persona_creation = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order_index"]

    def __str__(self):
        return f"{self.order_index}. {self.prompt[:80]}"


class ProspectResponse(models.Model):
    KIND_CHOICES = [
        ("typed", "Typed"),
        ("file", "File"),
        ("voice", "Voice"),
    ]
    FILE_KIND_CHOICES = [
        ("md", "Markdown"),
        ("pdf", "PDF"),
        ("docx", "Word Document"),
        ("other", "Other"),
    ]
    PROCESSING_STATUS_CHOICES = [
        ("done", "Done"),
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    intake_session = models.ForeignKey(ProspectIntakeSession, on_delete=models.CASCADE, related_name="responses")
    question = models.ForeignKey(ProspectQuestion, on_delete=models.CASCADE, related_name="responses")
    question_prompt_snapshot = models.TextField()
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="typed")
    response_text = models.TextField(blank=True)
    source_file = models.FileField(upload_to="prospects/intake/", null=True, blank=True)
    file_kind = models.CharField(max_length=10, choices=FILE_KIND_CHOICES, blank=True)
    processing_status = models.CharField(
        max_length=15, choices=PROCESSING_STATUS_CHOICES, default="done"
    )
    processing_error = models.TextField(blank=True)
    human_refined_text = models.TextField(null=True, blank=True)
    ai_summary_text = models.TextField(null=True, blank=True)
    transcript_text = models.TextField(null=True, blank=True)
    audio_file = models.FileField(upload_to="prospects/audio/", null=True, blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.intake_session} — Q{self.question.order_index} ({self.kind})"


class ProspectInsight(models.Model):
    SOURCE_CHOICES = [
        ("human", "Human"),
        ("ai_assisted", "AI Assisted"),
        ("ai_generated", "AI Generated"),
    ]
    KIND_CHOICES = [
        ("pain_point", "Pain Point"),
        ("opportunity", "Opportunity"),
        ("canon_domain", "Canon Domain"),
        ("tone_signal", "Tone Signal"),
        ("followup_question", "Followup Question"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prospect = models.ForeignKey(BusinessProspect, on_delete=models.CASCADE, related_name="insights")
    session = models.ForeignKey(
        ProspectIntakeSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="insights",
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="human")
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    title = models.CharField(max_length=300)
    body = models.TextField()
    confidence = models.FloatField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_insights",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.kind}: {self.title}"


class ProspectNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prospect = models.ForeignKey(BusinessProspect, on_delete=models.CASCADE, related_name="notes")
    session = models.ForeignKey(
        ProspectIntakeSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notes",
    )
    body = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prospect_notes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Note on {self.prospect.name} ({self.created_at.date()})"


class OnboardingQuestion(models.Model):
    CATEGORY_CHOICES = [
        ("identity", "Identity & Founding"),
        ("presentation", "Outward Presentation"),
        ("operations", "Operational Character"),
        ("relationships", "Relationships"),
        ("knowledge", "Knowledge & People"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    text = models.TextField()
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES)
    order = models.PositiveIntegerField(default=0)
    triggers_persona_creation = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category", "order"]

    def __str__(self):
        return f"[{self.category}] {self.text[:80]}"


class ProspectQuestionOnboardingMap(models.Model):
    prospect_question = models.OneToOneField(
        ProspectQuestion,
        on_delete=models.CASCADE,
        related_name="onboarding_map",
    )
    onboarding_question = models.ForeignKey(
        OnboardingQuestion,
        on_delete=models.CASCADE,
        related_name="prospect_maps",
    )

    class Meta:
        verbose_name = "Prospect → Onboarding Question Map"

    def __str__(self):
        return f"{self.prospect_question} → {self.onboarding_question}"
