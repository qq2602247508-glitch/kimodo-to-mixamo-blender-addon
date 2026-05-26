# Kimodo to Mixamo Blender Addon

Blender addon for sending NVIDIA Kimodo BVH motions to a Mixamo-rigged character and retargeting them with a trimmed Rokoko retarget workflow.

This addon is meant for a local Kimodo setup:

- Kimodo WebUI on `http://127.0.0.1:7860`
- Kimodo prompt command API on `http://127.0.0.1:7870`
- Blender BVH receiver on `http://127.0.0.1:8765`

The addon keeps the working Rokoko retarget algorithm, removes the login/cloud workflow from daily use, and adds Kimodo-specific bridge tools.

## Features

- Receive BVH files from local Kimodo/WebUI.
- Send a prompt from Blender to local Kimodo.
- One-click generate and bind:
  - generate a Kimodo motion from a prompt
  - export as standard T-pose BVH
  - send to Blender
  - rebuild bone list
  - check Mixamo target axis
  - auto-fix known 90 degree target axis mismatch
  - fix common Mixamo bone map mistakes
  - retarget animation
- One-click bind current BVH sent manually from Kimodo/Viser.
- Fix common Rokoko auto-detection mistakes where arm bones are mapped to shoulder bones.
- Detect and fix Mixamo target rigs that face `+X` instead of standard Mixamo `-Y`.

## Install

1. Download the zip from `dist/rokoko_retarget_bridge_v1_4_10_0_scoped_action_libraries.zip`.
2. In Blender, open `Edit > Preferences > Add-ons`.
3. Click `Install...`.
4. Select the zip file.
5. Enable `Rokoko Retarget Bridge`.
6. Open the addon's preferences and set `Action Library` to your external action library folder.
7. Open the 3D View sidebar, then the `Rokoko` tab.

## Required Local Kimodo Patch

The Blender addon expects your local Kimodo WebUI to expose a prompt command API at:

```text
http://127.0.0.1:7870/kimodo-bridge/generate
```

In this local setup, Kimodo also exports BVH with `standard_tpose=True`, because Rokoko retargeting is stable with standard T-pose BVH.

If the addon says Kimodo is not listening on `7870`, start your patched local Kimodo first and wait until the WebUI opens.

## Blender Panel

Open:

```text
3D View > Sidebar > Rokoko > Kimodo Bridge
```

Main fields:

- `Port`: Blender receiver port. Default: `8765`.
- `Mixamo Target`: your target Mixamo armature or mesh.
- `Delete Source After Retarget`: remove generated/imported BVH source armatures after successful retarget. Enabled by default.
- `Kimodo URL`: local Kimodo command API. Default: `http://127.0.0.1:7870`.
- `Prompt`: motion prompt to generate.
- `Duration`: generated motion duration.
- `Seed`: generation seed.
- `Steps`: Kimodo denoising steps.

## Workflows

### One Click Generate + Bind

Use this when you want Blender to generate and retarget in one step.

1. Start Kimodo and wait until `http://127.0.0.1:7860` opens.
2. In Blender, select your Mixamo target in `Mixamo Target`.
3. Enter a prompt, for example:

```text
A person jumps forward and lands in a game animation style.
```

4. Click `One Click Generate + Bind`.

The addon will generate the BVH in Kimodo, receive it in Blender, auto-fix target axis if needed, rebuild the bone list, fix Mixamo mapping, and retarget.

### One Click Bind Current BVH

Use this when you manually send a BVH from Kimodo/Viser to Blender.

1. Send BVH from Kimodo/WebUI to Blender.
2. Select your Mixamo target in `Mixamo Target`.
3. Click `One Click Bind Current BVH`.

The addon will bind the current/last BVH source to the selected Mixamo target.

### Current Model Action Library

This page is for the selected Mixamo model only. A newly imported model starts with an empty current-model library.

1. Select the model in `Mixamo Target`.
2. Click `Refresh`.
3. Use `Send Current Action to Resource Library` after a generated/retargeted action looks good.
4. Use `Show Selected Action` to preview the selected current-model action.
5. Use `Retarget Selected` to run the one-click retarget workflow:

```text
Build Bone List -> Check/Fix Target Axis -> Retarget
```

The retarget target is the armature or mesh selected in `Mixamo Target`.

### Resource Action Library

This page is the shared action resource library.

1. Select a resource action.
2. Click `Send to Current Model` to copy it into the selected model's current-model library.
3. Click `Delete` to remove the selected resource action from disk.

Resource actions and current-model actions are stored with separate scopes. A new model has a clean empty current-model library until you explicitly click `Send to Current Model` from the resource library.

### Manual Tools

The `Retargeting` panel also includes:

- `Check Target Axis`: checks if the target rest pose is standard Mixamo.
- `Fix Target Axis`: fixes known target rigs that face `+X` instead of `-Y`.
- `Fix Mixamo Bone Map`: fixes arm/leg mapping mistakes after `Rebuild Bone List`.

## Mixamo Target Requirements

Best results come from a clean Mixamo rig:

- body faces `-Y`
- shoulders extend along `X`
- rest pose is T-pose or compatible with Mixamo
- bone names are standard Mixamo-style, such as `mixamorig:LeftArm`

If your model was exported from another tool and faces `+X`, use `Check Target Axis` and `Fix Target Axis`.

## Notes

- This addon does not include Kimodo model weights.
- This addon does not include NVIDIA Kimodo itself.
- Local Kimodo generation may take time while the text encoder loads.
- The retarget core is based on Rokoko's Blender retarget workflow, trimmed for local Kimodo/Mixamo use.
- External action library saving currently stores `.blend` Action data plus `meta.json`. FBX/Godot animation-pack export is planned as a later workflow step.

## License

This repository contains code derived from the Rokoko Blender addon and local bridge additions. See `rokoko_retarget_bridge/LICENSE.md` for the included license file.
