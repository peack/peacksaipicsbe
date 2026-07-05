from __future__ import annotations

import json
from typing import Any

from .base import BaseParser, ParsedMeta, extract_loras, parse_size


def _resolve_text(prompt_json: dict, node_id: str, field: str, depth: int = 0) -> str:
    """Recursively resolve text from a node, following input links."""
    if depth > 10:
        return ""
    node = prompt_json.get(node_id)
    if not isinstance(node, dict):
        return ""

    val = node.get("inputs", {}).get(field)
    if val is None:
        return ""

    if isinstance(val, str):
        return val

    if isinstance(val, list) and len(val) == 2:
        linked_id = str(val[0])
        linked_field = val[1]
        if isinstance(linked_field, int):
            linked_node = prompt_json.get(linked_id, {})
            widget_vals = linked_node.get("inputs", {}).values()
            for w in widget_vals:
                if isinstance(w, str | int | float):
                    return str(w)
        return _resolve_text(prompt_json, linked_id, str(linked_field), depth + 1)

    return str(val) if val else ""


def _find_sampler(prompt_json: dict) -> dict | None:
    for nid, node in prompt_json.items():
        ct = node.get("class_type", "")
        if ct in ("KSampler", "KSamplerAdvanced"):
            return {"id": nid, **node.get("inputs", {})}
    return None


def _find_node_by_type(prompt_json: dict, class_type: str) -> list[tuple[str, dict]]:
    results = []
    for nid, node in prompt_json.items():
        if node.get("class_type") == class_type:
            results.append((nid, node))
    return results


class ComfyUI(BaseParser):
    name = "comfyui"

    @classmethod
    def sniff(cls, info: dict) -> bool:
        raw = info.get("prompt") or info.get("workflow") or ""
        if not raw:
            return False
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return False
            # ComfyUI graphs have string keys with nested dicts containing class_type
            for v in data.values():
                if isinstance(v, dict) and "class_type" in v:
                    return True
            return False
        except (json.JSONDecodeError, ValueError):
            return False

    @classmethod
    def parse(cls, info: dict) -> ParsedMeta:
        raw = info.get("prompt") or info.get("workflow") or "{}"
        prompt_json = json.loads(raw)
        meta = ParsedMeta()
        meta.raw_json = raw

        sampler = _find_sampler(prompt_json)
        if sampler:
            seed = sampler.get("seed", "")
            meta.seed = str(seed) if seed is not None else ""
            steps = sampler.get("steps")
            meta.steps = int(steps) if steps is not None else None
            cfg = sampler.get("cfg")
            meta.cfg_scale = float(cfg) if cfg is not None else None
            meta.sampler = sampler.get("sampler_name", "") or ""

        # Resolve positive/negative prompt from sampler inputs
        if sampler and "positive" in sampler:
            pos_ref = sampler["positive"]
            if isinstance(pos_ref, list) and len(pos_ref) == 2:
                meta.prompt = _resolve_text(prompt_json, str(pos_ref[0]), str(pos_ref[1]))
            elif isinstance(pos_ref, str):
                meta.prompt = pos_ref

        if sampler and "negative" in sampler:
            neg_ref = sampler["negative"]
            if isinstance(neg_ref, list) and len(neg_ref) == 2:
                meta.negative_prompt = _resolve_text(prompt_json, str(neg_ref[0]), str(neg_ref[1]))
            elif isinstance(neg_ref, str):
                meta.negative_prompt = neg_ref

        # If no sampler found, fall back to finding CLIPTextEncode nodes
        if meta.prompt == "":
            encode_nodes = _find_node_by_type(prompt_json, "CLIPTextEncode")
            for nid, node in encode_nodes:
                text = node.get("inputs", {}).get("text", "")
                if isinstance(text, str) and text.strip():
                    if not meta.prompt:
                        meta.prompt = text
                    elif not meta.negative_prompt:
                        meta.negative_prompt = text

        # Extract model from checkpoint loaders
        ckpts = _find_node_by_type(prompt_json, "CheckpointLoaderSimple")
        for nid, node in ckpts:
            model = node.get("inputs", {}).get("ckpt_name", "")
            if isinstance(model, str) and model:
                meta.model = model
                break

        # Extract size from EmptyLatentImage
        latents = _find_node_by_type(prompt_json, "EmptyLatentImage")
        for nid, node in latents:
            inputs = node.get("inputs", {})
            w = inputs.get("width") or inputs.get("Width")
            h = inputs.get("height") or inputs.get("Height")
            if w is not None and h is not None:
                meta.width = int(w) if not isinstance(w, int) else w
                meta.height = int(h) if not isinstance(h, int) else h
                break
        if not meta.width:
            size_str = sampler.get("size", "") if sampler else ""
            if isinstance(size_str, str):
                w, h = parse_size(size_str)
                meta.width, meta.height = w, h

        # Extract LoRAs
        lora_nodes = _find_node_by_type(prompt_json, "LoraLoader")
        if not lora_nodes:
            lora_nodes = _find_node_by_type(prompt_json, "LoraLoaderModelOnly")
        for nid, node in lora_nodes:
            name = node.get("inputs", {}).get("lora_name", "")
            if isinstance(name, str) and name:
                meta.loras.append(name)

        meta.prompt, extra_loras = extract_loras(meta.prompt)
        meta.loras.extend(extra_loras)

        return meta