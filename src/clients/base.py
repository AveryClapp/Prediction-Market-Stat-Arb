"""Base client with retry logic and error handling."""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class Market:
    """Standardized market representation across platforms."""

    platform: str
    market_id: str
    description: str
    price: float  # Price for "Yes" outcome (0.01 to 0.99)
    url: str
    close_time: str  # ISO format timestamp


@dataclass
class PlatformStatus:
    """Platform health status."""

    platform: str
    consecutive_failures: int
    last_success: Optional[datetime]
    is_healthy: bool


class BaseClient(ABC):
    """Abstract base client with retry logic and error handling."""

    def __init__(self, platform_name: str, max_retries: int = 3, backoff_base: float = 2):
        """
        Initialize base client.

        Args:
            platform_name: Name of the platform (e.g., "Kalshi", "Polymarket")
            max_retries: Maximum number of retry attempts
            backoff_base: Base for exponential backoff calculation
        """
        self.platform_name = platform_name
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.consecutive_failures = 0
        self.last_success: Optional[datetime] = None
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    def get_status(self) -> PlatformStatus:
        """Get current platform health status."""
        return PlatformStatus(
            platform=self.platform_name,
            consecutive_failures=self.consecutive_failures,
            last_success=self.last_success,
            is_healthy=self.consecutive_failures < self.max_retries,
        )

    async def _exponential_backoff(self, attempt: int) -> None:
        """
        Sleep for exponentially increasing duration.

        Args:
            attempt: Current attempt number (0-indexed)
        """
        delay = min(self.backoff_base**attempt, 60)  # Cap at 60 seconds
        logger.debug(f"{self.platform_name}: Backing off for {delay}s (attempt {attempt + 1})")
        await asyncio.sleep(delay)

    async def fetch_with_retry(
        self, method: str, url: str, **kwargs
    ) -> Optional[httpx.Response]:
        """
        Make HTTP request with exponential backoff retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments for httpx request

        Returns:
            Response object or None if all retries failed
        """
        for attempt in range(self.max_retries):
            try:
                response = await self.client.request(method, url, **kwargs)
                response.raise_for_status()

                # Success - reset failure counter
                self.consecutive_failures = 0
                self.last_success = datetime.now()

                return response

            except httpx.HTTPStatusError as e:
                logger.warning(
                    f"{self.platform_name}: HTTP {e.response.status_code} error: {e}"
                )
                if attempt < self.max_retries - 1:
                    await self._exponential_backoff(attempt)
                else:
                    self.consecutive_failures += 1

            except (httpx.RequestError, httpx.TimeoutException) as e:
                logger.warning(f"{self.platform_name}: Request error: {e}")
                if attempt < self.max_retries - 1:
                    await self._exponential_backoff(attempt)
                else:
                    self.consecutive_failures += 1

            except Exception as e:
                logger.error(f"{self.platform_name}: Unexpected error: {e}")
                self.consecutive_failures += 1
                break

        logger.error(
            f"{self.platform_name}: Failed after {self.max_retries} attempts. "
            f"Consecutive failures: {self.consecutive_failures}"
        )
        return None

    @abstractmethod
    async def get_active_markets(self) -> list[Market]:
        """
        Fetch active binary markets from the platform.

        Returns:
            List of Market objects in standardized format

        Raises:
            NotImplementedError: Must be implemented by subclass
        """
        raise NotImplementedError("Subclass must implement get_active_markets()")

    def __repr__(self) -> str:
        status = self.get_status()
        return (
            f"{self.__class__.__name__}("
            f"platform={self.platform_name}, "
            f"healthy={status.is_healthy}, "
            f"failures={self.consecutive_failures}"
            f")"
        )
