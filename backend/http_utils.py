"""HTTP utilities: aiohttp session management and retry logic."""
import asyncio
import logging
import aiohttp
from config import REQUEST_TIMEOUT, MAX_RETRIES, RETRY_BASE_DELAY, RETRY_BACKOFF_FACTOR, RATE_LIMIT_BACKOFF

logger = logging.getLogger(__name__)


async def create_session() -> aiohttp.ClientSession:
    """Create an aiohttp session with default timeout."""
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    return aiohttp.ClientSession(timeout=timeout)


async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict = None) -> dict:
    """
    Fetch JSON from a URL with retry and exponential backoff.

    Raises on final failure after exhausting retries.
    """
    last_error = None
    delay = RETRY_BASE_DELAY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 429:
                    logger.warning("Rate limited (429) on %s, backing off %.1fs", url, RATE_LIMIT_BACKOFF)
                    await asyncio.sleep(RATE_LIMIT_BACKOFF)
                    continue
                resp.raise_for_status()
                return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                logger.warning("Attempt %d/%d failed for %s: %s — retrying in %.1fs",
                               attempt, MAX_RETRIES, url, exc, delay)
                await asyncio.sleep(delay)
                delay *= RETRY_BACKOFF_FACTOR
            else:
                logger.error("All %d attempts failed for %s: %s", MAX_RETRIES, url, exc)

    raise last_error  # type: ignore[misc]
