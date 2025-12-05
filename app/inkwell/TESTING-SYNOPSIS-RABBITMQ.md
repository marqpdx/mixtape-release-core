# Testing Synopsis RabbitMQ Integration

## Overview

This document provides instructions for testing the complete RabbitMQ-based synopsis generation flow.

## Flow to Test

```
1. Django triggers synopsis generation (generate_synopsis_task)
2. Task sends POST to FastAPI with RabbitMQ connection info
3. FastAPI generates synopsis (external service)
4. FastAPI publishes result to RabbitMQ synopsis_results queue
5. Django Celery worker consumes from synopsis_results queue
6. Django updates SuggestedAsset with synopsis
```

## Prerequisites

### Python Dependencies

Ensure the following Python packages are installed in your virtual environment:

```bash
# Activate virtual environment
source env/bin/activate  # or '../env/bin/activate' from app directory

# Install required packages if missing
pip install requests  # Required for HTTP calls to FastAPI
pip install pika      # Required for RabbitMQ publisher testing
```

### Required Services Running

```bash
# RabbitMQ
sudo systemctl status rabbitmq-server
# or on macOS:
brew services list | grep rabbitmq

# Django Celery Worker (with synopsis_results queue)
celery -A mixtape worker -l info -Q synopsis_results

# Django Celery Worker (default queue for generating tasks)
celery -A mixtape worker -l info

# Django Application
python manage.py runserver

# FastAPI LLM Service (if available)
# Should be running on FASTAPI_LLM_URL (default: http://localhost:8001)
```

## Manual Testing Steps

### Step 1: Verify Configuration

Check that your environment has the correct settings:

```bash
# Check environment variables
echo $CELERY_BROKER_URL
# Should output: amqp://guest:guest@127.0.0.1:5672//

echo $FASTAPI_LLM_URL
# Should output: http://localhost:8001 (or your FastAPI URL)
```

Verify Django settings:

```python
# In Django shell: python manage.py shell
from django.conf import settings

print(settings.CELERY_BROKER_URL)
print(settings.FASTAPI_LLM_URL)
```

### Step 2: Create Test Asset

```python
# Django shell: python manage.py shell

from inkwell.models import SuggestedAsset, GutenbergInfo

# Create or get a test asset
gutenberg_info = GutenbergInfo.objects.create(
    source_id="1342",
    title="Pride and Prejudice",
    author="Jane Austen",
    cover_url="https://www.gutenberg.org/cache/epub/1342/pg1342.cover.medium.jpg",
    text_url="https://www.gutenberg.org/files/1342/1342-0.txt",
    source_url="/ebooks/1342",
)

asset = SuggestedAsset.objects.create(
    title="Pride and Prejudice",
    author="Jane Austen",
    source="gutenberg",
    source_id="1342",
    gutenberg_info=gutenberg_info,
    approved=True,
    synopsis_status="pending"
)

print(f"Created asset with ID: {asset.id}")
```

### Step 3: Trigger Synopsis Generation

```python
# In Django shell
from inkwell.tasks.synopsis import generate_synopsis_task

# Trigger the task
result = generate_synopsis_task.delay(asset.id)

print(f"Task triggered: {result.id}")
```

### Step 4: Monitor Logs

Watch the Celery worker logs for:

```
INFO [task] Received request to generate synopsis for asset <id>
INFO [task] Status set to 'pending' for: Pride and Prejudice
INFO [task] Synopsis generation request sent for: Pride and Prejudice
```

If FastAPI is running, watch for:
```
INFO Generated synopsis for asset <id>
INFO Published synopsis result for asset <id> to synopsis_results
```

### Step 5: Verify Result Consumption

Watch the Celery worker (synopsis_results queue) logs for:

```
INFO [synopsis_result] Received synopsis result for asset <id>
INFO [synopsis_result] Successfully saved synopsis for: Pride and Prejudice
```

### Step 6: Check Database

```python
# In Django shell
from inkwell.models import SuggestedAsset

asset = SuggestedAsset.objects.get(id=<your_asset_id>)

print(f"Synopsis Status: {asset.synopsis_status}")
print(f"Synopsis: {asset.synopsis[:100]}...")  # First 100 chars

# Should show:
# Synopsis Status: complete
# Synopsis: <generated synopsis text>
```

## Testing Without FastAPI

If FastAPI is not available yet, you can test the consumer task directly by publishing a test message to RabbitMQ:

### Step 1: Install pika

```bash
pip install pika
```

### Step 2: Create Test Publisher Script

Create a file `test_synopsis_publisher.py`:

```python
import pika
import json
import sys

def publish_test_synopsis(asset_id, synopsis_text):
    """Publishes a test synopsis result to RabbitMQ."""

    # Connect to RabbitMQ
    broker_url = "amqp://guest:guest@127.0.0.1:5672//"
    parameters = pika.URLParameters(broker_url)
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()

    # Declare queue
    channel.queue_declare(queue='synopsis_results', durable=True)

    # Prepare message
    message = {
        'task': 'inkwell.tasks.synopsis.process_synopsis_result',
        'args': [asset_id, synopsis_text, 'complete'],
        'kwargs': {},
    }

    # Publish message
    channel.basic_publish(
        exchange='',
        routing_key='synopsis_results',
        body=json.dumps(message),
        properties=pika.BasicProperties(
            delivery_mode=2,
            content_type='application/json',
        )
    )

    print(f"Published test synopsis for asset {asset_id}")

    # Close connection
    connection.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_synopsis_publisher.py <asset_id> <synopsis_text>")
        sys.exit(1)

    asset_id = int(sys.argv[1])
    synopsis_text = sys.argv[2]

    publish_test_synopsis(asset_id, synopsis_text)
```

### Step 3: Run Test Publisher

```bash
python test_synopsis_publisher.py 1 "This is a test synopsis for Pride and Prejudice."
```

### Step 4: Verify Django Received It

Check Celery worker logs and database as described in Manual Testing Steps above.

## Automated Unit Tests

Add these tests to `inkwell/tests.py`:

```python
from django.test import TestCase
from unittest.mock import patch, MagicMock
from inkwell.models import SuggestedAsset, GutenbergInfo
from inkwell.tasks.synopsis import process_synopsis_result, generate_synopsis_task

class SynopsisRabbitMQTestCase(TestCase):
    def setUp(self):
        """Create test asset."""
        self.gutenberg_info = GutenbergInfo.objects.create(
            source_id="1342",
            title="Pride and Prejudice",
            author="Jane Austen",
            text_url="https://www.gutenberg.org/files/1342/1342-0.txt",
            source_url="/ebooks/1342",
        )

        self.asset = SuggestedAsset.objects.create(
            title="Pride and Prejudice",
            author="Jane Austen",
            source="gutenberg",
            source_id="1342",
            gutenberg_info=self.gutenberg_info,
            approved=True,
            synopsis_status="pending"
        )

    def test_process_synopsis_result_success(self):
        """Test that process_synopsis_result updates asset correctly."""
        synopsis_text = "Test synopsis text"

        result = process_synopsis_result(
            asset_id=self.asset.id,
            synopsis=synopsis_text,
            status='complete'
        )

        # Refresh asset from database
        self.asset.refresh_from_db()

        # Verify updates
        self.assertEqual(self.asset.synopsis, synopsis_text)
        self.assertEqual(self.asset.synopsis_status, 'complete')
        self.assertEqual(result['status'], 'saved')
        self.assertEqual(result['asset_id'], self.asset.id)

    def test_process_synopsis_result_failure(self):
        """Test that process_synopsis_result handles failures."""
        result = process_synopsis_result(
            asset_id=self.asset.id,
            synopsis="",
            status='failed'
        )

        # Refresh asset from database
        self.asset.refresh_from_db()

        # Verify failed status
        self.assertEqual(self.asset.synopsis_status, 'failed')
        self.assertEqual(result['status'], 'saved')

    def test_process_synopsis_result_asset_not_found(self):
        """Test that process_synopsis_result handles missing asset."""
        result = process_synopsis_result(
            asset_id=99999,  # Non-existent asset
            synopsis="Test",
            status='complete'
        )

        # Verify error response
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error'], 'Asset not found')

    @patch('inkwell.tasks.synopsis.requests.post')
    @patch('inkwell.tasks.synopsis.os.getenv')
    def test_generate_synopsis_task_sends_rabbitmq_info(self, mock_getenv, mock_post):
        """Test that generate_synopsis_task sends RabbitMQ connection info."""
        # Mock environment variable
        mock_getenv.return_value = "amqp://guest:guest@127.0.0.1:5672//"

        # Mock successful HTTP response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        # Execute task
        generate_synopsis_task(self.asset.id)

        # Verify POST was called
        self.assertTrue(mock_post.called)

        # Get the call arguments
        call_args = mock_post.call_args
        payload = call_args[1]['json']

        # Verify payload contains RabbitMQ info
        self.assertIn('rabbitmq', payload)
        self.assertEqual(payload['rabbitmq']['queue_name'], 'synopsis_results')
        self.assertEqual(payload['rabbitmq']['routing_key'], 'synopsis_results')
        self.assertEqual(payload['asset_id'], self.asset.id)
```

### Run Tests

```bash
# Run all inkwell tests
python manage.py test inkwell

# Run only synopsis tests
python manage.py test inkwell.tests.SynopsisRabbitMQTestCase

# Run specific test
python manage.py test inkwell.tests.SynopsisRabbitMQTestCase.test_process_synopsis_result_success
```

## Troubleshooting

### Issue: Task not triggered

**Symptoms:**
- No logs showing synopsis generation started

**Check:**
```python
# Verify task is registered
from inkwell.tasks.synopsis import generate_synopsis_task
print(generate_synopsis_task.name)
# Should output: inkwell.tasks.synopsis.generate_synopsis_task
```

### Issue: Consumer task not receiving messages

**Symptoms:**
- Synopsis generated but asset not updated
- No logs showing "[synopsis_result] Received synopsis result"

**Check:**
1. Verify Celery worker is listening to synopsis_results queue:
   ```bash
   celery -A mixtape inspect active_queues
   ```

2. Check RabbitMQ queue has messages:
   ```bash
   sudo rabbitmqctl list_queues
   ```

3. Verify task routing in `mixtape/celery.py`:
   ```python
   app.conf.task_routes = {
       "inkwell.tasks.synopsis.process_synopsis_result": {
           "queue": "synopsis_results",
           "routing_key": "synopsis_results"
       },
   }
   ```

### Issue: FastAPI connection failed

**Symptoms:**
- Logs show: "Failed to generate synopsis for asset"
- HTTP connection errors

**Check:**
1. Verify FastAPI is running:
   ```bash
   curl http://localhost:8001/health  # or your FastAPI URL
   ```

2. Check FASTAPI_LLM_URL setting:
   ```python
   from django.conf import settings
   print(settings.FASTAPI_LLM_URL)
   ```

3. Review FastAPI logs for errors

## Success Criteria

The integration is working correctly when:

1. ✅ generate_synopsis_task sends POST to FastAPI with RabbitMQ info
2. ✅ FastAPI publishes synopsis result to synopsis_results queue
3. ✅ Django Celery worker consumes message from synopsis_results queue
4. ✅ process_synopsis_result updates SuggestedAsset with synopsis and status
5. ✅ Asset in database shows synopsis_status='complete' and populated synopsis field
6. ✅ All logs show successful flow without errors

## Monitoring in Production

### Key Metrics to Track

1. **Synopsis generation success rate**
   - Count of complete vs failed synopsis_status

2. **Processing time**
   - Time from task trigger to database update

3. **RabbitMQ queue depth**
   - Monitor synopsis_results queue for backlogs

4. **Failed tasks**
   - Track process_synopsis_result failures

### Example Monitoring Queries

```python
# Synopsis success rate (last 24 hours)
from django.utils import timezone
from datetime import timedelta
from inkwell.models import SuggestedAsset

cutoff = timezone.now() - timedelta(days=1)

total = SuggestedAsset.objects.filter(created_at__gte=cutoff).count()
complete = SuggestedAsset.objects.filter(
    created_at__gte=cutoff,
    synopsis_status='complete'
).count()
failed = SuggestedAsset.objects.filter(
    created_at__gte=cutoff,
    synopsis_status='failed'
).count()

success_rate = (complete / total * 100) if total > 0 else 0

print(f"Total: {total}, Complete: {complete}, Failed: {failed}")
print(f"Success Rate: {success_rate:.2f}%")
```

## Contact

For issues or questions about synopsis RabbitMQ integration, contact the Django/Inkwell team.
