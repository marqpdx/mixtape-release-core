# mixtape/logging.py

import logging

class HTTPStatusToLevelFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()

        # Django runserver message often ends with: '"GET /..." 404 56'
        parts = msg.rsplit(" ", 2)
        if len(parts) >= 2:
            try:
                status = int(parts[-2])
                if 200 <= status < 300:
                    record.levelname = "INFO"      # green
                elif 300 <= status < 400:
                    record.levelname = "INFO"      # or blue if you map it
                elif 400 <= status < 500:
                    record.levelname = "ERROR"     # red for 4xx
                elif status >= 500:
                    record.levelname = "CRITICAL"  # bold red
            except ValueError:
                pass

        return True
