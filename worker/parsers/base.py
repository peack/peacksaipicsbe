from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


@dataclass
class ParsedMeta:
    prompt: str = ""
    negative_prompt: str = ""
    model: str = ""
    sampler: str = ""
    steps: int | None = None
    cfg_scale: float | None = None
    seed: str = ""
    width: int | None = None
    height: int | None = None
    loras: list[str] = field(default_factory=list)
    raw_json: str = ""


class BaseParser:
    name: str = ""

    @classmethod
    def sniff(cls, info: dict) -> bool:
        raise NotImplementedError

    @classmethod
    def parse(cls, info: dict) -> ParsedMeta:
        raise NotImplementedError


LORA_PATTERN = re.compile(r"<lora:([^:>]+)(?::[^>]*)?>")


def extract_loras(text: str) -> tuple[str, list[str]]:
    loras = LORA_PATTERN.findall(text)
    cleaned = LORA_PATTERN.sub("", text)
    cleaned = re.sub(r",\s*,", ", ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip(", ").strip()
    return cleaned, loras


WEIGHT_PATTERN = re.compile(r"\(([^:()]+):[\d.]+\)")


def normalize_tag(token: str) -> str:
    token = WEIGHT_PATTERN.sub(r"\1", token)
    token = token.strip().lower()
    return token


def tokenize_prompt(text: str) -> list[str]:
    parts = [normalize_tag(t) for t in text.split(",")]
    seen = set()
    result = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            result.append(p)
    return result


def parse_size(s: str) -> tuple[int | None, int | None]:
    m = re.search(r"(\d+)\s*x\s*(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None