"""Zaman asimli islemler — kopan kamerada donmayi onler."""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

T = TypeVar("T")


def run_with_timeout(func: Callable[[], T], timeout_sec: float, default: T) -> T:
    result: list[T] = []
    error: list[BaseException] = []

    def worker() -> None:
        try:
            result.append(func())
        except BaseException as e:
            error.append(e)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout_sec)
    if thread.is_alive():
        return default
    if error:
        raise error[0]
    return result[0] if result else default
