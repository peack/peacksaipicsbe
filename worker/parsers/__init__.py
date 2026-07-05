from .a1111 import A1111
from .comfyui import ComfyUI
from .novelai import NovelAI
from .fooocus import Fooocus

PARSERS = [ComfyUI, A1111, NovelAI, Fooocus]


def sniff_source(info: dict) -> str | None:
    for p in PARSERS:
        try:
            if p.sniff(info):
                return p.name
        except Exception:
            continue
    return None


def parse(info: dict) -> tuple[str | None, object]:
    for p in PARSERS:
        try:
            if p.sniff(info):
                return p.name, p.parse(info)
        except Exception:
            continue
    return None, None