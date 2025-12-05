# ai/management/commands/trigger_task.py

from django.core.management.base import BaseCommand

from inkwell.tasks.rabbitmq_tasks import send_task_to_fastapi


# from inkwell.tasks.task_example import send_task_to_fastapi  # Import the correct Celery task

class Command(BaseCommand):
    help = "Trigger a Celery task to send a request to FastAPI"

    def handle(self, *args, **kwargs):
        task_id = 1  # You can customize this task_id as needed
        send_task_to_fastapi.delay(task_id)  # Trigger the Celery task asynchronously
        self.stdout.write(self.style.SUCCESS(f"Successfully triggered task with ID {task_id}"))
