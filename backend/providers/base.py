from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class BaseProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(self, messages: List[Dict[str, Any]],
             tools: Optional[List[Dict[str, Any]]] = None,
             model: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError