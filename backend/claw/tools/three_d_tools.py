"""Milestone 8 (sections 3-4): 3D renders through Blender when it is installed (free; optional; never bundled)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.integrations import blender as bl
from claw.integrations import images as im
from claw.integrations import motion as mo
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import existing_folder, safe_file_name, unique_path

QUALITY = {"draft": (960, 540, 8), "good": (1280, 720, 24)}
FPS = 24


class RenderArgs(ToolArgs):
    kind: Literal["turntable", "text"] = Field(description="turntable: a product spinning (MP4); text: 3D lettering (PNG)")
    label: str = Field(default="", max_length=40)
    colour: str = Field(default="orange", max_length=20)
    model_file: str | None = Field(default=None, max_length=500, description="Optional .obj/.stl/.glb to spin")
    seconds: float = Field(default=4, ge=1, le=12)
    quality: Literal["draft", "good"] = "draft"
    file_name: str = Field(default="", max_length=100)
    folder: str | None = Field(default=None, max_length=500)

    @field_validator("colour", mode="before")
    @classmethod
    def _c(cls, v):
        from claw.tools.image_tools import _COLOURS  # noqa: PLC0415
        t = str(v or "").strip().lower()
        return t if t.startswith("#") else _COLOURS.get(t, "#d9822b")


def check_render(args: RenderArgs, ctx: ToolContext) -> None:
    if bl.find_blender() is None:
        raise ToolError("3D renders need Blender, which is not installed. It is free from blender.org; "
                        "after installing it, ask again. Nothing was made.")
    existing_folder(ctx, args.folder, write=True)


async def make_3d_render(args: RenderArgs, ctx: ToolContext) -> ToolResult:
    check_render(args, ctx)
    folder = existing_folder(ctx, args.folder, write=True)
    model = None
    if args.model_file:
        model = ctx.policy.check_path(args.model_file)
        if not model.is_file() or model.suffix.lower() not in (".obj", ".stl", ".glb", ".gltf"):
            raise ToolError("The model must be an existing .obj, .stl, .glb or .gltf file.")
        ctx.memory.note_file(model)
    w, h, samples = QUALITY[args.quality]
    frames = max(2, int(args.seconds * FPS)) if args.kind == "turntable" else 1
    rgb = [c / 255 for c in im.hex_rgb(args.colour)]
    spec = {"kind": args.kind, "label": args.label, "colour": rgb, "accent": [0.08, 0.08, 0.1], "bg": [0.88, 0.9, 0.93],
            "metal": 0.3, "width": w, "height": h, "samples": samples, "frames": frames, "model": str(model) if model else None}
    try:
        rendered = await asyncio.to_thread(bl.run, spec, 120 + frames * 20)
    except RuntimeError as exc:
        raise ToolError(f"Blender could not make it: {exc}") from exc
    ext = ".mp4" if args.kind == "turntable" else ".png"
    out = unique_path(folder / safe_file_name(args.file_name or f"{args.label or 'render'} {args.kind}", ext))
    ctx.policy.check_path(out, write=True)
    if args.kind == "turntable":
        await asyncio.to_thread(bl.frames_to_mp4, rendered, out, FPS)
        info = await asyncio.to_thread(mo.inspect_video, out, None)
        info.pop("frame_image", None)
        ok = info["frames"] == frames and (info["width"], info["height"]) == (w, h)
        what = f"{info['width']}×{info['height']}, {info['seconds']} s, {info['frames']} frames"
    else:
        import shutil  # noqa: PLC0415
        shutil.copyfile(rendered[0], out)
        info = await asyncio.to_thread(im.inspect, out)
        ok = (info["width"], info["height"]) == (w, h)
        what = f"{info['width']}×{info['height']} PNG"
    ctx.memory.outputs.append({"path": str(out), "kind": "render", "verified": ok, "note": ""})
    return ToolResult(True, f"Rendered {out.name} with Blender ({what}){' from ' + model.name if model else ''}; reopened and checked.",
                      {"path": str(out), **{k: v for k, v in info.items() if k != "frame_image"}}, verified=ok)


def register_three_d_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec("make_3d_render", "Render a spinning product video or 3D text with Blender (if installed).",
                          Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, RenderArgs, make_3d_render, precheck=check_render))
