"""SM-2 inspired spaced repetition scheduling for flashcards."""

from datetime import date, timedelta

RATING_QUALITY = {"easy": 5, "medium": 3, "hard": 1}
BASE_INTERVALS = {"easy": 7, "medium": 3, "hard": 1}


def schedule_review(rating: str, ease_factor: float, interval_days: int, repetitions: int) -> dict:
    quality = RATING_QUALITY[rating]
    if quality < 3:
        repetitions = 0
        interval = BASE_INTERVALS["hard"]
    else:
        repetitions += 1
        if repetitions == 1:
            interval = BASE_INTERVALS[rating]
        else:
            interval = max(BASE_INTERVALS[rating], round(interval_days * ease_factor))
    ease_factor = max(1.3, ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    return {
        "ease_factor": round(ease_factor, 2),
        "interval_days": interval,
        "repetitions": repetitions,
        "next_review_date": date.today() + timedelta(days=interval),
    }
