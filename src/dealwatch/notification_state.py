"""Generic post-delivery notification-state handling."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from dealwatch.models import NotificationEvent
from dealwatch.storage import SQLiteStore


@dataclass(frozen=True, slots=True)
class NotificationDeliveryResult:
    """The outcome of one caller-requested notification delivery attempt."""

    delivered: bool
    already_sent: bool


def deliver_once(
    store: SQLiteStore,
    event: NotificationEvent,
    deliver: Callable[[], None],
) -> NotificationDeliveryResult:
    """Deliver an alert only when its successful fingerprint has not been recorded.

    The delivery callback is allowed to raise. In that case this function leaves no
    successful-notification record, so a later attempt remains eligible. The callback
    itself stays generic: M6 does not choose deals or know how a future transport works.
    """

    if store.has_successful_notification(event):
        return NotificationDeliveryResult(delivered=False, already_sent=True)

    deliver()
    was_recorded = store.record_successful_notification(event)
    return NotificationDeliveryResult(delivered=True, already_sent=not was_recorded)
