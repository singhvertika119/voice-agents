"""When each background worker last went round its loop, for the health page (deploy/run_background.py)."""
import time

_last: dict[str, float] = {}


def beat(name: str) -> None:
    _last[name] = time.time()


def ages() -> dict[str, int]:
    """Seconds since each worker last checked for work. A large number while nothing is queued means it is stuck."""
    now = time.time()
    return {k: int(now - v) for k, v in _last.items()}
