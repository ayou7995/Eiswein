"""Ticker master-table queries."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Ticker


class TickerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def by_symbol(self, symbol: str) -> Ticker | None:
        stmt = select(Ticker).where(Ticker.symbol == symbol.upper())
        return self._session.execute(stmt).scalar_one_or_none()

    def upsert(self, *, symbol: str, name: str | None = None) -> Ticker:
        existing = self.by_symbol(symbol)
        if existing is not None:
            if name is not None and existing.name != name:
                existing.name = name
            return existing
        ticker = Ticker(symbol=symbol.upper(), name=name)
        self._session.add(ticker)
        self._session.flush()
        return ticker

    def deactivate(self, ticker: Ticker) -> None:
        ticker.is_active = False
        self._session.flush()
