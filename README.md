# Kimodo to Mixamo Blender Addon

Stable local Blender bridge for generating NVIDIA Kimodo motions and retargeting them to Mixamo-rigged characters.

This repository intentionally does **not** include NVIDIA Kimodo, model weights, Hugging Face caches, Python virtual environments, Blender project files, or generated BVH/FBX outputs. It only contains the Blender addon and the lightweight local patch/scripts needed to connect an existing Kimodo checkout to Blender.

## Stable Version

Use:

```text
dist/kimodo_motion_bridge_v1_4_3_33_prefs_cache.zip
```

Known-good local setup:

- Blender addon version: `1.4.3.33`
- Kimodo bridge API version: `straight-style-path-toggle-v13`
- Kimodo WebUI: `http://127.0.0.1:7860`
- Kimodo command API: `http://127.0.0.1:7870`
- Blender BVH receiver: `http://127.0.0.1:8765`

## What Is Included

```text
rokoko_retarget_bridge/       Blender addon source
playback_speed_viewer/        Standalone animation loop preview and Godot export addon
dist/                         Stable installable addon zip
kimodo_patch/                 Lightweight files to copy into a local Kimodo setup
```

`kimodo_patch/kimodo/demo/bridge_api.py` adds a local HTTP command API to a patched Kimodo WebUI. The API accepts prompt requests from Blender, generates Kimodo motion, exports standard T-pose BVH, and sends that BVH back to Blender.

The bridge supports:

- Generate and send BVH to Blender.
- One-click generate and retarget to a selected Mixamo target.
- Loop-ready generation and retarget.
- Style Strength control.
- Path Points straight-line root constraint for normal generation and loop generation.
- Use Path Constraint toggle for normal generation and one-click bind.
- Optional debug comparison BVHs for loop generation.
- Copyable debug logs from the Blender addon.
- Chinese/English UI toggle in Blender addon preferences.
- Optional advanced panel toggle in Blender addon preferences.
- Configurable generated BVH/cache directory.

For backup or transfer, use the complete package:

```text
dist/kimodo_mixamo_v1_4_3_33_full_package.zip
```

## Animation Loop / Godot Export Addon

The standalone animation utility addon is included here too:

```text
playback_speed_viewer/
dist/animation_loop_godot_exporter_v1_4_1_arm_clearance_fix.zip
```

It is separate from the Kimodo retarget bridge and can be installed independently in Blender.

Main features:

- Drag or import BVH files for quick preview.
- Playback speed controls for checking animation timing.
- Trim custom start/end frames.
- Keyframe thinning and fill/interpolation workflow for smoother loop testing.
- In-place loop preparation helpers.
- Shoulder/arm offset tool for simple clothing clipping cleanup.
- Godot-friendly GLB export of the currently processed character animation.
```

## What Is Not Included

You must install or provide these yourself:

- NVIDIA Kimodo source checkout
- Kimodo model weights
- Meta Llama / LLM2Vec text encoder files
- Hugging Face token/access
- Python virtual environment
- Blender
- Your Mixamo character FBX files

Do not commit these folders to this repo:

```text
kimodo-src/
models/
Meta-Llama-3-8B-Instruct/
outputs/
logs/
.venv*/
```

## Blender Install

1. Open Blender.
2. Go to `Edit > Preferences > Add-ons`.
3. Click `Install...`.
4. Select:

```text
dist/kimodo_motion_bridge_v1_4_3_33_prefs_cache.zip
```

5. Enable `Kimodo 动作桥`.
6. Open `3D View > Sidebar > Kimodo 动作`.
7. In the addon preferences, choose Chinese/English UI and whether to show the advanced panel.

Install the animation utility addon the same way with:

```text
dist/animation_loop_godot_exporter_v1_4_1_arm_clearance_fix.zip
```

## Local Kimodo Patch

Copy the patch files into your local Kimodo workspace:

```text
kimodo_patch/kimodo/demo/bridge_api.py -> kimodo-src/kimodo/demo/bridge_api.py
kimodo_patch/scripts/*.ps1             -> scripts/
```

Your Kimodo app must call `start_bridge_api(demo)` during WebUI startup. In this local workspace that hook is already present. If you are applying this repo to a fresh Kimodo checkout, add the hook near the place where the demo server is initialized.

Start Kimodo with:

```powershell
.\scripts\start_kimodo_demo_local_llama_logged.ps1
```

Then open:

```text
http://127.0.0.1:7860/
```

Keep the WebUI open once before sending prompts from Blender. The command API uses the active WebUI client session.

Check the command API:

```text
http://127.0.0.1:7870/health
```

It should report:

```json
{"ok": true, "bridge_version": "straight-style-path-toggle-v10"}
```

## Workflow

1. Start Kimodo and wait until the WebUI opens.
2. Open Blender and import your Mixamo character.
3. In `Kimodo Bridge`, set `Mixamo Target` to your character armature or mesh.
4. Enter a prompt, duration, seed, steps, Style Strength, Use Path Constraint, and Path Points.
5. Click `Generate and Send BVH` to only receive BVH.
6. Click `One Click Generate + Bind` to generate, receive, rebuild bone list, fix known Mixamo mapping issues, and retarget.
7. Click `Loop Generate + Bind` for loop-ready walking/running style clips.
8. Click `One Click Bind Current BVH` for a BVH that was manually sent/imported.

If no Mixamo target is selected, generation still runs and imports the BVH; retargeting is skipped.

## Important Stability Notes

- Run only one Kimodo WebUI instance at a time. If multiple instances are open, Viser may move to ports like `7861`, `7862`, or `7863`, and the command API session can become confusing.
- If Blender says `Open Kimodo WebUI once before sending prompts from Blender`, open `http://127.0.0.1:7860/` and wait for the page to finish loading.
- If Kimodo cannot send BVH to Blender, make sure the Blender addon receiver is listening on port `8765`.
- The repository stores only the patch/addon. Keep model files and generated assets outside git.

## License

This repository contains code derived from the Rokoko Blender addon plus local Kimodo bridge additions. See `rokoko_retarget_bridge/LICENSE.md` for the included license file.
