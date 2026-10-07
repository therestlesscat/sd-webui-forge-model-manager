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
from typing import Any, Dict, List, Optional

from .remembered import Remembered
from .console import say

# Try to import blake3, fall back gracefully if not available
try:
    import blake3
    BLAKE3_AVAILABLE = True
except ImportError:
    BLAKE3_AVAILABLE = False
    say("Warning: blake3 not installed, BLAKE3 hash fallback disabled")


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

    # Hash kinds this class does not model, carried through untouched. Scan
    # Disk stored every kind Civitai names, lowercased, and Civitai names more than
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

    A sync reads a file for SHA-256 first (calculate_first), with AutoV2 and
    AutoV1, which come free; the rest (complete) only when none of those is
    known to Civitai, or Civitai's own list for the file does not say them.
    AutoV3 costs as much as SHA-256 again, BLAKE3 and CRC32 about as much
    between them, and Civitai answers most files by their SHA-256: hashing
    every kind up front ran at half the speed the disk could read.
    """

    CHUNK_SIZE = 1024 * 1024  # 1MB chunks for reading

    #: Asked first: SHA-256 and what comes free with it.
    FIRST_LOOKUPS = ("sha256", "autov1", "autov2")

    @classmethod
    def calculate_all(cls, file_path: str) -> HashResult:
        """
        Calculate all hash types for a file, in one read.

        For safetensors files, also calculates tensor-only hashes.

        Args:
            file_path: Path to the model file.

        Returns:
            HashResult with all computed hashes.
        """
        return cls._read(file_path, HashResult(), full=True, tensor=True, blake=True, crc=True)

    @classmethod
    def calculate_first(cls, file_path: str) -> HashResult:
        """
        What a sync asks Civitai with first, in one read: SHA-256, AutoV2
        (its first ten characters) and AutoV1 (64 KB of the file).
        """
        return cls._read(file_path, HashResult(), full=True, tensor=False, blake=False, crc=False)

    @classmethod
    def complete(cls, file_path: str, result: HashResult) -> HashResult:
        """
        Read from the file what `result` lacks of AutoV3, BLAKE3 and CRC32 -
        a second read, made only when something is missing. What it has is
        left as it is.
        """
        tensor = (file_path.lower().endswith('.safetensors')
                  and not result.tensor_sha256 and not result.autov3)
        blake = BLAKE3_AVAILABLE and not result.blake3
        crc = not result.crc32
        if not (tensor or blake or crc):
            return result
        return cls._read(file_path, result, full=False, tensor=tensor, blake=blake, crc=crc)

    @classmethod
    def _read(cls, file_path: str, result: HashResult, full: bool, tensor: bool,
              blake: bool, crc: bool) -> HashResult:
        """
        One read of the file, into `result`: SHA-256, AutoV2 and AutoV1 with
        `full`; the tensor-only SHA-256 and AutoV3 with `tensor` (safetensors
        only); BLAKE3 with `blake`; CRC32 with `crc`.
        """
        is_safetensors = file_path.lower().endswith('.safetensors')

        try:
            sha256_hasher = hashlib.sha256() if full else None
            blake3_hasher = blake3.blake3() if blake and BLAKE3_AVAILABLE else None
            crc_value = 0

            def feed(data: bytes) -> None:
                nonlocal crc_value
                if sha256_hasher is not None:
                    sha256_hasher.update(data)
                if blake3_hasher is not None:
                    blake3_hasher.update(data)
                if crc:
                    crc_value = zlib.crc32(data, crc_value)

            # AutoV3 hashes a safetensors file's tensors, skipping the header.
            # Those bytes go past in this same read, so they are hashed here
            # rather than in a pass of their own over the whole file.
            tensor_hasher = None
            tensor_offset = 0

            # For AutoV1: need to capture 64KB at 1MB offset
            autov1_data = b""
            autov1_offset = 1048576  # 1MB
            autov1_size = 65536      # 64KB
            bytes_read = 0

            with open(file_path, "rb") as f:
                # For safetensors, read header size first
                if is_safetensors:
                    header_bytes = f.read(8)
                    # Hashed whatever they hold: a file too short to carry a
                    # header length is not a safetensors file whatever it is
                    # called, and hashing it as empty would give every such
                    # file one hash.
                    feed(header_bytes)
                    bytes_read = len(header_bytes)
                    if len(header_bytes) == 8:
                        header_size = int.from_bytes(header_bytes, "little")
                        if header_size > 0 and tensor:
                            # 8 bytes of length, then the header itself
                            tensor_offset = 8 + header_size
                            tensor_hasher = hashlib.sha256()

                # Read rest of file
                for chunk in iter(lambda: f.read(cls.CHUNK_SIZE), b""):
                    feed(chunk)

                    chunk_start = bytes_read
                    chunk_end = bytes_read + len(chunk)

                    # The tensors, once this chunk reaches past the header
                    if tensor_hasher is not None and chunk_end > tensor_offset:
                        tensor_hasher.update(
                            chunk[max(0, tensor_offset - chunk_start):]
                        )

                    # Capture AutoV1 data if we're in the right range
                    if full and chunk_start < autov1_offset + autov1_size and chunk_end > autov1_offset:
                        start_in_chunk = max(0, autov1_offset - chunk_start)
                        end_in_chunk = min(len(chunk), autov1_offset + autov1_size - chunk_start)
                        autov1_data += chunk[start_in_chunk:end_in_chunk]

                    bytes_read += len(chunk)

            if full:
                result.sha256 = sha256_hasher.hexdigest().upper()
                result.autov2 = result.sha256[:10]
                # Calculate AutoV1 if we have enough data
                if len(autov1_data) >= autov1_size:
                    result.autov1 = hashlib.sha256(autov1_data[:autov1_size]).hexdigest().upper()[:8]
            if crc:
                result.crc32 = format(crc_value & 0xFFFFFFFF, '08X')
            if blake3_hasher is not None:
                result.blake3 = blake3_hasher.hexdigest().upper()
            # For safetensors, the tensor-only hash (AutoV3), gathered above
            if tensor_hasher is not None:
                result.tensor_sha256 = tensor_hasher.hexdigest().upper()
                result.autov3 = result.tensor_sha256[:12]

        except Exception as e:
            say(f"Error calculating hashes for {os.path.basename(file_path)}: {e}")

        return result

    @classmethod
    def later_lookups(cls, file_path: str) -> List[str]:
        """
        Asked only when none of FIRST_LOOKUPS is known to Civitai: kinds a
        second read gives (complete). AutoV3 first, for a safetensors file -
        the tensors alone, so it still finds a file whose header was edited.
        """
        order = ["blake3", "crc32"]
        if file_path.lower().endswith('.safetensors'):
            order.insert(0, "autov3")
        return order


# ---------------------------------------------------------------- trusting stored hashes
# A file's hashes are read from its bytes once, and kept with what the file
# was then (`hashes_checked` on its row): its size and modified time to the
# nanosecond, not as local time - a clock moved to another time zone would
# make every file in the library look changed, and gigabytes be read again.
# Only hashes read from the file itself, or checked against it by a download,
# carry one; a sidecar's never do.

def fingerprint(path: str) -> Optional[str]:
    """What a file is, as far as the disk says without reading it; None if it cannot be read."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return f"{stat.st_size}:{stat.st_mtime_ns}"


# ---------------------------------------------------------------- reading stored hashes
# Stored hashes arrive in either case - the hasher writes values upper case,
# Civitai's lists and older rows lower - and every reader used to fold them
# itself (#62). Read them through here: kinds and values lower case, the form
# they are compared in. tests/tools/check_hash_access.py fails on a read of
# file_hashes, or of resource_hashes, that does not come through this module.

def read_hashes(stored: Any) -> Dict[str, str]:
    """
    A file's stored hashes - a dict, the JSON text a row holds, or nothing -
    as {kind: value}, both lower case, empty values left out.
    """
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except ValueError:
            return {}
    if not isinstance(stored, dict):
        return {}
    return {str(k).lower(): str(v).strip().lower() for k, v in stored.items() if v}


def hash_key(value: Any) -> str:
    """A single hash as it is compared and kept - resource_hashes' key."""
    return str(value or "").strip().lower()


# ---------------------------------------------------------------- one file's sha256
# For confirming a file found by name is the one an image used, before any
# sync has stored its hashes. Kept per file until it changes: a gallery asks
# about the same few LoRAs again and again. No bound - one entry a file, and
# one dropped would mean reading a file of gigabytes again.
_sha256_seen = Remembered()


def file_sha256(path: str) -> Optional[str]:
    """The file's SHA-256, lower case; None if it cannot be read."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    known = _sha256_seen.get(path)
    if known and known[:2] == (stat.st_mtime, stat.st_size):
        return known[2]
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    found = digest.hexdigest()
    _sha256_seen[path] = (stat.st_mtime, stat.st_size, found)
    return found


def names_this_file(stored: Optional[Dict[str, str]], path: str, image_hash: str) -> bool:
    """
    Whether a hash an image gives for a resource is this file's. Images give
    AutoV2 - SHA-256's first ten characters - or twelve, or the whole of it;
    each is a start of the file's SHA-256, stored by a sync or worked out here.
    """
    wanted = hash_key(image_hash)
    if len(wanted) < 8:
        return False
    stored = read_hashes(stored)
    if stored.get("sha256"):
        return stored["sha256"].startswith(wanted)
    if any(value and (value == wanted or value.startswith(wanted)) for value in stored.values()):
        return True
    full = file_sha256(path)
    return bool(full) and full.startswith(wanted)
