"""Base classes and registry for mutations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel
import random

from datagen.models import Document, AuthoredScenario


class DerivedExpectation(BaseModel):
    decision: str
    reason_code: Optional[str] = None


class MutationContext:
    def __init__(
        self,
        scenario: AuthoredScenario,
        vendors_by_id: Dict[str, Any],
        pos_by_id: Dict[str, Any],
        catalog_by_sku: Dict[str, Any],
        rng: random.Random,
        all_cases: Optional[List[Any]] = None,
        constants: Optional[Any] = None,
    ):
        self.scenario = scenario
        self.vendors_by_id = vendors_by_id
        self.pos_by_id = pos_by_id
        self.catalog_by_sku = catalog_by_sku
        self.rng = rng
        self.all_cases = all_cases or []
        self.constants = constants


class Mutation(ABC):
    name: str
    params_model: Type[BaseModel]

    @abstractmethod
    def precondition(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> List[str]:
        """Returns list of error messages if preconditions are not met."""
        pass

    @abstractmethod
    def apply(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Document:
        """Returns a NEW document, never mutates input."""
        pass

    def derive(self, doc: Document, ctx: MutationContext, params: Dict[str, Any]) -> Optional[DerivedExpectation]:
        """Expected outcome if mechanically derivable."""
        return None


class MutationRegistry:
    def __init__(self):
        self._mutations: Dict[str, Mutation] = {}

    def register(self, mutation: Mutation):
        self._mutations[mutation.name] = mutation

    def get(self, name: str) -> Optional[Mutation]:
        return self._mutations.get(name)

    def list_names(self) -> List[str]:
        return sorted(self._mutations.keys())


registry = MutationRegistry()
