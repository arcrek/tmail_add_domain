from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
import tempfile
import threading


class DomainCache:
    def __init__(self, cache_file: str):
        self._file = os.path.abspath(cache_file)
        self._lock_file = self._file + ".lock"
        self._lock = threading.RLock()
        self._domains: set[str] = set()
        self._generation: tuple[int, int, int, int] | None = None

    @contextmanager
    def _file_locked(self):
        os.makedirs(os.path.dirname(self._file), exist_ok=True)
        with open(self._lock_file, "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _read(self) -> set[str] | None:
        try:
            with open(self._file) as handle:
                data = json.load(handle)
            if not isinstance(data, list) or any(not isinstance(item, str) for item in data):
                return None
            return set(data)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def load(self) -> None:
        with self._lock, self._file_locked():
            domains = self._read()
            if domains is not None:
                self._domains = domains
            self._generation = self._file_generation()

    def contains(self, domain: str) -> bool:
        current_generation = self._file_generation()
        with self._lock:
            if current_generation == self._generation:
                return domain in self._domains
        self.load()
        with self._lock:
            return domain in self._domains

    def domains(self) -> list[str]:
        with self._lock:
            return sorted(self._domains)

    def generation(self) -> tuple[int, int, int, int]:
        with self._lock, self._file_locked():
            domains = self._read()
            if domains is not None:
                self._domains = domains
            generation = self._file_generation()
            self._generation = generation
            return generation

    def add(self, domain: str) -> None:
        self.add_many([domain])

    def add_many(self, domains: list[str]) -> None:
        with self._lock, self._file_locked():
            current = self._read()
            merged = set(self._domains) if current is None else current
            merged.update(domains)
            self._persist(merged)
            self._domains = merged
            self._generation = self._file_generation()

    def replace(
        self,
        domains: list[str],
        expected_generation: tuple[int, int, int, int] | None = None,
    ) -> bool:
        replacement = set(domains)
        with self._lock, self._file_locked():
            if expected_generation is not None:
                current_generation = self._file_generation()
                if current_generation != expected_generation:
                    current = self._read()
                    if current is not None:
                        self._domains = current
                    self._generation = current_generation
                    return False
            self._persist(replacement)
            self._domains = replacement
            self._generation = self._file_generation()
            return True

    def _file_generation(self) -> tuple[int, int, int, int]:
        try:
            stat = os.stat(self._file)
        except OSError:
            return 0, 0, 0, 0
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def _persist(self, domains: set[str]) -> None:
        directory = os.path.dirname(self._file)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{os.path.basename(self._file)}.", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(sorted(domains), handle)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._file)
            directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
