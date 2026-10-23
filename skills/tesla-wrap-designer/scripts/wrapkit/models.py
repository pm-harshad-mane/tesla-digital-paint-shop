"""Model registry loaded from references/models.json."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
MODELS_JSON = SKILL_ROOT / "references" / "models.json"


@lru_cache(maxsize=1)
def load_registry() -> dict:
    with open(MODELS_JSON, encoding="utf-8") as f:
        return json.load(f)


def list_models() -> list[dict]:
    return list(load_registry()["models"])


def model_ids() -> list[str]:
    return [m["id"] for m in list_models()]


def get_model(model_id: str) -> dict:
    for m in list_models():
        if m["id"] == model_id:
            return m
    raise KeyError(f"Unknown model '{model_id}'. Valid ids: {', '.join(model_ids())}")


def canvas_size(model_id: str) -> tuple[int, int]:
    w, h = get_model(model_id)["canvas"]
    return int(w), int(h)


def limits() -> dict:
    return dict(load_registry()["limits"])


def source_ref() -> str:
    return load_registry()["source_ref"]


def raw_url(model_id: str, filename: str) -> str:
    get_model(model_id)
    reg = load_registry()
    return reg["raw_base"].format(ref=reg["source_ref"], id=model_id, file=filename)
