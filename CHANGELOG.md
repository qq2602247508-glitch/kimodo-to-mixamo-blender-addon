# Changelog

## 1.4.10.0

- Fix old resource actions incorrectly appearing in `Current Model Action Library`.
- Add explicit action scopes: resource actions stay in `Resource Action Library`; current-model actions only appear after `Send to Current Model`.
- Keep temporary retarget source armatures visible while retargeting so Blender has an active object for Rokoko's mode switching.

## 1.4.9.0

- Simplify action library UI into `Current Model Action Library` and `Resource Action Library`.
- Make resource actions separate from current-model actions in the lists.
- Add `Send to Current Model` and `Delete` buttons to the resource library.
- Keep current-model actions focused on `Send Current Action to Resource Library`, `Show Selected Action`, and `Retarget Selected`.
- Remove the overloaded resource-library apply/load workflow.
- Fix one-click bind status reporting when source armatures are deleted after retarget.

## 1.4.8.0

- Make `Apply to Current Character` retarget through the Rokoko workflow instead of directly assigning an Action.
- Create a temporary source armature for library actions, rebuild the bone list, check/fix target axis, retarget, save to current character, then delete the temporary source.
- Add `Delete Source After Retarget`, enabled by default, to remove generated/imported BVH source armatures after successful retarget.

## 1.4.7.0

- Add `Action Library` to Blender Add-on Preferences.
- Store the external action library path at addon/user-preference level instead of per `.blend` scene.
- Keep the action library path editable from the sidebar panels while using the same global preference.

## 1.4.6.0

- Add `Apply to Current Character` in the full `Action Library` panel.
- Allow a fresh Mixamo target to load any existing library action and immediately save it under `Current Character Actions`.
- Check/fix the current Mixamo target axis before loading an external library action when possible.
- Record source library metadata in `meta.json` when an action is adopted from the full library.

## 1.4.5.0

- Split the action library UI into `Current Character Actions` and `Action Library`.
- Add a current-character action list filtered by `Character ID`.
- Leave `Character ID` empty to use the selected `Mixamo Target` name automatically.
- Make action save/load use the explicit `Mixamo Target` from the Kimodo Bridge panel.
- Prevent one-click bind and action loading from falling back to the first or old Rokoko target in multi-character scenes.
- Show character/category metadata in action lists.

## 1.4.4.0

- Add `Kimodo Action Library` panel.
- Add external action library path selection.
- Add `Save Current Retarget to Library`.
- Save each library action as `action.blend` plus `meta.json`.
- Add library scanning with `Refresh Action Library`.
- Add `Load Selected Action` to preview a saved external action on the current Mixamo target.

## 1.4.3.9

- Add `One Click Generate + Bind`.
- Add `One Click Bind Current BVH`.
- Add Kimodo prompt command integration.
- Add Blender BVH receiver.
- Add Mixamo target axis detection and automatic known-axis fix.
- Add Mixamo bone map correction for common arm/leg mapping errors.
- Keep original Rokoko retarget core for stable animation transfer.
