"""
Data models for Model Manager.
Defines structures for models, versions, images, and metadata.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
import os


class NSFWLevel(Enum):
    """NSFW content levels from Civitai."""
    PG = "PG"
    PG13 = "PG-13"
    R = "R"
    X = "X"
    XXX = "XXX"
    BANNED = "Banned"
    UNKNOWN = "Unknown"

    @classmethod
    def from_string(cls, value) -> "NSFWLevel":
        """Convert string/int to NSFWLevel, handling various formats."""
        if value is None or value == "":
            return cls.UNKNOWN

        # Handle integer values (Civitai uses bitmask for nsfwLevel)
        # Bits: 1=None/SFW, 2=Soft, 4=Mature, 8=X, 16=XXX, 32=Banned
        # Value can be combination (e.g., 29 = 1+4+8+16 = has None+Mature+X+XXX content)
        # We take the highest set bit as the effective NSFW level
        if isinstance(value, (int, float)):
            int_val = int(value)
            # Map bit positions to levels (highest to lowest)
            bit_mapping = [
                (32, cls.BANNED),
                (16, cls.XXX),
                (8, cls.X),
                (4, cls.R),      # Mature
                (2, cls.PG13),   # Soft
                (1, cls.PG),     # None/SFW
            ]
            # Find highest set bit
            for bit, level in bit_mapping:
                if int_val & bit:
                    return level
            return cls.UNKNOWN

        # Handle boolean
        if isinstance(value, bool):
            return cls.R if value else cls.PG

        # Convert to string and normalize
        normalized = str(value).upper().replace("-", "").replace(" ", "")

        mapping = {
            "PG": cls.PG,
            "PG13": cls.PG13,
            "R": cls.R,
            "X": cls.X,
            "XXX": cls.XXX,
            "BANNED": cls.BANNED,
            "NONE": cls.UNKNOWN,  # "None" means no rating assigned
            "FALSE": cls.PG,  # Boolean false = not NSFW = PG
            "TRUE": cls.R,  # Legacy boolean true -> R
            # Also handle "Soft", "Mature" etc. from some API responses
            "SOFT": cls.PG13,
            "MATURE": cls.R,
        }

        return mapping.get(normalized, cls.UNKNOWN)

    @classmethod
    def severity_order(cls) -> List["NSFWLevel"]:
        """Return levels in order of severity (least to most).
        UNKNOWN is highest - assume worst case when we don't know."""
        return [cls.PG, cls.PG13, cls.R, cls.X, cls.XXX, cls.BANNED, cls.UNKNOWN]

    def severity_index(self) -> int:
        """Get numeric severity for comparison."""
        order = self.severity_order()
        return order.index(self)

    def __lt__(self, other: "NSFWLevel") -> bool:
        return self.severity_index() < other.severity_index()

    def __le__(self, other: "NSFWLevel") -> bool:
        return self.severity_index() <= other.severity_index()

    def __gt__(self, other: "NSFWLevel") -> bool:
        return self.severity_index() > other.severity_index()

    def __ge__(self, other: "NSFWLevel") -> bool:
        return self.severity_index() >= other.severity_index()

    def to_bitmask(self) -> int:
        """Convert NSFWLevel to bitmask value."""
        bitmask_map = {
            NSFWLevel.PG: 1,
            NSFWLevel.PG13: 2,
            NSFWLevel.R: 4,
            NSFWLevel.X: 8,
            NSFWLevel.XXX: 16,
            NSFWLevel.BANNED: 32,
            NSFWLevel.UNKNOWN: 64,  # Unknown is highest level
        }
        return bitmask_map.get(self, 1)


def image_nsfw_to_bitmask(nsfwLevel: Any, nsfw_bool: Any = None) -> int:
    """
    Convert image NSFW fields to bitmask value.

    Image API uses different levels than models:
    - None = 1 (PG)
    - Soft = 4 (R)
    - Mature = 8 (X)
    - X = 16 (XXX)

    Args:
        nsfwLevel: String enum from image (None, Soft, Mature, X)
        nsfw_bool: Boolean nsfw field from image

    Returns:
        Bitmask value (1=PG, 4=Soft/R, 8=Mature/X, 16=X/XXX)
    """
    # Map image nsfwLevel strings to bitmask
    level_map = {
        "None": 1,     # PG
        "Soft": 4,     # R
        "Mature": 8,   # X
        "X": 16,       # XXX
    }

    level_value = 1  # Default PG

    if nsfwLevel and isinstance(nsfwLevel, str):
        level_value = level_map.get(nsfwLevel, 1)
    elif nsfwLevel and isinstance(nsfwLevel, int):
        # If it's already an int, use it directly
        level_value = nsfwLevel

    # If nsfw boolean is True, ensure at least Soft/R level
    if nsfw_bool is True:
        level_value = max(level_value, 4)

    return level_value


class ModelType(Enum):
    """Types of models supported."""
    CHECKPOINT = "Checkpoint"
    LORA = "LORA"
    LOCON = "LoCon"
    TEXTUAL_INVERSION = "TextualInversion"
    HYPERNETWORK = "Hypernetwork"
    AESTHETIC_GRADIENT = "AestheticGradient"
    CONTROLNET = "Controlnet"
    UPSCALER = "Upscaler"
    MOTION_MODULE = "MotionModule"
    VAE = "VAE"
    POSES = "Poses"
    WILDCARDS = "Wildcards"
    OTHER = "Other"
    UNKNOWN = "Unknown"

    @classmethod
    def from_string(cls, value: str) -> "ModelType":
        """Convert string to ModelType."""
        if not value:
            return cls.UNKNOWN

        normalized = value.lower().replace(" ", "").replace("_", "")

        mapping = {
            "checkpoint": cls.CHECKPOINT,
            "lora": cls.LORA,
            "locon": cls.LOCON,
            "textualinversion": cls.TEXTUAL_INVERSION,
            "embedding": cls.TEXTUAL_INVERSION,
            "hypernetwork": cls.HYPERNETWORK,
            "aestheticgradient": cls.AESTHETIC_GRADIENT,
            "controlnet": cls.CONTROLNET,
            "upscaler": cls.UPSCALER,
            "motionmodule": cls.MOTION_MODULE,
            "vae": cls.VAE,
            "poses": cls.POSES,
            "wildcards": cls.WILDCARDS,
            "other": cls.OTHER,
        }

        return mapping.get(normalized, cls.UNKNOWN)


@dataclass
class ImageMeta:
    """Generation parameters for an image."""
    prompt: str = ""
    negative_prompt: str = ""
    steps: Optional[int] = None
    sampler: Optional[str] = None
    cfg_scale: Optional[float] = None
    seed: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    model: Optional[str] = None
    model_hash: Optional[str] = None
    denoising_strength: Optional[float] = None
    clip_skip: Optional[int] = None
    # Hires fix
    hires_upscale: Optional[float] = None
    hires_upscaler: Optional[str] = None
    hires_steps: Optional[int] = None
    # Extra params stored as dict
    extra: Dict[str, Any] = field(default_factory=dict)
    # Resources used (models, loras, VAEs, etc.)
    resources: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_civitai(cls, meta: Optional[Dict]) -> "ImageMeta":
        """Create from Civitai image metadata."""
        if not meta:
            return cls()

        # Extract resources (models, loras, VAEs used)
        resources = meta.get("resources", []) or []
        if meta.get("civitaiResources"):
            resources = resources + meta.get("civitaiResources", [])

        return cls(
            prompt=meta.get("prompt", ""),
            negative_prompt=meta.get("negativePrompt", ""),
            steps=meta.get("steps"),
            sampler=meta.get("sampler"),
            cfg_scale=meta.get("cfgScale"),
            seed=meta.get("seed"),
            width=meta.get("Size", "").split("x")[0] if "Size" in meta else None,
            height=meta.get("Size", "").split("x")[1] if "Size" in meta and "x" in meta.get("Size", "") else None,
            model=meta.get("Model"),
            model_hash=meta.get("Model hash"),
            denoising_strength=meta.get("Denoising strength"),
            clip_skip=meta.get("Clip skip"),
            hires_upscale=meta.get("Hires upscale"),
            hires_upscaler=meta.get("Hires upscaler"),
            hires_steps=meta.get("Hires steps"),
            extra={k: v for k, v in meta.items() if k not in [
                "prompt", "negativePrompt", "steps", "sampler", "cfgScale",
                "seed", "Size", "Model", "Model hash", "Denoising strength",
                "Clip skip", "Hires upscale", "Hires upscaler", "Hires steps"
            ]},
            resources=resources,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {}
        if self.prompt:
            result["prompt"] = self.prompt
        if self.negative_prompt:
            result["negativePrompt"] = self.negative_prompt
        if self.steps is not None:
            result["steps"] = self.steps
        if self.sampler:
            result["sampler"] = self.sampler
        if self.cfg_scale is not None:
            result["cfgScale"] = self.cfg_scale
        if self.seed is not None:
            result["seed"] = self.seed
        if self.width and self.height:
            result["Size"] = f"{self.width}x{self.height}"
        if self.model:
            result["Model"] = self.model
        if self.model_hash:
            result["Model hash"] = self.model_hash
        if self.denoising_strength is not None:
            result["Denoising strength"] = self.denoising_strength
        if self.clip_skip is not None:
            result["Clip skip"] = self.clip_skip
        if self.hires_upscale is not None:
            result["Hires upscale"] = self.hires_upscale
        if self.hires_upscaler:
            result["Hires upscaler"] = self.hires_upscaler
        if self.hires_steps is not None:
            result["Hires steps"] = self.hires_steps
        if self.resources:
            result["resources"] = self.resources
        if self.extra:
            result.update(self.extra)
        return result


@dataclass
class ModelImage:
    """Image from Civitai with metadata."""
    id: int
    url: str
    nsfw: NSFWLevel = NSFWLevel.UNKNOWN
    width: Optional[int] = None
    height: Optional[int] = None
    hash: Optional[str] = None
    meta: Optional[ImageMeta] = None

    @classmethod
    def from_civitai(cls, data: Dict) -> "ModelImage":
        """Create from Civitai API response."""
        # Prefer browsingLevel (integer) over nsfwLevel (often string "None")
        nsfw_value = data.get("browsingLevel", data.get("nsfwLevel", data.get("nsfw", "")))
        return cls(
            id=data.get("id", 0),
            url=data.get("url", ""),
            nsfw=NSFWLevel.from_string(nsfw_value),
            width=data.get("width"),
            height=data.get("height"),
            hash=data.get("hash"),
            meta=ImageMeta.from_civitai(data.get("meta"))
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "id": self.id,
            "url": self.url,
            "nsfw": self.nsfw.value,
            "width": self.width,
            "height": self.height,
            "hash": self.hash,
            "meta": self.meta.to_dict() if self.meta else None
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ModelImage":
        """Create from dictionary."""
        # Prefer browsingLevel (integer) over nsfw (may be string "None")
        nsfw_value = data.get("browsingLevel", data.get("nsfw", ""))
        return cls(
            id=data.get("id", 0),
            url=data.get("url", ""),
            nsfw=NSFWLevel.from_string(nsfw_value),
            width=data.get("width"),
            height=data.get("height"),
            hash=data.get("hash"),
            meta=ImageMeta.from_civitai(data.get("meta")) if data.get("meta") else None
        )


@dataclass
class ModelVersion:
    """A specific version of a model."""
    id: int
    name: str
    description: str = ""
    base_model: str = ""
    trained_words: List[str] = field(default_factory=list)
    download_url: Optional[str] = None
    nsfw: NSFWLevel = NSFWLevel.UNKNOWN
    published_at: Optional[datetime] = None
    images: List[ModelImage] = field(default_factory=list)
    # File info from Civitai
    file_size_kb: Optional[float] = None
    file_hash: Optional[str] = None  # SHA256

    @property
    def max_image_nsfw(self) -> NSFWLevel:
        """Get the highest NSFW level from all images."""
        if not self.images:
            return NSFWLevel.UNKNOWN
        return max(self.images, key=lambda i: i.nsfw.severity_index()).nsfw

    @classmethod
    def from_civitai(cls, data: Dict) -> "ModelVersion":
        """Create from Civitai API response."""
        # Parse published date
        published_at = None
        if data.get("publishedAt"):
            try:
                published_at = datetime.fromisoformat(
                    data["publishedAt"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        # Get primary file info
        file_size = None
        file_hash = None
        files = data.get("files", [])
        if files:
            primary_file = files[0]
            file_size = primary_file.get("sizeKB")
            hashes = primary_file.get("hashes", {})
            file_hash = hashes.get("SHA256")

        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            description=data.get("description", ""),
            base_model=data.get("baseModel", ""),
            trained_words=data.get("trainedWords", []),
            download_url=data.get("downloadUrl"),
            nsfw=NSFWLevel.from_string(data.get("nsfw", data.get("nsfwLevel", ""))),
            published_at=published_at,
            images=[ModelImage.from_civitai(img) for img in data.get("images", [])],
            file_size_kb=file_size,
            file_hash=file_hash,
        )


@dataclass
class CivitaiModelInfo:
    """Civitai model information (can have multiple versions)."""
    id: int
    name: str
    description: str = ""
    type: ModelType = ModelType.UNKNOWN
    nsfw: NSFWLevel = NSFWLevel.UNKNOWN
    tags: List[str] = field(default_factory=list)
    creator: Optional[str] = None
    # Stats
    download_count: int = 0
    favorite_count: int = 0
    comment_count: int = 0
    rating: float = 0.0
    rating_count: int = 0
    # Versions
    versions: List[ModelVersion] = field(default_factory=list)

    @classmethod
    def from_civitai(cls, data: Dict) -> "CivitaiModelInfo":
        """Create from Civitai API response."""
        stats = data.get("stats", {})

        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            description=data.get("description", ""),
            type=ModelType.from_string(data.get("type", "")),
            nsfw=NSFWLevel.from_string(data.get("nsfw", data.get("nsfwLevel", ""))),
            tags=data.get("tags", []),
            creator=data.get("creator", {}).get("username") if data.get("creator") else None,
            download_count=stats.get("downloadCount", 0),
            favorite_count=stats.get("favoriteCount", 0),
            comment_count=stats.get("commentCount", 0),
            rating=stats.get("rating", 0.0),
            rating_count=stats.get("ratingCount", 0),
            versions=[ModelVersion.from_civitai(v) for v in data.get("modelVersions", [])],
        )


@dataclass
class LocalModel:
    """
    A local model file with associated metadata.

    Combines local file information with Civitai metadata.
    """
    # Local file info
    file_path: str
    file_name: str
    file_size: int  # bytes
    file_modified: datetime
    file_created: datetime
    file_extension: str

    # Civitai metadata (if available)
    civitai_model: Optional[CivitaiModelInfo] = None
    civitai_version: Optional[ModelVersion] = None

    # Cached data
    _preview_path: Optional[str] = None
    _images_path: Optional[str] = None

    @property
    def has_civitai_data(self) -> bool:
        """Check if Civitai metadata is available."""
        return self.civitai_model is not None

    @property
    def display_name(self) -> str:
        """Get display name (Civitai name or filename)."""
        if self.civitai_model:
            return self.civitai_model.name
        return os.path.splitext(self.file_name)[0]

    @property
    def model_type(self) -> ModelType:
        """Get model type from Civitai data or infer from path."""
        if self.civitai_model:
            return self.civitai_model.type

        # Infer from directory structure
        path_lower = self.file_path.lower()
        if "lora" in path_lower:
            return ModelType.LORA
        elif "embedding" in path_lower or "textual" in path_lower:
            return ModelType.TEXTUAL_INVERSION
        elif "vae" in path_lower:
            return ModelType.VAE
        elif "controlnet" in path_lower:
            return ModelType.CONTROLNET
        elif "upscal" in path_lower:
            return ModelType.UPSCALER
        elif "checkpoint" in path_lower or "stable-diffusion" in path_lower:
            return ModelType.CHECKPOINT

        return ModelType.UNKNOWN

    @property
    def base_model(self) -> str:
        """Get base model from Civitai version data."""
        if self.civitai_version:
            return self.civitai_version.base_model
        return ""

    @property
    def nsfw_level(self) -> NSFWLevel:
        """
        Get the effective NSFW level.

        Note: Version's nsfwLevel is a BITMASK of what content CAN exist,
        not the actual content level. We should NOT use it directly.

        Instead, we use:
        1. Model's nsfw boolean (if true, at least R)
        2. Maximum NSFW level from actual images

        Returns UNKNOWN only if no Civitai data exists.
        """
        levels = []

        if self.civitai_model:
            # Model nsfw is typically a boolean, handled by from_string
            levels.append(self.civitai_model.nsfw)

        # Note: We intentionally skip civitai_version.nsfw because
        # version's nsfwLevel is a capability bitmask, not actual content level

        if self.civitai_version and self.civitai_version.images:
            # Use the max NSFW level from actual images
            levels.append(self.civitai_version.max_image_nsfw)

        # If no Civitai data, return UNKNOWN
        if not levels:
            return NSFWLevel.UNKNOWN

        # Filter out UNKNOWN levels when we have real data
        real_levels = [l for l in levels if l != NSFWLevel.UNKNOWN]
        if real_levels:
            return max(real_levels, key=lambda l: l.severity_index())

        return NSFWLevel.UNKNOWN

    @property
    def preview_path(self) -> Optional[str]:
        """Get path to preview image if exists."""
        if self._preview_path is not None:
            return self._preview_path

        base = os.path.splitext(self.file_path)[0]
        for ext in [".preview.png", ".preview.jpg", ".preview.jpeg", ".png", ".jpg"]:
            path = base + ext
            if os.path.exists(path):
                self._preview_path = path
                return path

        self._preview_path = ""
        return None

    @property
    def preview_url(self) -> Optional[str]:
        """Get thumbnail URL from Civitai if no local preview."""
        if self.preview_path:
            return None  # Use local

        if self.civitai_version and self.civitai_version.images:
            return self.civitai_version.images[0].url

        return None

    @property
    def trained_words(self) -> List[str]:
        """Get trigger words from Civitai version."""
        if self.civitai_version:
            return self.civitai_version.trained_words
        return []

    @property
    def tags(self) -> List[str]:
        """Get tags from Civitai model."""
        if self.civitai_model:
            return self.civitai_model.tags
        return []

    @property
    def rating(self) -> float:
        """Get rating from Civitai model."""
        if self.civitai_model:
            return self.civitai_model.rating
        return 0.0

    @property
    def download_count(self) -> int:
        """Get download count from Civitai model."""
        if self.civitai_model:
            return self.civitai_model.download_count
        return 0

    @property
    def civitai_model_id(self) -> Optional[int]:
        """Get Civitai model ID for duplicate detection."""
        if self.civitai_model:
            return self.civitai_model.id
        return None

    @property
    def civitai_version_id(self) -> Optional[int]:
        """Get Civitai version ID."""
        if self.civitai_version:
            return self.civitai_version.id
        return None

    @property
    def published_at(self) -> Optional[datetime]:
        """Get publish date from Civitai version."""
        if self.civitai_version:
            return self.civitai_version.published_at
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "file_path": self.file_path,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "file_size_mb": round(self.file_size / (1024 * 1024), 2),
            "file_modified": self.file_modified.isoformat() if self.file_modified else None,
            "file_created": self.file_created.isoformat() if self.file_created else None,
            "file_extension": self.file_extension,
            "display_name": self.display_name,
            "model_type": self.model_type.value,
            "base_model": self.base_model,
            "nsfw_level": self.nsfw_level.value,
            "has_civitai_data": self.has_civitai_data,
            "preview_path": self.preview_path,
            "preview_url": self.preview_url,
            "trained_words": self.trained_words,
            "tags": self.tags,
            "rating": self.rating,
            "download_count": self.download_count,
            "civitai_model_id": self.civitai_model_id,
            "civitai_version_id": self.civitai_version_id,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "creator": self.civitai_model.creator if self.civitai_model else None,
        }
