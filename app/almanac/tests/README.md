# Almanac Test Suite

**Author:** Claude Code
**Created:** 2025-12-26
**Status:** Ready to Run

---

## 📋 Overview

Comprehensive test suite for the Almanac event management system covering:
- **Event Creation** (single, recurring, adhoc series)
- **Occurrence Management** (edit, cancel, reschedule)
- **RSVP Logic** (individual occurrences, entire series, capacity)
- **Permissions** (author, organizers, visibility)

---

## 🏗️ Test Structure

```
almanac/tests/
├── __init__.py
├── fixtures.py                    # Shared test utilities and mixins
├── test_event_creation.py         # Event creation tests (46 tests)
├── test_occurrence_management.py  # Occurrence editing/cancelling (24 tests)
├── test_rsvp_logic.py            # RSVP and attendee tests (28 tests)
├── test_permissions.py           # Access control tests (22 tests)
└── README.md                     # This file

Total: ~120 test cases
```

---

## 🚀 Running Tests

### Run All Almanac Tests

```bash
cd REDACTED-LOCAL-PATH/mixtape-release-core/app
python manage.py test almanac.tests
```

### Run Specific Test Files

```bash
# Event creation tests only
python manage.py test almanac.tests.test_event_creation

# RSVP logic tests only
python manage.py test almanac.tests.test_rsvp_logic

# Occurrence management tests only
python manage.py test almanac.tests.test_occurrence_management

# Permission tests only
python manage.py test almanac.tests.test_permissions
```

### Run Specific Test Cases

```bash
# Run a specific test class
python manage.py test almanac.tests.test_event_creation.SingleEventCreationTestCase

# Run a single test method
python manage.py test almanac.tests.test_event_creation.SingleEventCreationTestCase.test_create_basic_single_event
```

### Run with Verbose Output

```bash
python manage.py test almanac.tests --verbosity=2
```

### Run with Coverage

```bash
# Install coverage if needed
pip install coverage

# Run tests with coverage
coverage run --source='almanac' manage.py test almanac.tests
coverage report
coverage html  # Generate HTML report
```

---

## 📁 Test Files Explained

### `fixtures.py` - Test Utilities

**Purpose:** Shared test data creation and helper methods

**Key Classes:**
- `AlmanacTestMixin` - Base mixin with common fixtures
  - Creates test users (user1, user2, organizer)
  - Creates test group with memberships
  - Helper methods for creating events, RSVPs, occurrences

**Key Functions:**
- `create_test_user()` - Quick user creation
- `create_test_group()` - Quick group creation
- `create_published_event()` - Create ready-to-view event

**Example Usage:**
```python
from almanac.tests.fixtures import AlmanacTestMixin

class MyTestCase(AlmanacTestMixin, TestCase):
    def test_something(self):
        event = self.create_test_event()
        rsvp = self.create_rsvp(event.series.next_occurrence, self.user1)
        ...
```

---

### `test_event_creation.py` - Event Creation (46 tests)

**What it tests:**
- ✅ Single event creation
- ✅ Recurring events with RRULE
- ✅ Adhoc series with custom dates
- ✅ Event metadata (format, location, registration)
- ✅ Validation (dates, required fields)
- ✅ Slug generation

**Example Tests:**
- `test_create_basic_single_event` - Simple event creation
- `test_single_event_creates_one_occurrence` - Verifies occurrence creation
- `test_create_weekly_recurring_event` - RRULE-based recurring events
- `test_adhoc_series_preserves_slot_order` - Custom date handling

**Run:** `python manage.py test almanac.tests.test_event_creation`

---

### `test_occurrence_management.py` - Occurrence Management (24 tests)

**What it tests:**
- ✅ Editing occurrence titles, locations, times
- ✅ Title/location overrides vs series defaults
- ✅ Cancelling occurrences
- ✅ Cancellation reasons
- ✅ Occurrence properties (is_past, is_happening_now, is_full)
- ✅ Attendee count tracking

**Example Tests:**
- `test_edit_occurrence_title` - Override series title
- `test_cancel_occurrence` - Cancel with reason
- `test_is_past_property` - Past occurrence detection
- `test_occurrence_is_full_with_limit` - Capacity tracking

**Run:** `python manage.py test almanac.tests.test_occurrence_management`

---

### `test_rsvp_logic.py` - RSVP & Attendance (28 tests)

**What it tests:**
- ✅ RSVPing to single occurrences
- ✅ RSVPing to entire series
- ✅ RSVP status changes (going → maybe → not_going)
- ✅ Capacity limits and full events
- ✅ Attendee check-in
- ✅ Feedback and ratings
- ✅ Registration notes

**Example Tests:**
- `test_rsvp_to_occurrence` - Basic RSVP
- `test_rsvp_to_all_occurrences` - Series RSVP
- `test_occurrence_full_status` - Capacity tracking
- `test_check_in_attendee` - Check-in flow

**Run:** `python manage.py test almanac.tests.test_rsvp_logic`

---

### `test_permissions.py` - Access Control (22 tests)

**What it tests:**
- ✅ Event authorship
- ✅ Organizer permissions
- ✅ Follower types (organizer, interested)
- ✅ Event visibility (draft, published, archived)
- ✅ Group sponsorship

**Example Tests:**
- `test_event_author_can_edit` - Author permissions
- `test_add_organizer_to_event` - Organizer assignment
- `test_filter_published_events` - Visibility filtering
- `test_event_sponsored_by_group` - Group context

**Run:** `python manage.py test almanac.tests.test_permissions`

---

## 🧪 Test Coverage

**Current Coverage:** ~120 test cases

**What's Covered:**
- ✅ Event CRUD operations
- ✅ Recurring event logic (RRULE)
- ✅ Occurrence management
- ✅ RSVP workflows
- ✅ Capacity tracking
- ✅ Permissions and access control
- ✅ Event visibility

**What's NOT Covered (yet):**
- ⏳ API endpoints (serializers, views)
- ⏳ Calendar filtering logic
- ⏳ Email notifications
- ⏳ Timezone conversions
- ⏳ Decorator assignments

---

## 🔧 Writing New Tests

### Quick Template

```python
from django.test import TestCase
from .fixtures import AlmanacTestMixin

class MyNewTestCase(AlmanacTestMixin, TestCase):
    """Tests for [feature description]"""

    def test_something_works(self):
        """Test that [specific behavior] works correctly"""
        # Arrange
        event = self.create_test_event(title="Test Event")

        # Act
        event.status = 'published'
        event.save()

        # Assert
        self.assertEqual(event.status, 'published')
```

### Best Practices

1. **Use fixtures** - Leverage `AlmanacTestMixin` for common setup
2. **One assertion per test** - Makes failures easier to diagnose
3. **Clear test names** - `test_what_should_happen_when_condition`
4. **Arrange-Act-Assert** - Structure tests clearly
5. **Test edge cases** - Empty values, max limits, past dates
6. **Clean docstrings** - Explain what you're testing

---

## 🐛 Troubleshooting

### Tests Fail with "Table doesn't exist"

```bash
# Run migrations
python manage.py migrate
```

### Tests Fail with "No module named 'almanac'"

```bash
# Make sure you're in the right directory
cd REDACTED-LOCAL-PATH/mixtape-release-core/app

# Verify DJANGO_SETTINGS_MODULE
export DJANGO_SETTINGS_MODULE=mixtape.settings.dev
```

### Tests Are Slow

```bash
# Use in-memory database for tests (add to settings_test.py)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
```

### Import Errors

```bash
# Make sure all test files are in almanac/tests/ directory
# and __init__.py exists
```

---

## 📊 Test Metrics

Run this to see test performance:

```bash
python manage.py test almanac.tests --timing
```

Expected results:
- **Total tests:** ~120
- **Execution time:** 5-15 seconds
- **Success rate:** 100%

---

## 🔗 Next Steps

1. **Add API endpoint tests** - Test serializers and views
2. **Add integration tests** - Test full request/response cycles
3. **Add calendar filtering tests** - Test complex query logic
4. **Set up CI/CD** - Run tests on every commit

---

## 📚 Resources

- [Django Testing Docs](https://docs.djangoproject.com/en/stable/topics/testing/)
- [Python unittest](https://docs.python.org/3/library/unittest.html)
- [Coverage.py](https://coverage.readthedocs.io/)

---

**Questions?** Check the tests or reach out to the development team.

**Ready to test?** Run `python manage.py test almanac.tests`
