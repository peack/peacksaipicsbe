from __future__ import annotations

import json

from .base import BaseParser, ParsedMeta


class NovelAI(BaseParser):
    name = "novelai"

    @classmethod
    def sniff(cls, info: dict) -> bool:
        raw = info.get("Comment", "")
        if not raw:
            return False
        try:
            data = json.loads(raw)
            return isinstance(data, dict) and bool(data.get("prompt"))
        except (json.JSONDecodeError, ValueError):
            return False

    @classmethod
    def parse(cls, info: dict) -> ParsedMeta:
        raw = info.get("Comment", "{}")
        data = json.loads(raw)
        meta = ParsedMeta()
        meta.raw_json = raw

        meta.prompt = data.get("prompt", "")
        meta.seed = str(data.get("seed", ""))
        steps = data.get("steps")
        meta.steps = int(steps) if steps is not None else None
        meta.sampler = data.get("sampler", "") or ""
        scale = data.get("scale")
        meta.cfg_scale = float(scale) if scale is not None else None

        meta.negative_prompt = data.get("uc", "") or data.get("negative_prompt", "")

        w = data.get("width")
        h = data.get("height")
        if w is not None:
            meta.width = int(w)
        if h is not None:
            meta.height = int(h)

        meta.model = data.get("model", "") or ""

        return meta