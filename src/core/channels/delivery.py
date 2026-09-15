"""Deterministic delivery boundary shared by both Meta channels."""
import json


class DeliveryUnconfirmed(RuntimeError):
    """Delivery must be reconciled; it must not be reported as successful."""


class IdempotencyConflict(ValueError):
    pass


def provider_message_id(result: dict) -> str:
    if not isinstance(result, dict) or not result.get("wam_id"):
        raise DeliveryUnconfirmed("Provider did not confirm delivery acceptance")
    if result.get("status") not in (None, "sent", "delivered", "read"):
        raise DeliveryUnconfirmed("Delivery is pending reconciliation")
    return str(result["wam_id"])


def validate_replayed_payload(row: dict, payload: dict) -> None:
    stored = row.get("content")
    if isinstance(stored, str):
        stored = json.loads(stored)
    if stored != payload:
        raise IdempotencyConflict("Idempotency key was already used for a different payload")
