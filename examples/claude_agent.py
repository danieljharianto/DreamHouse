"""Claude-powered agent for the DreamHouse benchmark.

Calls Claude with vision to turn a task prompt + 5 reference images into
Blender Python (bpy) code that builds a timber-frame structure.

Requires:
  pip install anthropic
  export ANTHROPIC_API_KEY=...
  export CLAUDE_MODEL=claude-opus-5   # optional, this is the default

Matches the agent signature dreamhouse / scripts/dev_run.py expects:
    generate(prompt: str, images: list[str], feedback: list[dict]) -> str

Usage:
  python scripts/dev_run.py --task DEV_01_0001 \\
      --agent examples.claude_agent:generate \\
      --output-dir ./runs/claude_agent_DEV_01_0001
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")
MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", "8000"))

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _image_block(path: str) -> dict:
    p = Path(path)
    media_type = _MEDIA_TYPES.get(p.suffix.lower(), "image/png")
    data = base64.standard_b64encode(p.read_bytes()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


SYSTEM_PROMPT = """You generate Blender Python (bpy) code for the DreamHouse \
timber-frame structure benchmark.

Rules:
- Output ONLY Blender Python code in a single ```python code block. No prose \
outside the code block.
- Get or create a collection named exactly "COLLECTION_NAME" and link every \
member object to it (e.g. bpy.ops.mesh.primitive_cube_add + object.scale + \
transform_apply, to build each member as an axis-aligned box).
- Give every member a unique name using one keyword from its category so the \
validator can classify it (case-insensitive):
    foundation: Sill, Post, BeamPost, Foundation
    floor:      CenterBeam, Rim, Joist
    walls:      Plate, Stud, King, Trimmer, Header, Cripple
    roof:       Ridge, Rafter, Raf, Collar, Lookout, Purlin, Valley, Hip
- A complete structure needs at least one member from every one of the 4 \
categories above (foundation, floor, walls, roof), stacked in a physically \
sensible order (foundation at z=0, then floor, then walls, then roof), with \
no large gaps between adjacent members.
- Use real-world lumber sizes in meters (e.g. a 2x6 sill is about \
0.14m x 0.038m in cross-section, a 2x4 stud is about 0.09m x 0.038m).
- Look at the 5 reference images (front, back, left, right, top) to infer \
footprint, story count, and roof shape; use the constraints in the prompt \
text as the source of truth for exact dimensions.
"""

_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _extract_code(text: str) -> str:
    match = _CODE_FENCE.search(text)
    return match.group(1).strip() if match else text.strip()


def _format_feedback(feedback: list[dict]) -> str:
    if not feedback:
        return ""
    last = feedback[-1]
    status = last.get("status")

    if status == "blender_error":
        return (
            "\n\nYour previous attempt raised a Blender error:\n"
            f"{(last.get('error') or '')[:800]}\nFix it."
        )
    if status == "export_empty":
        return (
            "\n\nYour previous attempt produced no exported members. Make "
            "sure every object is linked to the COLLECTION_NAME collection."
        )

    tests = (last.get("results") or {}).get("tests") or {}
    failed = [name for name, ok in tests.items() if not ok]
    if failed:
        return (
            "\n\nYour previous attempt failed these structural tests: "
            f"{', '.join(failed)}. Revise the structure to address them."
        )
    return ""


def generate(prompt: str, images: list[str], feedback: list[dict]) -> str:
    content = [_image_block(p) for p in images]
    content.append({"type": "text", "text": prompt + _format_feedback(feedback)})

    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": content}],
    )

    text = "".join(block.text for block in response.content if block.type == "text")
    return _extract_code(text)
