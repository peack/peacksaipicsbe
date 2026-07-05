from __future__ import annotations

import re

from .base import BaseParser, ParsedMeta, extract_loras, parse_size


# Matches the key=value segment at the end of A1111 parameters string
# Example: "Steps: 28, Sampler: DPM++ 2M Karras, CFG scale: 7, Seed: 12345, Size: 512x768, Model: model_v1.safetensors"
PARAM_LINE_RE = re.compile(
    r"Steps:\s*(\d+)\s*,\s*"
    r"Sampler:\s*([^,]+?)\s*,\s*"
    r"(?:CFG scale:\s*([\d.]+)\s*,\s*)?"
    r"Seed:\s*(\d+)\s*,\s*"
    r"Size:\s*(\d+x\d+)\s*,?\s*"
    r"(?:Model:\s*(.+?))?\s*$",
    re.IGNORECASE,
)


class A1111(BaseParser):
    name = "a1111"

    @classmethod
    def sniff(cls, info: dict) -> bool:
        val = info.get("parameters", "")
        return bool(val) and not val.strip().startswith("{")

    @classmethod
    def parse(cls, info: dict) -> ParsedMeta:
        raw = info.get("parameters", "")
        meta = ParsedMeta()
        meta.raw_json = raw

        # Split into prompt and params
        # Format: prompt\nNegative prompt: neg\nSteps: 28, Sampler: ..., ...
        parts = raw.split("Negative prompt:", 1)
        if len(parts) == 2:
            meta.prompt = parts[0].strip()
            rest = parts[1]
            # Rest has: " neg_text\nSteps: 28, ..."
            neg_div = rest.split("\n", 1)
            if len(neg_div) == 2:
                meta.negative_prompt = neg_div[0].strip()
                param_str = neg_div[1].strip()
            else:
                param_str = rest.strip()
        else:
            param_str = raw.strip()
            # Try splitting by newline: first line is prompt, rest is params
            lines = raw.split("\n", 1)
            if len(lines) == 2:
                meta.prompt = lines[0].strip()
                param_str = lines[1].strip()

        m = PARAM_LINE_RE.search(param_str)
        if m:
            meta.steps = int(m.group(1))
            meta.sampler = m.group(2).strip()
            if m.group(3):
                meta.cfg_scale = float(m.group(3))
            meta.seed = m.group(4)
            w, h = parse_size(m.group(5))
            meta.width = w
            meta.height = h
            if m.group(6):
                meta.model = m.group(6).strip()

        # Extract Loras from prompt
        meta.prompt, meta.loras = extract_loras(meta.prompt)

        return meta