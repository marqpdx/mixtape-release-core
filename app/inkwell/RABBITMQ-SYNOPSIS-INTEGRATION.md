# RabbitMQ Synopsis Integration Guide

## Overview

This document describes how the FastAPI LLM service should publish synopsis results back to the Django application via RabbitMQ.

When Django requests a synopsis generation via POST to `/generate_synopsis`, it includes RabbitMQ connection information in the payload. After generating the synopsis, FastAPI should publish the results to the specified queue for Django to consume.

## Architecture Flow

```
Django (generate_synopsis_task)
    → POST /generate_synopsis (with RabbitMQ info)
        → FastAPI generates synopsis
            → FastAPI publishes result to RabbitMQ
                → Django Celery worker consumes result
                    → Updates SuggestedAsset
```

## Request Format from Django

FastAPI will receive the following payload:

```json
{
    "asset_id": 123,
    "asset_url": "https://www.gutenberg.org/files/12345/12345-0.txt",
    "rabbitmq": {
        "broker_url": "amqp://guest:guest@127.0.0.1:5672//",
        "queue_name": "synopsis_results",
        "routing_key": "synopsis_results"
    }
}
```

## Publishing Results to RabbitMQ

### Installation

```bash
pip install pika
```

### Basic Publisher Implementation

```python
import pika
import json
import logging

logger = logging.getLogger(__name__)

def publish_synopsis_result(rabbitmq_config, asset_id, synopsis, status='complete'):
    """
    Publishes synopsis result to RabbitMQ for Django consumption.

    Args:
        rabbitmq_config: Dict with broker_url, queue_name, routing_key
        asset_id: ID of the SuggestedAsset
        synopsis: Generated synopsis text
        status: 'complete' or 'failed'
    """
    try:
        # Parse broker URL
        broker_url = rabbitmq_config['broker_url']
        queue_name = rabbitmq_config['queue_name']
        routing_key = rabbitmq_config['routing_key']

        # Connect to RabbitMQ
        parameters = pika.URLParameters(broker_url)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()

        # Declare queue (idempotent operation)
        channel.queue_declare(queue=queue_name, durable=True)

        # Prepare message payload
        message = {
            'task': 'inkwell.tasks.synopsis.process_synopsis_result',
            'args': [asset_id, synopsis, status],
            'kwargs': {},
        }

        # Publish message
        channel.basic_publish(
            exchange='',
            routing_key=routing_key,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Make message persistent
                content_type='application/json',
            )
        )

        logger.info(f"Published synopsis result for asset {asset_id} to {queue_name}")

        # Close connection
        connection.close()

        return True

    except Exception as e:
        logger.error(f"Failed to publish synopsis result for asset {asset_id}: {e}", exc_info=True)
        return False
```

### Usage in FastAPI Endpoint

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class SynopsisRequest(BaseModel):
    asset_id: int
    asset_url: str
    rabbitmq: dict

@app.post("/generate_synopsis")
async def generate_synopsis(request: SynopsisRequest):
    """
    Generates synopsis for a book and publishes result to RabbitMQ.
    """
    try:
        # Trigger async synopsis generation
        # This should be done in a background task to return quickly
        background_tasks.add_task(
            generate_and_publish_synopsis,
            request.asset_id,
            request.asset_url,
            request.rabbitmq
        )

        return {"status": "accepted", "asset_id": request.asset_id}

    except Exception as e:
        logger.error(f"Failed to start synopsis generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def generate_and_publish_synopsis(asset_id, asset_url, rabbitmq_config):
    """
    Background task that generates synopsis and publishes to RabbitMQ.
    """
    try:
        # Generate synopsis using LLM
        synopsis = await generate_synopsis_with_llm(asset_url)

        # Publish success result
        publish_synopsis_result(
            rabbitmq_config=rabbitmq_config,
            asset_id=asset_id,
            synopsis=synopsis,
            status='complete'
        )

    except Exception as e:
        logger.error(f"Synopsis generation failed for asset {asset_id}: {e}")

        # Publish failure result
        publish_synopsis_result(
            rabbitmq_config=rabbitmq_config,
            asset_id=asset_id,
            synopsis="",
            status='failed'
        )
```

## Message Format Specification

The message published to RabbitMQ must follow Celery's task message format:

```json
{
    "task": "inkwell.tasks.synopsis.process_synopsis_result",
    "args": [
        123,                    // asset_id (int)
        "Synopsis text here",   // synopsis (str)
        "complete"              // status (str: 'complete' or 'failed')
    ],
    "kwargs": {}
}
```

### Field Descriptions

- **task**: Must be `"inkwell.tasks.synopsis.process_synopsis_result"` (Django Celery task name)
- **args[0]**: `asset_id` - Integer ID of the SuggestedAsset
- **args[1]**: `synopsis` - String containing the generated synopsis (empty string if failed)
- **args[2]**: `status` - String, either `"complete"` or `"failed"`

## Connection Pooling (Recommended)

For production use, implement connection pooling to avoid creating new connections for each message:

```python
import pika
from pika.adapters.blocking_connection import BlockingConnection
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

class RabbitMQPool:
    def __init__(self, broker_url, pool_size=5):
        self.broker_url = broker_url
        self.pool_size = pool_size
        self.connections = []

    @contextmanager
    def get_channel(self):
        """Context manager for getting a channel from the pool."""
        connection = None
        channel = None

        try:
            # Reuse existing connection or create new one
            if self.connections:
                connection = self.connections.pop()
                if connection.is_closed:
                    connection = self._create_connection()
            else:
                connection = self._create_connection()

            channel = connection.channel()
            yield channel

        except Exception as e:
            logger.error(f"Channel error: {e}")
            if connection and not connection.is_closed:
                connection.close()
            raise

        finally:
            # Return connection to pool
            if connection and not connection.is_closed:
                if len(self.connections) < self.pool_size:
                    self.connections.append(connection)
                else:
                    connection.close()

    def _create_connection(self):
        """Creates a new RabbitMQ connection."""
        parameters = pika.URLParameters(self.broker_url)
        return BlockingConnection(parameters)

# Global pool instance
rabbitmq_pool = None

def init_rabbitmq_pool(broker_url):
    """Initialize the connection pool at application startup."""
    global rabbitmq_pool
    rabbitmq_pool = RabbitMQPool(broker_url)

def publish_synopsis_result_pooled(rabbitmq_config, asset_id, synopsis, status='complete'):
    """
    Publishes synopsis result using connection pooling.
    """
    try:
        queue_name = rabbitmq_config['queue_name']
        routing_key = rabbitmq_config['routing_key']

        message = {
            'task': 'inkwell.tasks.synopsis.process_synopsis_result',
            'args': [asset_id, synopsis, status],
            'kwargs': {},
        }

        with rabbitmq_pool.get_channel() as channel:
            channel.queue_declare(queue=queue_name, durable=True)

            channel.basic_publish(
                exchange='',
                routing_key=routing_key,
                body=json.dumps(message),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type='application/json',
                )
            )

        logger.info(f"Published synopsis result for asset {asset_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to publish synopsis result: {e}", exc_info=True)
        return False
```

### Initialize Pool at Startup

```python
from fastapi import FastAPI

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    # Initialize RabbitMQ connection pool
    broker_url = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@127.0.0.1:5672//")
    init_rabbitmq_pool(broker_url)
    logger.info("RabbitMQ connection pool initialized")
```

## Error Handling Best Practices

1. **Always publish a result** - Even if synopsis generation fails, publish with `status='failed'`
2. **Log all errors** - Use structured logging with exc_info=True
3. **Retry logic** - Implement retries for transient RabbitMQ connection failures
4. **Timeout handling** - Set appropriate timeouts for LLM calls
5. **Validation** - Validate asset_url before attempting to download large texts

## Testing

### Manual Test

```python
# Test publishing a synopsis result
rabbitmq_config = {
    'broker_url': 'amqp://guest:guest@127.0.0.1:5672//',
    'queue_name': 'synopsis_results',
    'routing_key': 'synopsis_results'
}

publish_synopsis_result(
    rabbitmq_config=rabbitmq_config,
    asset_id=1,
    synopsis="Test synopsis for debugging",
    status='complete'
)
```

### Verify Django Receives Message

Check Django logs for:
```
[synopsis_result] Received synopsis result for asset 1
[synopsis_result] Successfully saved synopsis for: [Book Title]
```

## Environment Variables

FastAPI should read these environment variables:

```bash
# RabbitMQ Connection (if not provided in request payload)
CELERY_BROKER_URL=amqp://guest:guest@localhost:5672//

# Optional: Connection pool size
RABBITMQ_POOL_SIZE=5
```

## Troubleshooting

### Connection Refused
- Verify RabbitMQ is running: `sudo systemctl status rabbitmq-server`
- Check broker_url format: `amqp://user:pass@host:port//`

### Messages Not Consumed
- Verify queue name matches: `synopsis_results`
- Check Celery worker is running: `celery -A mixtape worker -l info -Q synopsis_results`
- Verify task routing in Django's celery.py

### Invalid Message Format
- Ensure message follows Celery task format with `task`, `args`, `kwargs` keys
- Verify task name exactly matches: `inkwell.tasks.synopsis.process_synopsis_result`

## Contact

For questions or issues with this integration, contact the Django/Inkwell team.
