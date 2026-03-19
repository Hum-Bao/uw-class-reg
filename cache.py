"""Registration data cache management.

This module provides caching functionality for UW registration data
to reduce API calls and improve performance.
"""

import json
import time
from pathlib import Path
from typing import Any, cast

from constants import CACHE_DIRECTORY, CACHE_FILE_NAME


class RegistrationCache:
    """Manages local file-based caching of registration data."""

    def __init__(
        self,
        cache_file: Path | None = None,
    ) -> None:
        """Initialize the cache manager.

        Args:
            cache_file: Optional custom cache file path. Uses default if None.

        """
        if cache_file is None:
            cache_file = Path(CACHE_DIRECTORY) / CACHE_FILE_NAME
        self.cache_file: Path = cache_file

    def _load(self) -> dict[str, Any]:
        """Load cache data from file.

        Returns:
            Dictionary containing cache data with 'registrations' key.

        """
        if not self.cache_file.exists():
            return {"registrations": {}}

        try:
            with self.cache_file.open("r", encoding="utf-8") as cache_handle:
                data = json.load(cache_handle)
        except (json.JSONDecodeError, OSError):
            return {"registrations": {}}
        else:
            if not isinstance(data, dict):
                return {"registrations": {}}
            typed_data: dict[str, Any] = cast("dict[str, Any]", data)
            typed_data.setdefault("registrations", {})
            return typed_data

    def _save(self, cache_data: dict[str, Any]) -> None:
        """Save cache data to file.

        Args:
            cache_data: Dictionary containing cache data to persist.

        """
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_file.open("w", encoding="utf-8") as cache_handle:
            json.dump(cache_data, cache_handle, indent=2)

    def get_registration(
        self,
        quarter_code: str,
        max_age_seconds: int,
    ) -> dict[str, Any] | None:
        """Get cached registration data for a quarter if fresh enough.

        Args:
            quarter_code: Quarter code in YYYYQ format.
            max_age_seconds: Maximum age of cached data in seconds.

        Returns:
            Cached registration data if available and fresh, None otherwise.

        """
        cache_data = self._load()
        registrations = cache_data.get("registrations", {})
        quarter_cache = registrations.get(quarter_code)

        if not isinstance(quarter_cache, dict):
            return None

        typed_cache: dict[str, Any] = cast("dict[str, Any]", quarter_cache)
        fetched_at = typed_cache.get("fetched_at")
        cached_payload = typed_cache.get("data")

        if (
            isinstance(fetched_at, (int, float))
            and isinstance(cached_payload, dict)
            and time.time() - fetched_at <= max_age_seconds
        ):
            return cast("dict[str, Any]", cached_payload)

        return None

    def save_registration(
        self,
        quarter_code: str,
        registration_data: dict[str, Any],
    ) -> None:
        """Save registration data to cache with current timestamp.

        Args:
            quarter_code: Quarter code in YYYYQ format.
            registration_data: Registration data to cache.

        """
        cache_data = self._load()
        registrations = cache_data.get("registrations", {})
        registrations[quarter_code] = {
            "fetched_at": time.time(),
            "data": registration_data,
        }
        cache_data["registrations"] = registrations
        self._save(cache_data)

    def invalidate(self, quarter_code: str | None = None) -> None:
        """Clear cached registration data for one quarter or all quarters.

        Args:
            quarter_code: Specific quarter to invalidate, or None to clear all.

        """
        cache_data = self._load()
        registrations = cache_data.get("registrations", {})

        if quarter_code is None:
            cache_data["registrations"] = {}
        else:
            registrations.pop(quarter_code, None)
            cache_data["registrations"] = registrations

        self._save(cache_data)
