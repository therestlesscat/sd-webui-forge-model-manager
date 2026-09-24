"""
Talking to Civitai.

  client.py         the HTTP client: auth, rate limiting, retries, endpoints
  prompt_filter.py  finding models whose images carry a usable prompt
  size_filter.py    finding models whose download is a given size
  licensing.py      whether a version has to be paid for

Import what you need from here; the split behind it is about what the code is
for, not about what callers should know.
"""
from .client import (
    CivitaiAPIError,
    CivitaiClient,
    CivitaiNotFoundError,
    CivitaiRateLimitError,
    TokenBucketRateLimiter,
)
from .licensing import paid_access_info
from .prompt_filter import (
    apply_generation_data,
    decode_filter_token,
    encode_filter_token,
    enrich_images_with_generation_data,
    generation_ids_needing_lookup,
    image_has_usable_prompt,
    iter_models_with_usable_prompts,
    keep_generation_data,
    search_models_with_usable_prompts,
)
from .size_filter import primary_file_size_kb, size_range_check

__all__ = [
    "CivitaiAPIError", "CivitaiClient", "CivitaiNotFoundError",
    "CivitaiRateLimitError", "TokenBucketRateLimiter",
    "paid_access_info",
    "apply_generation_data", "decode_filter_token", "encode_filter_token",
    "enrich_images_with_generation_data", "generation_ids_needing_lookup",
    "image_has_usable_prompt", "keep_generation_data",
    "iter_models_with_usable_prompts", "search_models_with_usable_prompts",
    "primary_file_size_kb", "size_range_check",
]
