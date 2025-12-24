# Events Publishing Integration

## Overview

The Almanac Events system integrates with the universal publishing infrastructure (`app.publishing`) to enable flexible event distribution across multiple channels and contexts.

## Current Publishing Implementation

### Event Model Publishing Status

Events use the **PublishableContentMixin** which provides:

- `status` field: `DRAFT`, `PUBLISHED`, `ARCHIVED`
- `published_at` timestamp
- `publish()` and `unpublish()` methods

**Current Workflow**:
```python
# Create event
event = Event.objects.create_single_event(...)

# Publish event
event.publish()  # Sets status='published', published_at=now()

# Unpublish event
event.unpublish()  # Sets status='draft', published_at=None
```

**API Endpoints**:
- `POST /api/almanac/events/{id}/publish` - Publish event
- `POST /api/almanac/events/{id}/unpublish` - Unpublish event

## ContentPlacement Integration (Future)

Events can leverage `ContentPlacement` for advanced distribution scenarios.

### When to Use ContentPlacement for Events

**NOT needed for basic events** - The current publishing workflow (DRAFT → PUBLISHED) is sufficient for most event use cases.

**Consider ContentPlacement when**:
1. **Event Snapshots** - Need to lock event details at a specific point in time
2. **Multi-Channel Distribution** - Publishing same event to multiple groups/calendars with different visibility
3. **Override Display** - Different title/description per channel
4. **Version Locking** - Lock to specific EventSnapshot for historical accuracy

### EventSnapshot Model (Deferred - Phase 6)

When event versioning is needed, create `EventSnapshot` inheriting from `BaseVersion`:

```python
from publishing.models import BaseVersion

class EventSnapshot(BaseVersion):
    """
    Immutable snapshot of an Event at a point in time.
    Used when event details change after people have RSVP'd.
    """
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='snapshots')

    # Snapshot of event data
    title = models.CharField(max_length=255)
    description = models.TextField()
    location = models.CharField(max_length=500)
    event_format = models.CharField(max_length=50)

    # Snapshot of series data
    rrule = models.TextField(blank=True)
    default_duration_minutes = models.IntegerField()

    class Meta(BaseVersion.Meta):
        ordering = ['-created_at']
```

Then add artifact resolution to Event model:

```python
class Event(BaseContent, PublishableContentMixin):
    # ... existing fields ...

    def get_current_artifact(self):
        """Get the latest event snapshot."""
        return self.snapshots.filter(kind='snapshot').order_by('-created_at').first()

    def get_artifact(self, ref):
        """Get specific snapshot by ID."""
        return self.snapshots.get(id=ref)

    def create_snapshot(self):
        """Create immutable snapshot of current event state."""
        return EventSnapshot.objects.create(
            event=self,
            kind='snapshot',
            created_by=self.author,
            title=self.title,
            description=self.description,
            location=self.location,
            event_format=self.event_format,
            rrule=self.series.rrule if self.series else '',
            default_duration_minutes=self.series.default_duration_minutes if self.series else 60,
        )
```

### Example: Multi-Channel Event Publishing

Once EventSnapshot is implemented:

```python
from publishing.models import ContentPlacement, PublicationGroup
from django.contrib.contenttypes.models import ContentType

# Publish event to multiple groups with different settings
def publish_event_to_groups(event, user, group_configs):
    """
    Publish event to multiple groups with per-group customization.

    Args:
        event: Event instance
        user: User publishing the event
        group_configs: List of dicts with group and override settings
    """
    # Create snapshot
    snapshot = event.create_snapshot()

    # Create publication group
    ct_event = ContentType.objects.get_for_model(Event)
    pub_group = PublicationGroup.objects.create(
        created_by=user,
        source_content_type=ct_event,
        source_object_id=event.id,
        note=f"Publishing {event.title} to multiple groups",
    )

    # Create placements for each group
    ct_group = ContentType.objects.get_for_model(Group)
    ct_snapshot = ContentType.objects.get_for_model(EventSnapshot)

    for config in group_configs:
        group = config['group']

        ContentPlacement.objects.create(
            publication_group=pub_group,
            placed_by=user,

            # Source
            source_content_type=ct_event,
            source_object_id=event.id,

            # Target
            target_content_type=ct_group,
            target_object_id=group.id,

            # Channel
            channel='almanac',
            visibility=config.get('visibility', 'members'),

            # Version locking
            follow_updates=config.get('follow_updates', False),
            locked_artifact_content_type=ct_snapshot,
            locked_artifact_object_id=snapshot.id,

            # Display overrides
            overrides={
                'title': config.get('title_override', event.title),
                'location': config.get('location_override', event.location),
            }
        )
```

## Current Recommendation

**For now**: Use the existing Event publishing workflow (DRAFT → PUBLISHED). The current implementation is sufficient for:
- Creating and publishing events
- Managing RSVPs and attendance
- Calendar views
- Event following and notifications

**Defer ContentPlacement** until you need:
- Event versioning/snapshots
- Multi-channel distribution with different display settings
- Historical accuracy when event details change

## Publishing Service Integration

When ContentPlacement is used, Events can leverage the publishing services:

```python
from publishing.services import get_display_payload, can_view_placement

# Resolve event placement to displayable artifact
payload = get_display_payload(placement)
# Returns: {
#   'artifact': EventSnapshot instance,
#   'source': Event instance,
#   'metadata': {
#     'title': 'Event Title' (with overrides applied),
#     'location': 'Event Location',
#     'channel': 'almanac',
#     'visibility': 'members',
#   }
# }

# Check if user can view the event placement
can_view = can_view_placement(placement, user)
```

## Summary

- ✅ **Current**: Events have publishing workflow (DRAFT → PUBLISHED → ARCHIVED)
- ✅ **Working**: Publish/unpublish endpoints functional
- ⏸️ **Deferred**: EventSnapshot model (Phase 6)
- ⏸️ **Deferred**: ContentPlacement integration (when versioning is needed)
- ✅ **Ready**: Publishing infrastructure (BaseVersion, ContentPlacement, services) available when needed

The universal publishing foundation is in place and ready to extend Events when versioning or multi-channel distribution becomes a requirement.
