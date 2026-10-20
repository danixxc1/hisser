"""Pinned recognition models and the portable app's selected profile."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class ModelSpec:
    id: str
    filename: str
    label: str
    size: int
    sha256: str


LARGE_V3_Q5 = ModelSpec(
    "large-v3-q5_0", "ggml-large-v3-q5_0.bin", "Large-v3",
    1_081_140_203, "d75795ecff3f83b5faa89d1900604ad8c780abd5739fae406de19f23ecd98ad1",
)
TURBO_Q5 = ModelSpec(
    "large-v3-turbo-q5_0", "ggml-large-v3-turbo-q5_0.bin", "Large-v3 Turbo",
    574_041_195, "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2",
)
MODELS = {model.id: model for model in (LARGE_V3_Q5, TURBO_Q5)}


@dataclass(frozen=True)
class Profile:
    model: ModelSpec = LARGE_V3_Q5
    cpu_threads: int = 6


def model_for_filename(filename: str) -> ModelSpec | None:
    return next((model for model in MODELS.values() if model.filename == filename), None)


def load_profile(data_root: Path) -> Profile:
    """Load catalog IDs, never executable paths or arbitrary model filenames.

    Missing profiles preserve the existing large-v3 installation. A damaged
    profile is rejected rather than silently switching models or hiding errors.
    """
    profile_path = Path(data_root) / "transcription-profile.json"
    if not profile_path.exists():
        return Profile()
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("profile must be an object")
        model_id = payload.get("model_id", LARGE_V3_Q5.id)
        threads = payload.get("cpu_threads", 6)
        if not isinstance(model_id, str) or model_id not in MODELS:
            raise ValueError("unknown model")
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 32:
            raise ValueError("invalid CPU thread count")
        return Profile(MODELS[model_id], threads)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise ValueError("The transcription profile is damaged. Restore Hisser's data/transcription-profile.json from the verified package.") from exc
