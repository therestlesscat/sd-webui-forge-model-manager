"""
Civitai API client with rate limiting and retry logic.
"""
import time
import threading
import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


class CivitaiAPIError(Exception):
    """Base exception for Civitai API errors."""
    pass


class CivitaiRateLimitError(CivitaiAPIError):
    """Rate limit exceeded."""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class CivitaiNotFoundError(CivitaiAPIError):
    """Model not found on Civitai."""
    pass


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter for API calls.

    Allows burst requests up to max_tokens, then limits to tokens_per_second.
    Thread-safe implementation.
    """

    def __init__(self, tokens_per_second: float, max_tokens: int):
        self.tokens_per_second = tokens_per_second
        self.max_tokens = max_tokens
        self.tokens = float(max_tokens)
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.tokens_per_second)
        self.last_refill = now

    def acquire(self, timeout: float = 120.0) -> bool:
        """
        Wait for a token, return True if acquired, False if timeout.

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            True if token acquired, False if timed out.
        """
        start = time.time()

        while True:
            with self._lock:
                self._refill()

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True

            # Check timeout
            if time.time() - start >= timeout:
                return False

            # Wait for next token
            wait_time = min(1.0 / self.tokens_per_second, timeout - (time.time() - start))
            if wait_time > 0:
                time.sleep(wait_time)

    def wait_time(self) -> float:
        """Get estimated wait time for next token."""
        with self._lock:
            self._refill()
            if self.tokens >= 1.0:
                return 0.0
            return (1.0 - self.tokens) / self.tokens_per_second


class CivitaiClient:
    """
    Civitai API client with rate limiting and retry logic.

    Usage:
        client = CivitaiClient.from_settings()
        version = client.get_model_by_hash("abc123...")
        model = client.get_model(version["modelId"])
        images = client.get_model_images(version["id"])
    """

    BASE_URL = "https://civitai.com/api/v1"

    # Rate limits (requests per second)
    AUTH_RATE = 2.0
    AUTH_BURST = 10
    UNAUTH_RATE = 0.5
    UNAUTH_BURST = 5

    # Retry settings
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 2.0  # seconds

    # Request timeout
    REQUEST_TIMEOUT = 30  # seconds

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the client.

        Args:
            api_key: Optional Civitai API key for higher rate limits.
        """
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SD-WebUI-Forge-Model-Manager/1.0"

        # Set up rate limiter based on auth status
        if api_key:
            self.rate_limiter = TokenBucketRateLimiter(self.AUTH_RATE, self.AUTH_BURST)
            self.session.headers["Authorization"] = f"Bearer {api_key}"
            print("[ModelManager] Civitai client initialized with API key")
        else:
            self.rate_limiter = TokenBucketRateLimiter(self.UNAUTH_RATE, self.UNAUTH_BURST)
            print("[ModelManager] Civitai client initialized without API key (lower rate limits)")

    @classmethod
    def from_settings(cls) -> "CivitaiClient":
        """Create client using API key from WebUI settings."""
        try:
            from modules import shared
            api_key = getattr(shared.opts, 'model_manager_civitai_api_key', '') or None
            print(f"[ModelManager] Read API key from settings: {'***' + api_key[-4:] if api_key and len(api_key) > 4 else ('(empty)' if not api_key else '(short)')}")
            if api_key:
                api_key = api_key.strip()
                if not api_key:
                    api_key = None
        except Exception as e:
            print(f"[ModelManager] Error reading API key from settings: {e}")
            api_key = None

        return cls(api_key)

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make a rate-limited request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/models/123")
            params: Query parameters

        Returns:
            JSON response as dict.

        Raises:
            CivitaiNotFoundError: If resource not found (404)
            CivitaiRateLimitError: If rate limited and retries exhausted
            CivitaiAPIError: For other API errors
        """
        url = f"{self.BASE_URL}{endpoint}"
        last_error = None

        # Log auth status on first request
        auth_header = self.session.headers.get("Authorization", "")
        has_auth = bool(auth_header)
        print(f"[ModelManager] Request: {method} {endpoint} (auth={'yes' if has_auth else 'no'})")

        for attempt in range(self.MAX_RETRIES + 1):
            # Wait for rate limiter
            if not self.rate_limiter.acquire(timeout=120.0):
                raise CivitaiRateLimitError(60)

            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    timeout=self.REQUEST_TIMEOUT
                )

                # Handle specific status codes
                if response.status_code == 404:
                    raise CivitaiNotFoundError(f"Not found: {endpoint}")

                if response.status_code == 429:
                    # Rate limited - get retry-after if available
                    retry_after = int(response.headers.get("Retry-After", 60))
                    if attempt < self.MAX_RETRIES:
                        print(f"[ModelManager] Rate limited, waiting {retry_after}s...")
                        time.sleep(retry_after)
                        continue
                    raise CivitaiRateLimitError(retry_after)

                if response.status_code >= 500:
                    # Server error - retry with backoff
                    if attempt < self.MAX_RETRIES:
                        wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                        print(f"[ModelManager] Server error {response.status_code}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    raise CivitaiAPIError(f"Server error: {response.status_code}")

                # Check for other errors
                response.raise_for_status()

                return response.json()

            except requests.exceptions.Timeout:
                last_error = CivitaiAPIError("Request timed out")
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    print(f"[ModelManager] Timeout, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

            except requests.exceptions.ConnectionError as e:
                last_error = CivitaiAPIError(f"Connection error: {e}")
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    print(f"[ModelManager] Connection error, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

            except (CivitaiNotFoundError, CivitaiRateLimitError):
                raise

            except Exception as e:
                last_error = CivitaiAPIError(f"Request failed: {e}")
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    time.sleep(wait_time)
                    continue

        raise last_error or CivitaiAPIError("Request failed after retries")

    def get_model_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get model version by file hash.

        Args:
            file_hash: SHA256 hash of the model file.

        Returns:
            Version info dict with embedded model reference, or None if not found.
        """
        try:
            return self._request("GET", f"/model-versions/by-hash/{file_hash}")
        except CivitaiNotFoundError:
            return None

    def get_model(self, model_id: int) -> Optional[Dict[str, Any]]:
        """
        Get full model info by ID.

        Args:
            model_id: Civitai model ID.

        Returns:
            Full model dict with all versions, or None if not found.
        """
        try:
            return self._request("GET", f"/models/{model_id}")
        except CivitaiNotFoundError:
            return None

    def get_model_images(
        self,
        version_id: int,
        limit: int = 200,
        page: int = 1
    ) -> Dict[str, Any]:
        """
        Get images for a model version (single page).

        Args:
            version_id: Civitai model version ID.
            limit: Results per page (max 200).
            page: Page number (1-based).

        Returns:
            Dict with 'images', 'total_count', 'current_page', 'total_pages'.
        """
        params = {
            "modelVersionId": version_id,
            "limit": min(limit, 200),
            "page": page,
            "nsfw": "X"  # Include all NSFW levels up to X
        }

        try:
            data = self._request("GET", "/images", params)
        except CivitaiNotFoundError:
            return {"images": [], "total_count": 0, "current_page": 1, "total_pages": 0}

        items = data.get("items", [])
        metadata = data.get("metadata", {})

        total_count = metadata.get("totalItems", len(items))
        current_page = metadata.get("currentPage", page)
        total_pages = metadata.get("totalPages", 1)

        return {
            "images": items,
            "total_count": total_count,
            "current_page": current_page,
            "total_pages": total_pages
        }

    def close(self):
        """Close the session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
