"""Placeholder fake Oura server primitives for future integration evals."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class FakeOuraServer:
    """Records fixture requests without starting a network server yet."""

    requests: list[str] = field(default_factory=list)
    base_url: str = "http://127.0.0.1:0"

    def record(self, path: str) -> None:
        self.requests.append(path)


@contextmanager
def run_fake_oura_server() -> Iterator[FakeOuraServer]:
    """Yield a fake server object for import-safe smoke tests."""

    yield FakeOuraServer()
