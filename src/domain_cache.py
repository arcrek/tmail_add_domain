from __future__ import annotations
import json
import os
import threading

class DomainCache:
    def __init__(self, cache_file: str):
        self._file = cache_file
        self._lock = threading.Lock()
        self._domains: set = set()

    def load(self) -> None:
        try:
            with open(self._file) as f:
                data = json.load(f)
            self._domains = set(data)
        except (FileNotFoundError, json.JSONDecodeError):
            self._domains = set()

    def contains(self, domain: str) -> bool:
        with self._lock:
            return domain in self._domains

    def domains(self) -> list[str]:
        with self._lock:
            return sorted(self._domains)

    def add(self, domain: str) -> None:
        with self._lock:
            self._domains.add(domain)
            self._persist()

    def add_many(self, domains: list) -> None:
        with self._lock:
            self._domains.update(domains)
            self._persist()

    def replace(self, domains: list[str]) -> None:
        with self._lock:
            replacement = set(domains)
            self._persist(replacement)
            self._domains = replacement

    def _persist(self, domains: set | None = None) -> None:
        tmp = self._file + ".tmp"
        os.makedirs(os.path.dirname(os.path.abspath(self._file)), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(sorted(self._domains if domains is None else domains), f)
        os.replace(tmp, self._file)
