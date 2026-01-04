# lanternmail/services/exceptions.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ListmonkError(Exception):
    message: str
    status_code: Optional[int] = None
    response_text: Optional[str] = None

    def __str__(self) -> str:
        bits = [self.message]
        if self.status_code is not None:
            bits.append(f"status={self.status_code}")
        if self.response_text:
            bits.append(f"response={self.response_text}")
        return " | ".join(bits)


class ListmonkAuthError(ListmonkError):
    pass


class ListmonkNotFoundError(ListmonkError):
    pass


class ListmonkBadRequestError(ListmonkError):
    pass


class ListmonkUpstreamError(ListmonkError):
    pass
