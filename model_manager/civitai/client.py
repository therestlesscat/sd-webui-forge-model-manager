"""
Civitai API client with rate limiting and retry logic.
"""
import json
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import quote


class CivitaiAPIError(Exception):
    """Base exception for Civitai API errors."""
    pass


def _civitai_says(response) -> str:
    """What Civitai's answer says went wrong - its "error", or "message" - or ''."""
    try:
        body = response.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    said = body.get("error") or body.get("message")
    return said.strip() if isinstance(said, str) else ""


class CivitaiRateLimitError(CivitaiAPIError):
    """Rate limit exceeded."""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited. Retry after {retry_after}s")


class CivitaiNotFoundError(CivitaiAPIError):
    """Model not found on Civitai."""
    pass


class CivitaiAuthError(CivitaiAPIError):
    """Civitai refused the request's key (401), or what it asked for (403)."""
    def __init__(self, status: int):
        self.status = status
        super().__init__("Civitai refused the API key" if status == 401
                         else "Civitai refused the request (403)")


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


# One bucket per rate, shared by every client at that rate. Each client used
# to make its own, full: a sync, each download and every search paced itself
# alone, and together they went past the rate set.
_limiters: Dict[Tuple[float, int], TokenBucketRateLimiter] = {}
_limiters_lock = threading.Lock()


def shared_limiter(rate: float, burst: int, label: str) -> TokenBucketRateLimiter:
    """The bucket every client at this rate draws from, made on first use."""
    with _limiters_lock:
        limiter = _limiters.get((rate, burst))
        if limiter is None:
            limiter = _limiters[(rate, burst)] = TokenBucketRateLimiter(rate, burst)
            print(f"[ModelManager] Civitai requests {label}: {rate:g} req/s")
        return limiter


def api_key_from_settings() -> Optional[str]:
    """
    The Civitai API key the settings hold, trimmed, or None.

    The one place it is read. Civitai's API takes a key pasted with a space
    or a newline around it; the download header, which read it separately,
    sent it as pasted.
    """
    try:
        from modules import shared
        key = str(getattr(shared.opts, 'model_manager_civitai_api_key', '') or '').strip()
    except Exception as e:
        print(f"[ModelManager] Error reading API key from settings: {e}")
        return None
    return key or None


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
    # Civitai's tRPC endpoint accepts at most 30 procedures per request:
    # 31 is rejected with HTTP 400, 30 is not. The rate limiter charges
    # one token per request whatever the batch holds, so the difference
    # between 20 and 30 is a third off every gallery refresh.
    GENERATION_DATA_BATCH = 30

    # Rate limits (requests per second).
    # Civitai was measured serving ~10 req/s without complaint; these stay well
    # under that. AUTH_RATE is the default for the setting, not a hard cap.
    AUTH_RATE = 6.0
    AUTH_BURST = 12
    UNAUTH_RATE = 0.5
    UNAUTH_BURST = 5

    # Retry settings
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 2.0  # seconds

    # Request timeout
    REQUEST_TIMEOUT = 30  # seconds

    def __init__(
        self,
        api_key: Optional[str] = None,
        requests_per_second: Optional[float] = None
    ):
        """
        Initialize the client.

        Args:
            api_key: Optional Civitai API key for higher rate limits.
            requests_per_second: Override the authenticated request rate.
                Ignored without an API key.
        """
        self.api_key = api_key
        # Whether a 429 is waited out (Retry-After, up to MAX_RETRIES times)
        # or raised at once. A filter checking a page of models turns it off:
        # it would rather stop the page, which it can resume, than sit out
        # minutes of Retry-After with the stream showing nothing.
        self.wait_on_rate_limit = True
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "SD-WebUI-Forge-Model-Manager/1.0"

        if api_key:
            rate = float(requests_per_second or self.AUTH_RATE)
            rate = max(0.5, min(rate, 10.0))
            self.rate_limiter = shared_limiter(rate, max(int(rate * 2), 5), "with an API key")
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        else:
            self.rate_limiter = shared_limiter(self.UNAUTH_RATE, self.UNAUTH_BURST,
                                               "without an API key")

    @classmethod
    def from_settings(cls) -> "CivitaiClient":
        """Create client using API key from WebUI settings."""
        api_key = api_key_from_settings()
        rate = None
        try:
            from modules import shared
            configured = getattr(shared.opts, 'model_manager_civitai_requests_per_second', None)
            if configured:
                rate = float(configured)
        except Exception:
            pass

        return cls(api_key, requests_per_second=rate)

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
            CivitaiAuthError: If the key is refused (401, 403) - at once,
                since asking again with the same key gets the same answer
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

                if response.status_code in (401, 403):
                    raise CivitaiAuthError(response.status_code)

                if response.status_code == 429:
                    # Rate limited - get retry-after if available
                    retry_after = int(response.headers.get("Retry-After", 60))
                    if self.wait_on_rate_limit and attempt < self.MAX_RETRIES:
                        print(f"[ModelManager] Rate limited, waiting {retry_after}s...")
                        time.sleep(retry_after)
                        continue
                    raise CivitaiRateLimitError(retry_after)

                if response.status_code >= 500:
                    # Server error - retry with backoff. Civitai says why in
                    # the body, when it says anything: "Image search is
                    # temporarily overloaded - please retry." It used to be
                    # left unread, and the page said only "Server error: 503".
                    said = _civitai_says(response)
                    if attempt < self.MAX_RETRIES:
                        wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                        print(f"[ModelManager] Server error {response.status_code}"
                              f"{': ' + said if said else ''}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    raise CivitaiAPIError(f"Civitai: {said} ({response.status_code})" if said
                                          else f"Server error: {response.status_code}")

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

            except CivitaiAPIError:
                # Raised above, and already saying what happened - not to be
                # wrapped again as "Request failed: ...".
                raise

            except Exception as e:
                last_error = CivitaiAPIError(f"Request failed: {e}")
                if attempt < self.MAX_RETRIES:
                    wait_time = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                    time.sleep(wait_time)
                    continue

        raise last_error or CivitaiAPIError("Request failed after retries")

    def whoami(self) -> Dict[str, Any]:
        """
        The account the API key belongs to - its username, among others.

        Raises:
            CivitaiAuthError: If Civitai refuses the key, or there is none.
            CivitaiAPIError: If Civitai cannot be asked.
        """
        return self._request("GET", "/me")

    def check_permissions(self, version_ids: List[int], user_id: int) -> Dict[int, bool]:
        """
        Whether this account may use each of these versions - Civitai's
        permissions check, the one place that says a paid version has been
        bought (the version itself reads the same to everyone). Its default
        permission, Generate; it accepts no Download.

        Returns:
            {version id: allowed}, for those it answered.
        """
        answer = self._request("GET", "/permissions/check", params={
            "entityIds": ",".join(str(int(v)) for v in version_ids), "userId": int(user_id)})
        return {int(k): bool(v) for k, v in (answer or {}).items() if str(k).isdigit()}

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

    def get_model_version(self, version_id: int) -> Optional[Dict[str, Any]]:
        """
        Get one model version by its id: its baseModel, files, and the model
        it belongs to.

        Returns:
            Version info dict with embedded model reference, or None if not found.
        """
        try:
            return self._request("GET", f"/model-versions/{int(version_id)}")
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
        checkpoint_type: str = "",
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
            checkpoint_type: "Trained" or "Merge". Checkpoints only; the API
                rejects anything else, so an empty value is left off.
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
        if checkpoint_type in ("Trained", "Merge"):
            params["checkpointType"] = checkpoint_type

        data = self._request("GET", "/models", params)
        metadata = data.get("metadata", {}) or {}

        return {
            "items": data.get("items", []),
            "metadata": metadata,
            "nextCursor": metadata.get("nextCursor")
        }

    # /models accepts at most 100 ids, and limit caps at 100.
    MODELS_BY_ID_BATCH = 100

    # Civitai accepts checkpointType as a filter but never returns it as a
    # field - it is on neither the model nor the version payload, from either
    # /models or /models/{id}. So the value is learned from which filtered
    # query a model comes back in, rather than read from a response.
    CHECKPOINT_TYPES = ("Trained", "Merge")

    def get_checkpoint_types(self, model_ids: List[int]) -> Dict[int, str]:
        """
        Which of these checkpoint models are trained, and which are merges.

        Asks once per type per batch of a hundred ids and takes the answer from
        set membership: a model returned by the Trained query is trained, one
        returned by the Merge query is a merge, and one returned by neither is
        left out. Over this library the two sets are disjoint and together with
        the leftovers they partition the batch exactly, which is what says the
        server is applying both filters rather than ignoring one.

        Since that is inference rather than a documented field, a batch whose
        answers do not partition it is discarded rather than guessed at.

        Args:
            model_ids: Civitai model ids, which should be checkpoints. Asking
                about anything else simply returns nothing for it.

        Returns:
            Model id -> "Trained" or "Merge". Ids with no answer are absent.
        """
        ids = [int(i) for i in model_ids if i]
        if not ids:
            return {}

        out: Dict[int, str] = {}

        for start in range(0, len(ids), self.MODELS_BY_ID_BATCH):
            batch = ids[start:start + self.MODELS_BY_ID_BATCH]
            wanted = set(batch)
            answers: Dict[str, set] = {}

            for kind in self.CHECKPOINT_TYPES:
                try:
                    data = self._request("GET", "/models", params={
                        "ids": ",".join(str(i) for i in batch),
                        "checkpointType": kind,
                        "limit": self.MODELS_BY_ID_BATCH,
                    })
                except CivitaiAPIError as e:
                    print(f"[ModelManager] checkpointType {kind} batch failed: {e}")
                    answers = {}
                    break

                # An id we did not ask about means `ids` was not applied, and
                # the whole answer is about somebody else's models.
                returned = {m.get("id") for m in (data.get("items") or []) if m.get("id")}
                answers[kind] = returned & wanted
                if returned - wanted:
                    print("[ModelManager] checkpointType answer included ids that were "
                          "not asked for; ignoring this batch")
                    answers = {}
                    break

            if len(answers) != len(self.CHECKPOINT_TYPES):
                continue

            trained, merged = answers["Trained"], answers["Merge"]
            if trained & merged:
                print("[ModelManager] a model came back as both Trained and Merge; "
                      "ignoring this batch")
                continue

            for model_id in trained:
                out[model_id] = "Trained"
            for model_id in merged:
                out[model_id] = "Merge"

        return out

    def get_models_by_ids(self, model_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """
        Fetch several models in one request each 100, keyed by id.

        A metadata refresh needs the full model payload for every model in the
        library. Asking per model is one call each; `ids` collapses that to one
        call per hundred, which is the difference between minutes and seconds.

        Ids Civitai no longer serves are simply absent from the result, so
        callers must treat a missing key as "not found" rather than an error.

        Args:
            model_ids: Civitai model ids.

        Returns:
            Dict of model id to the model payload.
        """
        found: Dict[int, Dict[str, Any]] = {}
        unique = list(dict.fromkeys(int(m) for m in model_ids if m))

        for start in range(0, len(unique), self.MODELS_BY_ID_BATCH):
            batch = unique[start:start + self.MODELS_BY_ID_BATCH]
            data = self._request("GET", "/models", {
                "ids": ",".join(str(m) for m in batch),
                "limit": len(batch),
                # Without it Civitai strips every showcase image but PG, and
                # the version's cover goes with them - see version_covers().
                "nsfw": "true",
            })
            for item in (data or {}).get("items", []) or []:
                if item.get("id"):
                    found[item["id"]] = item

        return found

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

    def get_enums(self) -> Dict[str, List[str]]:
        """
        Fetch the enums Civitai accepts as filter values.

        Keys include ModelType, BaseModel, ActiveBaseModel (the subset still
        being published) and BaseModelType. Hardcoding these goes stale every
        time Civitai ships a new base model.

        Returns:
            Dict of enum name to list of values.
        """
        data = self._request("GET", "/enums")
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items() if isinstance(v, list)}

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

    def get_generation_data(self, image_ids: List[int], workers: int = 1,
                            errors: Optional[Dict[int, Exception]] = None
                            ) -> Dict[int, Dict[str, Any]]:
        """
        Get generation data (prompt, params, resources) for images.

        The public /api/v1/images endpoint returns `meta: null` for every
        image, so generation parameters come from the website's own tRPC
        endpoint instead, GENERATION_DATA_BATCH ids per request.

        Requires an API key - returns {} without one, so callers fall back
        to whatever the public API gave them.

        Args:
            image_ids: Civitai image IDs to look up.
            workers: Requests in flight at once. The rate limiter still paces
                them, so this only saves waiting on Civitai: a gallery page's
                four requests took 0.38 s one after another.
            errors: Filled with each id whose request failed, and why, for a
                caller that treats "no prompt" and "not known" differently.

        Returns:
            Dict mapping image ID to its generation data. IDs that could not
            be resolved are simply absent.
        """
        if not self.api_key:
            return {}

        ids = [int(i) for i in image_ids if i]
        if not ids:
            return {}

        chunks = [ids[start:start + self.GENERATION_DATA_BATCH]
                  for start in range(0, len(ids), self.GENERATION_DATA_BATCH)]

        def fetch(chunk):
            procedures = ",".join([self.GENERATION_DATA_PROC] * len(chunk))
            payload = {str(i): {"json": {"id": image_id}} for i, image_id in enumerate(chunk)}
            url = (
                f"{self.TRPC_BASE_URL}{procedures}"
                f"?batch=1&input={quote(json.dumps(payload))}"
            )
            try:
                return chunk, self._request("GET", "", absolute_url=url), None
            except CivitaiAPIError as e:
                print(f"[ModelManager] Generation data batch failed: {e}")
                return chunk, None, e

        if workers > 1 and len(chunks) > 1:
            with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as executor:
                answers = list(executor.map(fetch, chunks))
        else:
            answers = [fetch(chunk) for chunk in chunks]

        results: Dict[int, Dict[str, Any]] = {}
        for chunk, data, error in answers:
            if error is not None:
                if errors is not None:
                    errors.update((image_id, error) for image_id in chunk)
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


