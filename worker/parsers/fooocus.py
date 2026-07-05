from __future__ import annotations

import json

from .base import BaseParser, ParsedMeta, extract_loras, parse_size


class Fooocus(BaseParser):
    name = "fooocus"

    @classmethod
    def sniff(cls, info: dict) -> bool:
        raw = info.get("parameters", "")
        if not raw:
            return False
        try:
            data = json.loads(raw)
            return isinstance(data, dict) and bool(data.get("prompt"))
        except (json.JSONDecodeError, ValueError):
            return False

    @classmethod
    def parse(cls, info: dict) -> ParsedMeta:
        raw = info.get("parameters", "{}")
        data = json.loads(raw)
        meta = ParsedMeta()
        meta.raw_json = raw

        meta.prompt = data.get("prompt", "")
        meta.negative_prompt = data.get("negative_prompt", "") or data.get("negativePrompt", "")
        meta.seed = str(data.get("seed", ""))
        steps = data.get("steps") or data.get("performance_seed")
        meta.steps = int(steps) if steps is not None else None
        meta.sampler = data.get("sampler_name", "") or ""
        scale = data.get("guidance_scale") or data.get("cfg")
        meta.cfg_scale = float(scale) if scale is not None else None

        w = data.get("width")
        h = data.get("height")
        if w is not None:
            meta.width = int(w)
        if h is not None:
            meta.height = int(h)

        meta.model = data.get("model", "") or data.get("base_model", "") or ""

        meta.prompt, meta.loras = extract_loras(meta.prompt)

        return meta