import time
from collections import deque
from config.settings import settings
from utils.logger import get_logger

log = get_logger("RateLimiter")

# Sliding window deques (in-process singleton)
_minute_window: deque = deque()
_hour_window: deque   = deque()


def _prune(window: deque, window_ms: int):
    cutoff = time.time() * 1000 - window_ms
    while window and window[0] < cutoff:
        window.popleft()


def consume_request() -> tuple[bool, int]:
    """Returns (allowed, retry_after_ms)"""
    _prune(_minute_window, 60_000)
    if len(_minute_window) >= settings.rate_limit_requests_per_minute:
        retry = int(60_000 - (time.time() * 1000 - _minute_window[0]))
        log.warning(f"Global rate limit hit. Retry after {retry}ms")
        return False, retry
    _minute_window.append(time.time() * 1000)
    return True, 0


def consume_create_order() -> tuple[bool, int]:
    """Returns (allowed, retry_after_ms)"""
    _prune(_hour_window, 3_600_000)
    if len(_hour_window) >= settings.rate_limit_create_order_per_hour:
        retry = int(3_600_000 - (time.time() * 1000 - _hour_window[0]))
        log.warning(f"create_order rate limit hit. Retry after {retry}ms")
        return False, retry
    _hour_window.append(time.time() * 1000)
    return True, 0


def get_rate_limit_status() -> dict:
    _prune(_minute_window, 60_000)
    _prune(_hour_window, 3_600_000)
    return {
        "requests_used_this_minute":        len(_minute_window),
        "requests_remaining_this_minute":   settings.rate_limit_requests_per_minute - len(_minute_window),
        "create_orders_used_this_hour":     len(_hour_window),
        "create_orders_remaining_this_hour": settings.rate_limit_create_order_per_hour - len(_hour_window),
    }
