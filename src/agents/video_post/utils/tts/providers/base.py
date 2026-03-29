from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas import TtsSynthesisBatchResult, TtsSynthesisContext, TtsSynthesisRequest


class TtsProvider(ABC):
    provider_name = ""

    @abstractmethod
    async def synthesize_many(
        self,
        requests: list[TtsSynthesisRequest],
        context: TtsSynthesisContext,
    ) -> TtsSynthesisBatchResult:
        raise NotImplementedError

    async def release(self) -> None:
        return None
