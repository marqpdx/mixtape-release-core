# inkwell/tasks/__init__.py

from .ingest import ingest_approved_asset_task  # register it

# from .task_example import send_task_to_fastapi
# from .task_listener import listen_for_task_result
from .rabbitmq_tasks import (
    poll_rabbitmq_results,
    send_task_to_fastapi,
    start_rabbitmq_polling,
)
# from .startup import run_startup_task_async
from .synopsis import (  # synopsis generation and results
    generate_synopsis_task,
    process_synopsis_result,
)
from .stackroom_integration import (  # register with autodiscover
    ingest_object_task,
    deactivate_object_task,
)
