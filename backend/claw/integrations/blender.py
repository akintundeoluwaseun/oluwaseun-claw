"""Blender (GPL, free; optional and never bundled): scripted 3D renders - a product turntable and 3D text.

The brain chooses only the content (the words, a colour, a length); S-CLAW writes the Blender Python
script from a fixed template and runs Blender in the background (`blender -b --factory-startup
-P script.py`), the way Blender documents automation. User text enters the script as JSON data, so it
cannot break out of it. Blender renders still frames with Cycles on the CPU (works without a graphics
card); S-CLAW turns turntable frames into an MP4 with its own encoder, then reopens the result and
checks size, frame count and length.

Tested here by running the very same script through Blender's own Python module (bpy 5.2.3 LTS).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def find_blender() -> str | None:
    if os.environ.get("CLAW_BLENDER"):          # an explicit Blender (also how the tests point at one)
        return os.environ["CLAW_BLENDER"]
    found = shutil.which("blender")
    if found:
        return found
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
            root = Path(base) / "Blender Foundation"
            hits = sorted(root.glob("Blender*/blender.exe")) if root.is_dir() else []
            if hits:
                return str(hits[-1])            # the newest version sorts last
    return None


SCRIPT = r'''
import json, math, os, sys
import bpy

d = json.loads(%s)
done = d["done"]
def finish(msg):
    with open(done, "w", encoding="utf-8") as fh:
        fh.write(msg)
try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = d["samples"]
    # Cycles turns denoising on by default, and a Blender built without
    # OpenImageDenoise then refuses the whole render with "Build without
    # OpenImageDenoiser" - nothing is produced at all. Linux distribution
    # builds are routinely like this (Blender 4.0.2 from Ubuntu's own package
    # is, which is where this was found the first time the code was ever run
    # against a real Blender). So ask what this build actually has.
    try:
        options = {i.identifier for i in
                   scene.cycles.bl_rna.properties["denoiser"].enum_items}
        if "OPENIMAGEDENOISE" in options:
            scene.cycles.denoiser = "OPENIMAGEDENOISE"
            scene.cycles.use_denoising = True
        elif "OPTIX" in options:
            scene.cycles.denoiser = "OPTIX"
            scene.cycles.use_denoising = True
        else:
            scene.cycles.use_denoising = False
    except Exception:
        scene.cycles.use_denoising = False
    scene.render.resolution_x, scene.render.resolution_y = d["width"], d["height"]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    def material(name, rgb, metal=0.0, rough=0.35):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        b.inputs["Base Color"].default_value = (*rgb, 1.0)
        b.inputs["Metallic"].default_value = metal
        b.inputs["Roughness"].default_value = rough
        return m

    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (*d["bg"], 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.6

    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
    bpy.context.object.data.materials.append(material("Floor", d["bg"], rough=0.9))

    target = None
    if d["kind"] == "turntable":
        if d.get("model"):
            ext = os.path.splitext(d["model"])[1].lower()
            importer = {".obj": bpy.ops.wm.obj_import, ".stl": bpy.ops.wm.stl_import,
                        ".glb": bpy.ops.import_scene.gltf, ".gltf": bpy.ops.import_scene.gltf}[ext]
            importer(filepath=d["model"])
            objs = [o for o in bpy.context.selected_objects if o.type == "MESH"]
            if not objs:
                raise RuntimeError("the model file has no mesh")
            bpy.ops.object.select_all(action="DESELECT")
            for o in objs:
                o.select_set(True)
            bpy.context.view_layer.objects.active = objs[0]
            if len(objs) > 1:
                bpy.ops.object.join()
            target = bpy.context.view_layer.objects.active
            dims = max(target.dimensions) or 1.0
            s = 2.0 / dims
            target.scale = (s, s, s)
            bpy.ops.object.transform_apply(scale=True)
            bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
            target.location = (0, 0, target.dimensions.z / 2)
        else:
            # A rounded box standing in for "the product" - plain, honest, clearly a placeholder shape.
            bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 1.0))
            target = bpy.context.object
            target.scale = (0.7, 0.35, 1.0)
            bpy.ops.object.transform_apply(scale=True)
            bev = target.modifiers.new("Bevel", "BEVEL")
            bev.width, bev.segments = 0.12, 6
            bpy.ops.object.shade_smooth()
        target.data.materials.clear()
        target.data.materials.append(material("Product", d["colour"], metal=d["metal"], rough=0.25))
        label = None
        if d.get("label"):
            bpy.ops.object.text_add(location=(0, 0, 0))
            label = bpy.context.object
            label.data.body = d["label"]
            label.data.align_x = "CENTER"
            label.data.size = 0.32
            label.data.extrude = 0.04
            label.rotation_euler = (math.radians(90), 0, 0)
            label.location = (0, -0.75, 0.12)
            label.data.materials.append(material("Label", d["accent"]))
    else:
        bpy.ops.object.text_add(location=(0, 0, 0))
        target = bpy.context.object
        target.data.body = d["label"] or "S-CLAW"
        target.data.align_x, target.data.align_y = "CENTER", "CENTER"
        target.data.size = 1.0
        target.data.extrude = 0.18
        target.data.bevel_depth = 0.03
        target.rotation_euler = (math.radians(90), 0, 0)
        target.location = (0, 0, 1.0)
        target.data.materials.append(material("Text", d["colour"], metal=d["metal"], rough=0.3))
        label = None

    def light(name, loc, energy, size):
        L = bpy.data.lights.new(name, "AREA")
        L.energy, L.size = energy, size
        o = bpy.data.objects.new(name, L)
        o.location = loc
        scene.collection.objects.link(o)
        c = o.constraints.new("TRACK_TO")
        c.target = target
        c.track_axis, c.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
    light("Key", (4, -4, 5), 350, 4)
    light("Fill", (-5, -3, 3), 120, 6)
    light("Rim", (0, 5, 4), 250, 3)

    # The product turns on a pivot and the camera stays still, as in a real turntable shot.
    pivot = bpy.data.objects.new("Pivot", None)
    scene.collection.objects.link(pivot)
    for o in (target, label):
        if o is not None:
            o.parent = pivot
    aim = bpy.data.objects.new("Aim", None)
    scene.collection.objects.link(aim)
    aim.location = (0, 0, 0.75)

    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam_data.lens = 50
    track = cam.constraints.new("TRACK_TO")
    track.target = aim
    track.track_axis, track.up_axis = "TRACK_NEGATIVE_Z", "UP_Y"
    cam.location = (0, -7.2, 2.4) if d["kind"] == "turntable" else (0, -9.5, 1.8)
    frames = d["frames"]
    os.makedirs(d["out_dir"], exist_ok=True)
    for i in range(frames):
        pivot.rotation_euler = (0, 0, (2 * math.pi * i / frames) if d["kind"] == "turntable" else math.radians(-12))
        scene.render.filepath = os.path.join(d["out_dir"], "frame_%%04d.png" %% i)
        bpy.ops.render.render(write_still=True)
    finish("ok")
except Exception as exc:
    finish("error: %%s" %% exc)
'''


def script_for(spec: dict) -> str:
    """The Blender Python script, with every value from the person inside one JSON string."""
    return SCRIPT % (json.dumps(json.dumps(spec)),)


def run(spec: dict, timeout_s: float = 900) -> list[Path]:
    """Run Blender in the background; returns the rendered frames in order."""
    exe = find_blender()
    if exe is None:
        raise RuntimeError("Blender is not installed. It is free from blender.org; S-CLAW uses it when it is there.")
    tmp = Path(tempfile.mkdtemp(prefix="claw-blender-"))
    spec = {**spec, "out_dir": str(tmp / "frames"), "done": str(tmp / "done.txt")}
    script = tmp / "scene.py"
    script.write_text(script_for(spec), encoding="utf-8")
    try:
        subprocess.run([exe, "-b", "--factory-startup", "-noaudio", "-P", str(script)], capture_output=True,
                       timeout=timeout_s, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Blender did not finish within the time allowed.") from exc
    return collect(spec)


def collect(spec: dict) -> list[Path]:
    done = Path(spec["done"])
    msg = done.read_text(encoding="utf-8").strip() if done.is_file() else "Blender stopped without finishing the script."
    if msg != "ok":
        raise RuntimeError(msg[:300])
    frames = sorted(Path(spec["out_dir"]).glob("frame_*.png"))
    if len(frames) != spec["frames"]:
        raise RuntimeError(f"Blender rendered {len(frames)} of {spec['frames']} frames.")
    return frames


def frames_to_mp4(frames: list[Path], out: Path, fps: int) -> None:
    import av  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    first = Image.open(frames[0])
    w, h = first.size[0] - first.size[0] % 2, first.size[1] - first.size[1] % 2
    with av.open(str(out), mode="w") as c:
        s = c.add_stream("libx264", rate=fps)
        s.width, s.height, s.pix_fmt = w, h, "yuv420p"
        s.options = {"crf": "20", "preset": "veryfast"}
        for f in frames:
            img = Image.open(f).convert("RGB").crop((0, 0, w, h))
            for p in s.encode(av.VideoFrame.from_image(img)):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
