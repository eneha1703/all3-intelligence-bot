from datetime import date

from all3_radar.digest.corpus import resolve_digest_window


def test_resolve_digest_window_formats_same_month_range() -> None:
    window = resolve_digest_window("2026-W18")

    assert window.previous_thursday == date(2026, 4, 23)
    assert window.current_thursday == date(2026, 4, 30)
    assert window.title == "Top 5 News Highlights | 23-30 April 2026 | Week 18"


def test_resolve_digest_window_formats_cross_month_range() -> None:
    window = resolve_digest_window("2026-W19")

    assert window.previous_thursday == date(2026, 4, 30)
    assert window.current_thursday == date(2026, 5, 7)
    assert window.title == "Top 5 News Highlights | 30 April-7 May 2026 | Week 19"


def test_resolve_digest_window_formats_cross_year_range() -> None:
    window = resolve_digest_window("2027-W01")

    assert window.previous_thursday == date(2026, 12, 31)
    assert window.current_thursday == date(2027, 1, 7)
    assert window.title == "Top 5 News Highlights | 31 December 2026-7 January 2027 | Week 1"
