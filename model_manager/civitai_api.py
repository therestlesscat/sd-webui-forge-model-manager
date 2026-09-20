"""
Civitai API client with rate limiting and retry logic.
"""
import json
import time
import threading
import requests
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from urllib.parse import quote


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

    # Internal tRPC endpoint used by the Civitai website.
    # The public /api/v1/images endpoint stopped returning image `meta`
    # (generation parameters) - it is always null. This endpoint still
    # returns it, supports batching, and requires an API key.
    # Undocumented: treat failures as non-fatal and degrade gracefully.
    TRPC_BASE_URL = "https://civitai.com/api/trpc/"
    GENERATION_DATA_PROC = "image.getGenerationData"
    GENERATION_DATA_BATCH = 20  # 50+ returns HTTP 400

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
        params: Optional[Dict[str, Any]] = None,
        absolute_url: Optional[str] = None
    ) -> Any:
        """
        Make a rate-limited request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/models/123")
            params: Query parameters
            absolute_url: Full URL to use instead of BASE_URL + endpoint.

        Returns:
            Parsed JSON response (dict for the v1 API, list for tRPC batches).

        Raises:
            CivitaiNotFoundError: If resource not found (404)
            CivitaiRateLimitError: If rate limited and retries exhausted
            CivitaiAPIError: For other API errors
        """
        url = absolute_url or f"{self.BASE_URL}{endpoint}"
        last_error = None

        # Log auth status on first request
        auth_header = self.session.headers.get("Authorization", "")
        has_auth = bool(auth_header)
        if absolute_url and absolute_url.startswith(self.TRPC_BASE_URL):
            # Batched tRPC calls repeat the procedure name once per item
            procedures = absolute_url[len(self.TRPC_BASE_URL):].split("?")[0].split(",")
            label = f"trpc/{procedures[0]} x{len(procedures)}"
        else:
            label = endpoint or url.split("?")[0]
        print(f"[ModelManager] Request: {method} {label} (auth={'yes' if has_auth else 'no'})")

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

    def search_models(
        self,
        query: str = "",
        types: Optional[List[str]] = None,
        base_models: Optional[List[str]] = None,
        sort: str = "Most Downloaded",
        period: str = "AllTime",
        nsfw: bool = False,
        tag: str = "",
        limit: int = 10,
        cursor: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search models on Civitai using cursor-based pagination.

        Args:
            query: Search text.
            types: Model types (Checkpoint, LORA, etc).
            base_models: Base models (SD 1.5, SDXL, Pony, Flux, etc).
            sort: Sort order (Most Downloaded, Highest Rated, Newest).
            period: Time period (AllTime, Year, Month, Week, Day).
            nsfw: Include NSFW models.
            tag: Filter by tag.
            limit: Results per page.
            cursor: Cursor for pagination (from previous response's nextCursor).

        Returns:
            Dict with 'items' (models), 'metadata', and 'nextCursor'.
        """
        params = {
            "limit": limit,
            "sort": sort,
            "period": period,
        }

        if cursor:
            params["cursor"] = cursor
        if query:
            params["query"] = query
        if types:
            params["types"] = ",".join(types)
        if base_models:
            params["baseModels"] = ",".join(base_models)
        if nsfw:
            params["nsfw"] = "true"
        if tag:
            params["tag"] = tag

        data = self._request("GET", "/models", params)
        metadata = data.get("metadata", {}) or {}

        return {
            "items": data.get("items", []),
            "metadata": metadata,
            "nextCursor": metadata.get("nextCursor")
        }

    def search_tags(
        self,
        query: str = "",
        limit: int = 20,
        page: int = 1
    ) -> Dict[str, Any]:
        """
        Search tags on Civitai.

        Args:
            query: Search text to filter tags by name.
            limit: Results per page (max 200).
            page: Page number.

        Returns:
            Dict with 'items' (tags) and 'metadata' (pagination info).
        """
        params = {
            "limit": limit,
            "page": page,
        }

        if query:
            params["query"] = query

        data = self._request("GET", "/tags", params)

        return {
            "items": data.get("items", []),
            "metadata": data.get("metadata", {})
        }

    def get_model_images(
        self,
        version_id: int,
        cursor: str = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get images for a model version using cursor-based pagination.

        Args:
            version_id: Civitai model version ID.
            cursor: Cursor for pagination (from previous response's nextCursor).
            limit: Results per page (max 100 for cursor to work).

        Returns:
            Dict with 'images' and 'next_cursor' (None if no more pages).
        """
        params = {
            "modelVersionId": version_id,
            "limit": min(limit, 100),  # Use 100 to ensure cursor is returned
            "nsfw": "X"  # Include all NSFW levels up to X
        }

        if cursor:
            params["cursor"] = cursor

        try:
            data = self._request("GET", "/images", params)
        except CivitaiNotFoundError:
            return {"images": [], "next_cursor": None}

        items = data.get("items", [])
        metadata = data.get("metadata", {}) or {}

        # Get next cursor for pagination (None if no more pages)
        next_cursor = metadata.get("nextCursor")

        return {
            "images": items,
            "next_cursor": next_cursor
        }

    def get_generation_data(self, image_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """
        Get generation data (prompt, params, resources) for images.

        The public /api/v1/images endpoint returns `meta: null` for every
        image, so generation parameters come from the website's own tRPC
        endpoint instead. Requests are batched (20 per call).

        Requires an API key - returns {} without one, so callers fall back
        to whatever the public API gave them.

        Args:
            image_ids: Civitai image IDs to look up.

        Returns:
            Dict mapping image ID to its generation data. IDs that could not
            be resolved are simply absent.
        """
        if not self.api_key:
            return {}

        ids = [int(i) for i in image_ids if i]
        if not ids:
            return {}

        results: Dict[int, Dict[str, Any]] = {}

        for start in range(0, len(ids), self.GENERATION_DATA_BATCH):
            chunk = ids[start:start + self.GENERATION_DATA_BATCH]

            procedures = ",".join([self.GENERATION_DATA_PROC] * len(chunk))
            payload = {str(i): {"json": {"id": image_id}} for i, image_id in enumerate(chunk)}
            url = (
                f"{self.TRPC_BASE_URL}{procedures}"
                f"?batch=1&input={quote(json.dumps(payload))}"
            )

            try:
                data = self._request("GET", "", absolute_url=url)
            except CivitaiAPIError as e:
                print(f"[ModelManager] Generation data batch failed: {e}")
                continue

            # tRPC batch responses are a list positionally matching the input
            if not isinstance(data, list):
                print("[ModelManager] Unexpected generation data response shape")
                continue

            for index, entry in enumerate(data):
                if index >= len(chunk) or not isinstance(entry, dict):
                    continue
                # Per-entry errors are isolated - skip just that image
                if entry.get("error"):
                    continue
                result = entry.get("result") or {}
                gen_data = (result.get("data") or {}).get("json") or {}
                if gen_data:
                    results[chunk[index]] = gen_data

        return results

    def close(self):
        """Close the session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def _map_civitai_resources(resources: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Convert generation-data resources into the `civitaiResources` shape the UI
    expects (type / name / modelVersionId, used for View + Download links).
    """
    mapped = []

    for resource in resources or []:
        if not isinstance(resource, dict):
            continue

        version_id = resource.get("versionId") or resource.get("modelVersionId")
        entry = {
            "type": resource.get("modelType") or "Unknown",
            "name": resource.get("modelName") or resource.get("versionName") or "Unknown",
            "modelId": resource.get("modelId"),
            "modelVersionId": version_id,
            "modelVersionName": resource.get("versionName"),
        }

        if resource.get("strength") is not None:
            entry["weight"] = resource.get("strength")

        mapped.append(entry)

    return mapped


def enrich_images_with_generation_data(
    client: CivitaiClient,
    images: List[Dict[str, Any]]
) -> int:
    """
    Fill in missing generation metadata on images, in place.

    Only images that lack a usable prompt are looked up. Failures are logged
    and swallowed - images are left as-is rather than breaking the caller.

    Args:
        client: Civitai client to use for the lookup.
        images: Image dicts from the /images endpoint (modified in place).

    Returns:
        Number of images that were enriched.
    """
    if not images:
        return 0

    needs_lookup = [
        img.get("id") for img in images
        if img.get("id") and not (img.get("meta") or {}).get("prompt")
    ]
    if not needs_lookup:
        return 0

    try:
        generation_data = client.get_generation_data(needs_lookup)
    except Exception as e:
        print(f"[ModelManager] Generation data lookup failed: {e}")
        return 0

    if not generation_data:
        return 0

    enriched = 0

    for img in images:
        data = generation_data.get(img.get("id"))
        if not data:
            continue

        meta = data.get("meta") or {}
        if not meta:
            continue

        # Keep anything the existing meta had that the new one lacks
        merged = dict(meta)
        for key, value in (img.get("meta") or {}).items():
            merged.setdefault(key, value)

        civitai_resources = _map_civitai_resources(data.get("resources"))
        if civitai_resources:
            merged["civitaiResources"] = civitai_resources

        img["meta"] = merged
        enriched += 1

    return enriched
