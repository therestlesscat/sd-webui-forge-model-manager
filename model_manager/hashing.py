"""
Working out what a file on disk actually is.

Civitai identifies a model by the hash of its bytes, and there are six of them
in circulation - different tools settled on different ones, so a lookup tries
them in turn until one is recognised.

Hashing means reading the whole file, which for a library of checkpoints is
the slowest thing this extension does. Everything that can avoid it does:
results are stored, a sidecar written by another tool is read instead where
one exists, and a lookup that already failed is not repeated.
"""
import hashlib
import json
import os
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Try to import blake3, fall back gracefully if not available
try:
    import blake3
    BLAKE3_AVAILABLE = True
except ImportError:
    BLAKE3_AVAILABLE = False
    print("[ModelManager] Warning: blake3 not installed, BLAKE3 hash fallback disabled")


@dataclass
class HashResult:
    """Result of hash calculation with all computed hashes."""
    sha256: Optional[str] = None          # Full file SHA256 (64 chars)
    autov2: Optional[str] = None          # First 10 chars of SHA256
    autov3: Optional[str] = None          # First 12 chars of tensor-only SHA256 (safetensors)
    autov1: Optional[str] = None          # SHA256 of 64KB at 1MB offset, first 8 chars
    crc32: Optional[str] = None           # Full file CRC32 (8 chars)
    blake3: Optional[str] = None          # Full file BLAKE3 (64 chars)
    tensor_sha256: Optional[str] = None   # Full tensor-only SHA256 (safetensors)

    # Hash kinds this class does not model, carried through untouched. A scan
    # stores every kind Civitai names, lowercased, and Civitai names more than
    # the six above - sha256_12 on 412 of this library's versions, sshs_12 on
    # three. Without somewhere to put them, a metadata refresh read the seven
    # it knew and wrote back only those, so the rest were dropped on every
    # sync. sha256_12 is a prefix of sha256 and could be recomputed; sshs_12
    # could not, and was simply lost.
    extra: Dict[str, str] = field(default_factory=dict)

    KNOWN = ("sha256", "autov2", "autov3", "autov1",
             "crc32", "blake3", "tensor_sha256")

    @classmethod
    def from_stored(cls, stored: Optional[Dict[str, str]]) -> "HashResult":
        """Rebuild from the dict _hashes_to_dict() wrote to the database.

        A metadata refresh reuses hashes an earlier sync already computed,
        rather than reading every byte of the file again. Kinds this class
        has no field for survive the trip in `extra`.
        """
        stored = stored or {}
        if not isinstance(stored, dict):
            return cls()
        return cls(
            extra={k: v for k, v in stored.items()
                   if k not in cls.KNOWN and v},
            **{name: stored.get(name) for name in cls.KNOWN}
        )

    def to_dict(self) -> Dict[str, str]:
        """Every hash held here, in the form the database stores."""
        out = {name: getattr(self, name) for name in self.KNOWN
               if getattr(self, name)}
        # A named field wins over a stray key of the same name.
        for key, value in self.extra.items():
            out.setdefault(key, value)
        return out


class ModelHasher:
    """
    Calculate multiple hash types for model files.

    Supports:
    - SHA256: Full file hash
    - AutoV2: First 10 chars of full SHA256
    - AutoV3: First 12 chars of tensor-only SHA256 (safetensors only)
    - AutoV1: SHA256 of 64KB at 1MB offset, first 8 chars
    - CRC32: Full file CRC32
    - BLAKE3: Full file BLAKE3 hash
    """

    CHUNK_SIZE = 1024 * 1024  # 1MB chunks for reading

    @classmethod
    def calculate_all(cls, file_path: str) -> HashResult:
        """
        Calculate all hash types for a file.

        For safetensors files, also calculates tensor-only hashes.

        Args:
            file_path: Path to the model file.

        Returns:
            HashResult with all computed hashes.
        """
        result = HashResult()
        is_safetensors = file_path.lower().endswith('.safetensors')

        try:
            # Calculate full file hashes in a single pass
            sha256_hasher = hashlib.sha256()
            blake3_hasher = blake3.blake3() if BLAKE3_AVAILABLE else None
            crc = 0

            # For AutoV1: need to capture 64KB at 1MB offset
            autov1_data = b""
            autov1_offset = 1048576  # 1MB
            autov1_size = 65536      # 64KB
            bytes_read = 0

            with open(file_path, "rb") as f:
                # For safetensors, read header size first
                header_size = 0
                if is_safetensors:
                    header_bytes = f.read(8)
                    if len(header_bytes) == 8:
                        header_size = int.from_bytes(header_bytes, "little")
                        # Update hashes with header size bytes
                        sha256_hasher.update(header_bytes)
                        if blake3_hasher:
                            blake3_hasher.update(header_bytes)
                        crc = zlib.crc32(header_bytes, crc)
                        bytes_read = 8

                        # Check if 1MB offset falls within header
                        if autov1_offset < bytes_read:
                            autov1_data = header_bytes[autov1_offset:autov1_offset + autov1_size]

                # Read rest of file
                for chunk in iter(lambda: f.read(cls.CHUNK_SIZE), b""):
                    sha256_hasher.update(chunk)
                    if blake3_hasher:
                        blake3_hasher.update(chunk)
                    crc = zlib.crc32(chunk, crc)

                    # Capture AutoV1 data if we're in the right range
                    chunk_start = bytes_read
                    chunk_end = bytes_read + len(chunk)

                    if chunk_start < autov1_offset + autov1_size and chunk_end > autov1_offset:
                        # Calculate overlap with AutoV1 range
                        start_in_chunk = max(0, autov1_offset - chunk_start)
                        end_in_chunk = min(len(chunk), autov1_offset + autov1_size - chunk_start)
                        autov1_data += chunk[start_in_chunk:end_in_chunk]

                    bytes_read += len(chunk)

            # Store full file hashes
            result.sha256 = sha256_hasher.hexdigest().upper()
            result.autov2 = result.sha256[:10]
            result.crc32 = format(crc & 0xFFFFFFFF, '08X')

            if blake3_hasher:
                result.blake3 = blake3_hasher.hexdigest().upper()

            # Calculate AutoV1 if we have enough data
            if len(autov1_data) >= autov1_size:
                autov1_hash = hashlib.sha256(autov1_data[:autov1_size]).hexdigest().upper()
                result.autov1 = autov1_hash[:8]

            # For safetensors, calculate tensor-only hash (AutoV3)
            if is_safetensors and header_size > 0:
                result.tensor_sha256, result.autov3 = cls._calculate_tensor_hash(file_path, header_size)

        except Exception as e:
            print(f"[ModelManager] Error calculating hashes for {os.path.basename(file_path)}: {e}")

        return result

    @classmethod
    def _calculate_tensor_hash(cls, file_path: str, header_size: int) -> Tuple[Optional[str], Optional[str]]:
        """
        Calculate tensor-only SHA256 for safetensors files.

        Args:
            file_path: Path to safetensors file.
            header_size: Size of the header (from first 8 bytes).

        Returns:
            Tuple of (full tensor SHA256, AutoV3 - first 12 chars).
        """
        try:
            sha256_hasher = hashlib.sha256()
            offset = 8 + header_size  # Skip header size bytes + header

            with open(file_path, "rb") as f:
                f.seek(offset)
                for chunk in iter(lambda: f.read(cls.CHUNK_SIZE), b""):
                    sha256_hasher.update(chunk)

            tensor_sha256 = sha256_hasher.hexdigest().upper()
            autov3 = tensor_sha256[:12]
            return tensor_sha256, autov3

        except Exception as e:
            print(f"[ModelManager] Error calculating tensor hash: {e}")
            return None, None

    @classmethod
    def get_fallback_order(cls, file_path: str) -> List[str]:
        """
        Get the order of hash types to try for lookup.

        Args:
            file_path: Path to model file (to check if safetensors).

        Returns:
            List of hash type names in fallback order.
        """
        is_safetensors = file_path.lower().endswith('.safetensors')

        # Base order: SHA256 -> CRC32 -> BLAKE3 -> AutoV1 -> AutoV2
        order = ["sha256", "crc32", "blake3", "autov1", "autov2"]

        # For safetensors, add AutoV3 after SHA256 (most likely to work for modified files)
        if is_safetensors:
            order.insert(1, "autov3")

        return order

    @classmethod
    def load_cm_info_hashes(cls, file_path: str) -> Optional[Dict[str, str]]:
        """
        Load hashes from .cm-info.json file if it exists.

        Args:
            file_path: Path to model file.

        Returns:
            Dict of hash type -> hash value, or None if not found.
        """
        base = os.path.splitext(file_path)[0]
        cm_info_path = base + ".cm-info.json"

        if not os.path.exists(cm_info_path):
            return None

        try:
            with open(cm_info_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            hashes = data.get("Hashes", {})
            if hashes:
                # Normalize to our format (uppercase)
                return {k.lower(): v.upper() for k, v in hashes.items()}
        except Exception as e:
            print(f"[ModelManager] Error reading .cm-info.json: {e}")

        return None
