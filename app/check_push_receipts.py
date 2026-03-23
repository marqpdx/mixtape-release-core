#!/usr/bin/env python3
"""
Poll Expo push receipts to check actual FCM delivery status.

Usage:
    python check_push_receipts.py <ticket_id> [<ticket_id2> ...]

Ticket IDs appear in the Celery worker log after a message send:
    push_sent notification=... token_prefix=... ticket_id=XXXX-XXXX-...

Receipt statuses:
    ok                  — FCM delivered successfully
    error/InvalidCredentials  — Firebase project mismatch (wrong service account on Expo)
    error/DeviceNotRegistered — Token is stale, device unregistered from FCM
    error/MessageTooBig       — Payload over 4KB
    error/MessageRateExceeded — FCM rate limit hit
"""

import sys
import json
import requests


def check_receipts(ticket_ids: list[str]) -> None:
    print(f"\nPolling receipts for {len(ticket_ids)} ticket(s)...\n")

    resp = requests.post(
        "https://exp.host/--/api/v2/push/getReceipts",
        json={"ids": ticket_ids},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=15,
    )

    if not resp.ok:
        print(f"HTTP error {resp.status_code}: {resp.text}")
        sys.exit(1)

    data = resp.json().get("data", {})

    if not data:
        print("No receipts found yet — Expo may still be processing. Wait 15-30s and retry.")
        return

    for ticket_id, receipt in data.items():
        status = receipt.get("status", "unknown")
        details = receipt.get("details", {})
        message = receipt.get("message", "")
        if status == "ok":
            print(f"  ✓ {ticket_id}  →  ok (FCM delivered)")
        else:
            error = details.get("error", "unknown")
            print(f"  ✗ {ticket_id}  →  {status} / {error}")
            if message:
                print(f"      {message}")

    print()


if __name__ == "__main__":
    ids = sys.argv[1:]
    if not ids:
        print("Usage: python check_push_receipts.py <ticket_id> [<ticket_id2> ...]")
        print("\nTicket IDs are logged by Celery after each push send:")
        print("  push_sent notification=... token_prefix=... ticket_id=XXXXXXXX-...")
        sys.exit(1)

    check_receipts(ids)
