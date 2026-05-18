from abc import ABC, abstractmethod

from app.schemas import ChatRequest, ChatResponse


class BaseProvider(ABC):
    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def default_model(self) -> str: ...
