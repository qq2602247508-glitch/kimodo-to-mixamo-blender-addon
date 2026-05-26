import json
import re
from datetime import datetime
from pathlib import Path

import bpy

from .. import bridge


def _safe_slug(text):
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "action"


def _target(context):
    st = context.scene.rro_bridge
    return bridge._armature_from_object(st.target_object) or context.scene.rsl_retargeting_armature_target


def _library_root(context):
    path = bpy.path.abspath(context.scene.rro_bridge.action_library_path)
    return Path(path)


def _make_action_name(st):
    prefix = _safe_slug(st.character_prefix)
    action = _safe_slug(st.action_name)
    return f"{prefix}_{action}"


class ActionLibraryRefresh(bpy.types.Operator):
    bl_idname = "rro_action_library.refresh"
    bl_label = "Refresh Action Library"
    bl_description = "Scan the external action library folder"
    bl_options = {"REGISTER"}

    def execute(self, context):
        root = _library_root(context)
        context.scene.rro_action_library_items.clear()
        if not root.exists():
            self.report({"WARNING"}, f"Library folder does not exist: {root}")
            return {"FINISHED"}

        for meta_path in sorted(root.rglob("meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            blend_path = meta_path.parent / "action.blend"
            if not blend_path.exists():
                continue
            item = context.scene.rro_action_library_items.add()
            item.name = meta.get("name") or meta_path.parent.name
            item.path = str(blend_path)
            item.meta_path = str(meta_path)

        context.scene.rro_bridge.last_status = f"Loaded {len(context.scene.rro_action_library_items)} library actions"
        return {"FINISHED"}


class ActionLibrarySaveCurrent(bpy.types.Operator):
    bl_idname = "rro_action_library.save_current"
    bl_label = "Save Current Retarget to Library"
    bl_description = "Save the target's current retargeted action to the external action library"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.rro_bridge
        target = _target(context)
        if target is None:
            self.report({"ERROR"}, "Please select a Mixamo Target first.")
            return {"CANCELLED"}
        if not target.animation_data or not target.animation_data.action:
            self.report({"ERROR"}, "Target has no current action to save.")
            return {"CANCELLED"}

        action_name = _make_action_name(st)
        category = _safe_slug(st.action_category)
        root = _library_root(context)
        action_dir = root / "humanoid_mixamo" / category / action_name
        action_dir.mkdir(parents=True, exist_ok=True)

        saved_action = target.animation_data.action.copy()
        saved_action.name = action_name
        saved_action.use_fake_user = True
        blend_path = action_dir / "action.blend"
        bpy.data.libraries.write(str(blend_path), {saved_action}, fake_user=True)

        meta = {
            "name": action_name,
            "category": category,
            "character_prefix": _safe_slug(st.character_prefix),
            "prompt": st.prompt,
            "seed": st.prompt_seed,
            "duration": st.prompt_duration,
            "diffusion_steps": st.prompt_diffusion_steps,
            "target": target.name,
            "source_bvh": st.last_bvh_path,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "rig": "mixamo",
        }
        meta_path = action_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        st.last_status = f"Saved action: {action_name}"
        bpy.ops.rro_action_library.refresh()
        self.report({"INFO"}, f"Saved action to {blend_path}")
        return {"FINISHED"}


class ActionLibraryLoadSelected(bpy.types.Operator):
    bl_idname = "rro_action_library.load_selected"
    bl_label = "Load Selected Action"
    bl_description = "Load the selected external action and assign it to the current Mixamo target"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = _target(context)
        if target is None:
            self.report({"ERROR"}, "Please select a Mixamo Target first.")
            return {"CANCELLED"}

        items = context.scene.rro_action_library_items
        index = context.scene.rro_action_library_index
        if index < 0 or index >= len(items):
            self.report({"ERROR"}, "Select an action from the library list first.")
            return {"CANCELLED"}

        item = items[index]
        blend_path = Path(item.path)
        if not blend_path.exists():
            self.report({"ERROR"}, f"Action file not found: {blend_path}")
            return {"CANCELLED"}

        with bpy.data.libraries.load(str(blend_path), link=False) as (data_from, data_to):
            data_to.actions = list(data_from.actions)

        if not data_to.actions:
            self.report({"ERROR"}, "No action found in selected library file.")
            return {"CANCELLED"}

        action = data_to.actions[0]
        action.use_fake_user = True
        if target.animation_data is None:
            target.animation_data_create()
        target.animation_data.action = action
        context.scene.rro_bridge.last_status = f"Loaded action: {action.name}"
        self.report({"INFO"}, f"Loaded action {action.name}")
        return {"FINISHED"}


class RRO_UL_ActionLibrary(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        layout.label(text=item.name, icon="ACTION")
