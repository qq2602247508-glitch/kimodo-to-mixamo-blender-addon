# Changelog

## 1.4.3.13 - Stable Prompt Segments Baseline

- Restored the stable Rokoko-based one-click retarget workflow.
- Added Blender-side prompt segment rows.
- Fixed Blender 4.5 panel draw error by avoiding Scene writes during `draw()`.
- Kept `Generate and Send BVH`, `One Click Generate + Bind`, and `One Click Bind Current BVH`.
- Excluded action-library experiments from this stable release.
- Added lightweight Kimodo patch files and Windows helper scripts.
- Documented that NVIDIA Kimodo, models, caches, venvs, and generated assets are not included.

## Notes

This release is the known-good local baseline used with:

- Kimodo WebUI on `7860`
- command API on `7870`
- Blender receiver on `8765`
