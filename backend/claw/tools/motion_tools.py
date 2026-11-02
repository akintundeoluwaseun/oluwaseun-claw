"""Motion graphics: make a short animated promo video (After Effects when installed, else Claw's built-in maker)."""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import Field, field_validator

from claw.agent.schemas import Capability
from claw.integrations import motion as mo
from claw.permissions.policy import RiskLevel
from claw.tools.base import ToolArgs, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from claw.tools.file_tools import resolve_folder
from claw.tools.image_tools import FlyerArgs, _ocr_words, _output, _title_seen


class MotionArgs(ToolArgs):
    title: str = Field(min_length=1, max_length=80, description="The headline, e.g. the product name")
    subtitle: str = Field(default="", max_length=120)
    points: list[str] = Field(default_factory=list, max_length=5, description="Up to 5 selling points")
    contact: str = Field(default="", max_length=120, description="Phone or website")
    seconds: float = Field(default=10, ge=4, le=30, description="Length of the video in seconds")
    size: Literal["landscape", "square", "story"] = "landscape"
    style: Literal["slide", "pop", "fade"] = "slide"
    background: str = FlyerArgs.model_fields["background"].default
    accent: str = FlyerArgs.model_fields["accent"].default
    file_name: str = Field(default="promo video", max_length=80)
    folder: str | None = Field(default=None, max_length=500)
    editor: Literal["auto", "aftereffects", "builtin"] = Field(
        default="auto", description="auto, aftereffects or builtin")

    @field_validator("points", mode="before")
    @classmethod
    def _one_list(cls, v):
        if isinstance(v, str):  # a small brain sends "a, b, c"
            return [p.strip() for p in v.replace("\n", ",").split(",") if p.strip()][:5]
        return v[:5] if isinstance(v, list) else v

    @field_validator("background", "accent", mode="before")
    @classmethod
    def _colours(cls, v, info):
        return FlyerArgs._named_colours(v, info)


def check_motion(args: MotionArgs, ctx: ToolContext) -> None:
    resolve_folder(ctx, args.folder)
    if args.editor == "aftereffects":
        ok, why = mo.after_effects_available()
        if not ok:
            raise ToolError(f"{why} Claw can make the video with its built-in maker instead, if you agree.")


async def make_motion_video(args: MotionArgs, ctx: ToolContext) -> ToolResult:
    check_motion(args, ctx)
    spec = mo.MotionSpec(args.title, args.subtitle, list(args.points), args.contact, mo.SIZES[args.size],
                         "#" + args.background.lstrip("#"), "#" + args.accent.lstrip("#"), float(args.seconds), args.style)
    out = _output(ctx, args.folder, args.file_name, ".mp4")
    project = None
    use_ae = args.editor == "aftereffects" or (args.editor == "auto" and mo.after_effects_available()[0])
    if use_ae:
        project = _output(ctx, args.folder, args.file_name, ".aep")
        try:
            await asyncio.to_thread(mo.run_after_effects, spec, out, project)
        except Exception as exc:  # noqa: BLE001 - After Effects errors are varied
            raise ToolError(f"After Effects could not make the video: {str(exc)[:240]}") from exc
        maker = "After Effects"
    else:
        await asyncio.to_thread(mo.render_builtin, spec, out)
        maker = "Claw's built-in video maker (After Effects was not used)"
    if not out.is_file():
        raise ToolError(f"{maker} finished, but the video file is not there.")
    info = await asyncio.to_thread(mo.inspect_video, out, spec.title_moment())
    grab = info.pop("frame_image")
    ran, text = await asyncio.to_thread(_ocr_words, grab) if grab is not None else (False, "")
    seen = _title_seen(args.title, text) if ran else None
    right_size = (info["width"], info["height"]) == spec.size
    right_length = abs(info["seconds"] - spec.seconds) <= 1.0
    ok = right_size and right_length and info["frames"] > 0 and (seen is None or seen >= 0.6)
    check = (f"OCR read {round(seen * 100)}% of the headline words in the video" if seen is not None
             else "headline not checked (OCR not available)")
    ctx.memory.outputs.append({"path": str(out), "kind": "video", "verified": ok, "note": "" if ok else check})
    if project is not None and project.is_file():
        ctx.memory.outputs.append({"path": str(project), "kind": "project", "verified": True, "note": "After Effects project"})
    extra = f" The After Effects project is {project.name}, so you can change it there." if project is not None and project.is_file() else ""
    return ToolResult(True, f"Made the video with {maker}: {out.name} ({info['width']}×{info['height']}, {info['seconds']} s, "
                            f"{info['frames']} frames); {check}.{extra}",
                      {"path": str(out), "maker": maker, **info, "headline_seen": seen}, verified=ok)


def register_motion_tools(reg: ToolRegistry) -> None:
    reg.register(ToolSpec("make_motion_video",
                          "Make a short animated promo video (MP4), with After Effects if installed.",
                          Capability.DOCUMENTS, RiskLevel.LOCAL_WRITE, MotionArgs, make_motion_video, precheck=check_motion))
