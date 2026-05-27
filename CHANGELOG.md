# Changelog

## 1.4.3.27 - Stable Straight Style Generation

- Saved the current known-good Blender addon and Kimodo patch pair.
- Added Kimodo bridge API version `straight-style-generation-v9`.
- Added Style Strength support to normal generation, one-click bind, and loop generation.
- Added Path Points straight-line root constraint to normal generation, one-click bind, and loop generation.
- Kept loop-ready two-stage generation with optional debug comparison clips.
- Matched BVH import settings to the working debug workflow: no FPS scaling, frame start 1, `-Z` forward, `Y` up.
- Added copyable debug logs in the advanced Blender panel.
- Kept generation working even when no Mixamo target is selected; in that case retargeting is skipped.
- Moved local Kimodo URL/script/debug settings into a separate advanced panel.
- Updated the installable addon zip in `dist/`.

## 1.4.3.13 - Stable Prompt Segments Baseline

- Restored the stable Rokoko-based one-click retarget workflow.
- Added Blender-side prompt segment rows.
- Fixed Blender 4.5 panel draw error by avoiding Scene writes during `draw()`.
- Kept `Generate and Send BVH`, `One Click Generate + Bind`, and `One Click Bind Current BVH`.
- Excluded action-library experiments from this stable release.
- Added lightweight Kimodo patch files and Windows helper scripts.
- Documented that NVIDIA Kimodo, models, caches, venvs, and generated assets are not included.
