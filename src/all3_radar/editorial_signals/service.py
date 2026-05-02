"""Services for editor-driven shortlist signals."""

from __future__ import annotations

from dataclasses import dataclass

from all3_radar.domain.models import EditorialSignal
from all3_radar.storage.repositories import RadarRepository

SHORTLIST_SIGNAL_TYPE = "shortlist"
TELEGRAM_INLINE_BUTTON_SOURCE = "telegram_inline_button"


@dataclass(frozen=True)
class ShortlistToggleResult:
    is_active: bool
    signal: EditorialSignal


class EditorialSignalService:
    def __init__(self, repository: RadarRepository) -> None:
        self.repository = repository

    def toggle_shortlist(
        self,
        *,
        normalized_item_id: str,
        canonical_event_id: str | None,
        chat_id: str,
        telegram_message_id: str,
        user_id: str,
        username: str = "",
        source_kind: str = TELEGRAM_INLINE_BUTTON_SOURCE,
        raw_value: str = "🏆",
    ) -> ShortlistToggleResult:
        current_state = self.repository.get_editorial_signal_state(
            signal_type=SHORTLIST_SIGNAL_TYPE,
            source_kind=source_kind,
            normalized_item_id=normalized_item_id,
            chat_id=chat_id,
            user_id=user_id,
        )
        next_state = "inactive" if current_state == "active" else "active"
        signal = EditorialSignal(
            signal_type=SHORTLIST_SIGNAL_TYPE,
            signal_state=next_state,
            source_kind=source_kind,
            normalized_item_id=normalized_item_id,
            canonical_event_id=canonical_event_id,
            chat_id=chat_id,
            telegram_message_id=telegram_message_id,
            user_id=user_id,
            username=username,
            raw_value=raw_value,
        )
        self.repository.upsert_editorial_signal(signal)
        return ShortlistToggleResult(is_active=next_state == "active", signal=signal)
