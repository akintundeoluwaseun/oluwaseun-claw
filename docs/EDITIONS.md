# Claw Online and Claw Local

One application. One codebase, one interface, one set of tool schemas, one set
of safety rules, one task-execution path. The two editions differ only in what
the installer carries and, because of that, where the thinking happens.

| | Claw Online | Claw Local |
|---|---|---|
| Inference | the Claw service | llama.cpp on this computer |
| Model weights in the installer | none | one brain (Light / Standard / Pro) |
| Inference engine in the installer | none | llama.cpp `llama-server.exe` |
| API key the user types | none | none |
| Needs the internet to think | yes | no |
| Computer-control tools, approvals, verification | identical | identical |

## The switch

`resources/edition.json`, written by the packaging profile and read by
`claw/edition.py`:

```json
{
  "id": "online",
  "name": "Claw Online",
  "local_inference": false,
  "service_url": "https://…/v1",
  "service_token": "…",
  "bundled_model": ""
}
```

A source checkout has no such file and is treated as **Local**, because a
checkout can build and run the engine. A damaged profile also falls back to
Local: that is the safe direction, because Local cannot start talking to a
server on its own.

`GET /edition` tells the interface which edition it is talking to and which
ways of thinking exist here, so Settings offers what the build can do instead
of offering a brain download in Claw Online and failing afterwards.

## The rules, and where they are enforced

- **Claw Online cannot run or download a local brain.** `PUT /settings` returns
  409 `wrong_edition` for `mode: builtin`, and `POST /brain/download` returns the
  same. Tested in `tests/test_editions.py`.
- **Claw Local cannot be switched to a Claw service it was not built with.** Same
  409. It can still use *your own* hosted model (`cloud` mode) if you choose it —
  that is an existing feature and it is never chosen for you.
- **An Online build with no service address says so.** It does not fall back to a
  local brain it does not have, nor to a key the user never gave. Its status
  reads `not_configured`, not `unreachable`, because retrying will never help.
- **The service token never leaves the backend.** It is not in `/edition`, not in
  `/settings`, and not in the dataclass `repr`.
- **The service address must be https.** A hosted brain carries the user's
  instructions, their documents and the token.

## Claw Online is not remote control

The service proposes an action and reads what came back. Every action is then
validated on this computer against the tool schemas, the permission policy, the
authorized-folder list and the approval rules, exactly as it is for a local
brain. Nothing the service returns reaches the desktop without passing those
checks, and nothing about the edition changes them. There is no path by which
the service drives the machine directly.

## Model profiles (Claw Local)

| Profile | Model | Download | Memory it asks for |
|---|---|---|---|
| Light | Qwen3-VL-2B-Instruct (Q4_K_M) | ~1.8 GB | 4 GB system / 2 GB VRAM |
| Standard | Qwen3-VL-4B-Instruct (Q4_K_M) | ~3.3 GB | 8 GB system / 4 GB VRAM |
| Pro | Qwen3-VL-8B-Instruct (Q4_K_M) | ~6.2 GB | 14 GB system / 8 GB VRAM |

Claw recommends the largest that fits the hardware it detects, and the smallest
if nothing fits. The engine refuses to start a model that will not fit in free
memory rather than letting Windows thrash.

**Light is new and its repository has not been reached from a networked machine
yet** — see "Not verified" below.

## Building them

```powershell
# Claw Online — small, no weights. The service address has no default on purpose.
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 `
  -Edition Online -ServiceUrl https://your-claw-service/v1 -ServiceToken <token>

# Claw Local — carries llama.cpp and one brain
powershell -ExecutionPolicy Bypass -File scripts\build-release.ps1 `
  -Edition Local -Brain Standard -SliceMB 1900
```

The script prints the measured size of what it produced. The GitHub workflow
(**Build Windows installer**) takes `edition`, `brain`, `service_url` and
`publish`; `publish` is **off** by default, so a build uploads the installer as
a run artifact and does not create a release. Its smoke test now fails the build
if the edition was built wrong: Claw Online carrying `llama-server.exe` or any
`.gguf`, or Claw Local carrying neither.

## Not verified

These need a Windows machine, a network, or both. Nothing below is claimed to
work:

1. **Installer sizes.** Neither installer has been built, so neither has been
   measured. The build prints sizes; this document will not guess them.
2. **Real inference, either edition.** No Claw service exists yet to point Claw
   Online at, and no model weights are reachable from the build container
   (huggingface.co and GitHub release assets are both refused by its egress
   policy). No prompt has been sent to any real model in either edition.
3. **The Light brain's repository.** `Qwen/Qwen3-VL-2B-Instruct-GGUF` and its file
   patterns were written by analogy with the 4B and 8B entries and have not been
   resolved against Hugging Face. If the repository or the file names differ, the
   download fails with "no file matched" — it cannot silently fetch the wrong
   thing, because files, sizes and checksums all come from the API — but someone
   has to run it once on a networked machine.
4. **The PowerShell changes.** `build-release.ps1` cannot be run or parsed in the
   Linux container. A parse check was added to the Windows test workflow so the
   next run catches a syntax error in about a minute instead of twenty minutes
   into a build.
5. **Offline operation end to end.** What is tested is that Claw Local's startup,
   settings, edition and brain paths touch no non-loopback socket, with every
   outbound connection refused (`test_local_edition_runs_with_no_network_at_all`).
   Thinking offline needs weights, so that half is untested here.
