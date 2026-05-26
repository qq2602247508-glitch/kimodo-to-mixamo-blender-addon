# Changelog

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
