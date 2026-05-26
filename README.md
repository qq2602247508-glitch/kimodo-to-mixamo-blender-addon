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

1. Download the zip from `dist/rokoko_retarget_bridge_v1_4_6_0_apply_library_action.zip`.
2. In Blender, open `Edit > Preferences > Add-ons`.
3. Click `Install...`.
4. Select the zip file.
5. Enable `Rokoko Retarget Bridge`.
6. Open the 3D View sidebar, then the `Rokoko` tab.

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

### Save Current Action to External Library

Use this after a retargeted action looks good.

1. Open `Current Character Actions`.
2. Set `Action Library` to an external folder, for example:

```text
E:\400-game assets\ai\kimodo\action_library
```

3. Set:

- `Character ID`: optional. Leave empty to use the selected `Mixamo Target` name, or type a stable character id such as `hero`.
- `Category`: for example `idle`, `locomotion`, `jump`, `combat`
- `Action Name`: for example `idle_01`, `walk_forward_01`, `run_forward_01`

4. Click `Save Current Retarget to Library`.

The addon saves:

```text
action_library/
  humanoid_mixamo/
    locomotion/
      hero_walk_forward_01/
        action.blend
        meta.json
```

The `action.blend` stores the Blender Action datablock. The `meta.json` stores prompt, seed, duration, source BVH path, target name, and creation time.

### Current Character Actions

Use this page for the character you are currently working on.

1. Select the character in `Mixamo Target`.
2. Click `Refresh`.
3. The list shows only actions whose saved `Character ID` matches the current target or the typed `Character ID`.
4. Select an action and click `Load Current Character Action`.

This solves the multi-character scene problem: one-click bind and library load use the explicit `Mixamo Target` from the Kimodo Bridge panel, not the first Mixamo armature in the scene.

### Action Library

Use this page to browse every saved action in the external library.

1. Open `Action Library`.
2. Set `Action Library` to the folder that contains saved actions.
3. Click `Refresh Action Library`.
4. Select an action in the list.
5. Click `Load Selected Action`.

The selected Action is loaded from the external `.blend` file and assigned to the current Mixamo target.

### Apply Library Action to a New Character

Use this when you import a fresh Mixamo character and want to give it an existing library action.

1. Select the new character in `Mixamo Target`.
2. Open `Action Library`.
3. Click `Refresh Action Library`.
4. Select any saved action.
5. Click `Apply to Current Character`.

The addon loads the selected action onto the current Mixamo target, checks/fixes the target axis when possible, then saves a copy under `Current Character Actions` using the current target's `Character ID`.

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
