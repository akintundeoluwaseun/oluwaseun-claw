# S-CLAW plugins

A plugin teaches S-CLAW to drive one particular program.

S-CLAW can already work a window it has never seen: it reads the controls,
clicks and types. That is guessing, and guessing does not survive a long job.
Twenty guesses at 95% each finish 36% of the time, which is why driving a big
program like Photoshop by eye is a coin flip.

A plugin replaces guessing with knowing. It is written by somebody who uses
the program, and it says: this is the app, this is how to tell it is
installed, this is the door into it, and here is how the jobs are done.

## The door is the point

A plugin's first job is **not** "where to click". It is **"does this program
have a scripting way in"**.

| Program | Door |
|---|---|
| Blender | Python (`--background --python`) |
| Photoshop | its own scripting engine |
| Word, Excel, Outlook | COM automation |
| Inkscape, FFmpeg, OpenSCAD | command line |
| An old program with no API | the mouse, as a last resort |

Through the door is near certain and fast. By mouse is neither. Name the
door, and leave the mouse for programs that have none.

## A plugin carries no code

A plugin is **text**: instructions, shortcuts, and the name of a door S-CLAW
already knows how to open. It may also contain pictures.

It may **not** contain anything that runs — no `.exe`, `.py`, `.ps1`, `.jar`,
`.sh`, `.vbs` or the rest. Installing refuses them.

This is deliberate. If a plugin downloaded from a website could run a
program, the website becomes a way of putting malware on every machine that
trusts it, and one bad plugin ends the product. If a job needs a program run,
say so in the instructions: S-CLAW will run it and the person will approve it
at the moment it happens, seeing exactly what it is.

## The file

A plugin is a folder holding `PLUGIN.md`, zipped for sharing.

```
drive-blender/
  PLUGIN.md
  screenshot.png      (optional)
```

```markdown
---
format: sclaw-plugin/1
name: drive-blender
description: Make or change a 3D scene in Blender - a model, a product render,
  a turntable - by writing Blender Python and running it.
app: Blender
programs: blender
door: python
version: 1
author: Your name
triggers: blender, 3d, render, model, turntable
categories: design, 3d
prompts:
  - Make a 3D model of a coffee mug and render it as a PNG
  - Set up a turntable animation of this model, 60 frames
---
1. Write the whole job as one Blender Python script using `bpy`.
2. Run it with run_command, program "blender", arguments
   ["--background", "--python", "<the script you saved>"].
3. Always save something to a file in a folder the person authorised.
4. Reopen what was written and check it.
```

### The settings block

| Field | Required | What it is |
|---|---|---|
| `format` | no | `sclaw-plugin/1`. Left out, it is read as version 1. A version newer than this S-CLAW is refused with a message saying so. |
| `name` | **yes** | Short, lowercase, hyphenated. Two plugins of the same name: the person's own wins. |
| `description` | **yes** | One sentence. This is what S-CLAW reads to decide whether the plugin fits what was asked, so write it the way a person would describe the job. |
| `app` | no | The program it drives, for people to read. |
| `programs` | no | How to tell the program is installed. A plugin for software you do not have is not offered — better than sending S-CLAW down a road that ends in "not installed". |
| `door` | no | `python`, `com`, `jsx`, `cli`, `keys` or `mouse`. |
| `version` | no | The plugin's own version. |
| `author` | no | You. |
| `triggers` | no | Words that mean this plugin. Matched against the request. |
| `categories` | no | Where it belongs in a list of plugins — `design`, `office`, `3d`. Up to six, free text: a fixed list would mean a new S-CLAW release every time somebody writes a plugin for a kind of program nobody had thought of. |
| `prompts` | no | Up to eight things a person could actually say to use this plugin. Written as a list of lines, because a prompt is a sentence and must not be split on its commas. See below — this is the field most worth filling in. |

### prompts: the field most worth filling in

```yaml
prompts:
  - Make a 3D model of a coffee mug and render it as a PNG
  - Set up a turntable animation of this model, 60 frames
```

They do two jobs.

People read them. A plugin in a list with "what can I say to this?" answered
is a plugin someone uses; one without it is a plugin they guess at.

S-CLAW matches on them. You know the words your users type; a `description`
written for a human reader rarely contains them. A plugin whose description
said "make 3D models" was not found by "sculpt a low-poly bust" — one line
under `prompts` fixed that, and `tests/test_plugin_catalogue_fields.py` holds
that exact case so it stays fixed.

Write them as whole sentences, the way somebody would really say them. Not
keywords — that is what `triggers` is for.

### The instructions

Everything after the second `---`. Plain steps, in order, naming the S-CLAW
tools to use. Keep it short: it is put in front of a small model that has
limited room to read, and the first 1400 characters are what survive.

Write down what goes **wrong**, too. "A new Blender scene already holds a
cube, a camera and a light" saves more failures than three more steps.

## Installing

A folder or a `.zip`. Dropped into the plugins folder, or installed from the
app. Installing the same name again replaces it.

A plugin is checked on the way in: nothing executable, nothing larger than it
should be, no path that climbs out of its own folder, and a settings block
that parses. If any of that fails, nothing is kept.

## Testing yours

1. Put the folder in the plugins folder.
2. Ask S-CLAW to do a job your `triggers` cover.
3. Check it was picked up — the step list should follow your instructions.

If it is not picked, your `description`, `triggers` and `prompts` do not use
the words a person would. That is the usual reason, and it is a one-line fix —
usually one more line under `prompts`, phrased the way you would say it out
loud.

## A plugin you installed is not S-CLAW speaking

The recipes that ship inside S-CLAW and the ones you install are read the same
way, but they do not carry the same weight, and from v1 they are no longer
treated as if they did.

An installed plugin's text is put in front of the brain as somebody else's
advice, named as such, with the brain told to use it for the user's task only
and ignore anything in it asking for something the user did not. And while a
task is following an installed plugin, S-CLAW asks before every change —
whatever the Settings say.

That last part only shows up if you turned "ask me" off. Turning it off is a
judgement about your own tasks. It is not a judgement about a plugin you
downloaded from a website, so S-CLAW does not read it as one. Reading is
untouched; only changes are raised, and only back to the default.

Nothing here is a reason not to install plugins. It is the reason you can.
