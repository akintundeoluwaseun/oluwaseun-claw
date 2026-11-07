---
name: drive-blender
description: Make or change a 3D scene in Blender - a model, a product render, a turntable - by writing Blender Python and running it.
app: Blender
programs: blender
door: python
version: 1
author: S-CLAW
triggers: blender, 3d, render, model, scene, turntable, product shot
---
Blender has a scripting door, so do NOT drive it with the mouse. Clicking
through Blender's interface is slow and wrong most of the time; the same job
written as Python is exact and repeatable.

How to do it:

1. Write the whole job as one Blender Python script using the `bpy` module.
2. Run it with run_command, program "blender", arguments:
   ["--background", "--python", "<the script you saved>"]
   `--background` means no window opens, which is what you want for a render.
   Leave `--background` out only if the person asked to watch it happen.
3. Always end the script by saving something to a file - a .blend, a .png
   render, or an exported .obj/.stl - in a folder the person authorised.
4. Reopen what was written and check it: a render that is a single flat
   colour means the camera or the light is wrong, not that the job is done.

Things that go wrong and how to avoid them:

- A new Blender scene already holds a cube, a camera and a light. Delete what
  you do not want rather than assuming an empty scene.
- Set the output path and format in the script (`bpy.context.scene.render
  .filepath`), never rely on Blender's default, which is a temp folder.
- Give the render a small resolution and few samples while trying it out, and
  raise them once the picture is right. A full render can take many minutes:
  start it with start_program and check on it, rather than waiting.
- Blender exits with 0 even when the script raised an error, so read what it
  printed; a Python traceback in the output means the job failed.
