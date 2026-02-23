from __future__ import annotations

from abc import ABC, abstractmethod

from src.common.models import Bar, Signal


class Strategy(ABC):
    @abstractmethod
    def on_bar(self, bar: Bar) -> list[Signal]:
        raise NotImplementedError
