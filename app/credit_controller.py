import threading
import time

from .models import SongBehavior


class KeyboardCreditController:
    def __init__(self, default_credit_per_key: float = 0.125, max_credit: float = 8.0):
        self._lock = threading.Lock()
        self._credit_beats = 0.0
        self._default_credit_per_key = default_credit_per_key
        self._credit_per_key = default_credit_per_key
        self._max_credit = max_credit

        self._press_timestamps: list[float] = []
        self._last_press_time = 0.0
        self._debounce_seconds = 0.03

    def configure(self, behavior: SongBehavior):
        with self._lock:
            self._credit_per_key = behavior.credit_per_key_beats
            self._max_credit = behavior.max_credit_beats

    def on_key_press(self):
        now = time.time()

        if now - self._last_press_time < self._debounce_seconds:
            return

        with self._lock:
            self._last_press_time = now
            self._credit_beats = min(
                self._max_credit, self._credit_beats + self._credit_per_key
            )

            self._press_timestamps.append(now)
            cutoff = now - 60
            self._press_timestamps = [
                t for t in self._press_timestamps if t >= cutoff
            ]

        self._adapt_credit()

    def consume(self, beats: float):
        with self._lock:
            self._credit_beats = max(0.0, self._credit_beats - beats)

    def get_credit(self) -> float:
        with self._lock:
            return self._credit_beats

    def get_typing_rate(self, window_seconds: float = 10.0) -> float:
        now = time.time()
        with self._lock:
            recent = [t for t in self._press_timestamps if t >= now - window_seconds]
            if len(recent) < 2:
                return 0.0
            return len(recent) / window_seconds

    def _adapt_credit(self):
        rate_short = self.get_typing_rate(10.0)
        rate_long = self.get_typing_rate(60.0)

        rate = rate_short if rate_short > 0 else rate_long
        if rate <= 0:
            return

        with self._lock:
            base = self._default_credit_per_key
            if rate > 8:
                self._credit_per_key = max(base * 0.5, base * (5.0 / rate))
            elif rate < 1:
                self._credit_per_key = min(base * 2.0, base * (2.0 / max(rate, 0.3)))
            else:
                blend = 0.9
                self._credit_per_key = (
                    self._credit_per_key * blend + base * (1 - blend)
                )
