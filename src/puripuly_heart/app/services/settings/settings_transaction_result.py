from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from puripuly_heart.core.messages import (
    TRANSACTION_STATUS_SETTINGS_COMMIT_SUCCESS_RUNTIME_APPLIED,
    TRANSACTION_STATUS_SETTINGS_COMMIT_SUCCESS_RUNTIME_DEGRADED,
    TransactionResult,
)


@dataclass(slots=True)
class _ResultScope:
    current: TransactionResult | None = None


class SettingsTransactionResultOwner:
    def __init__(self) -> None:
        self._latest: TransactionResult | None = None
        self._scope: ContextVar[_ResultScope | None] = ContextVar(
            "settings_transaction_result_scope", default=None,
        )

    @property
    def current(self) -> TransactionResult | None:
        scope = self._scope.get()
        return scope.current if scope is not None else self._latest

    @contextmanager
    def capture(self):
        scope = _ResultScope()
        token = self._scope.set(scope)
        try:
            yield scope
        finally:
            self._scope.reset(token)

    def set(self, result: TransactionResult) -> None:
        self._latest = result
        scope = self._scope.get()
        if scope is not None:
            scope.current = result

    def committed(self) -> bool:
        current = self.current
        return current is not None and current.status in {
            TRANSACTION_STATUS_SETTINGS_COMMIT_SUCCESS_RUNTIME_APPLIED,
            TRANSACTION_STATUS_SETTINGS_COMMIT_SUCCESS_RUNTIME_DEGRADED,
        }


__all__ = ["SettingsTransactionResultOwner"]
