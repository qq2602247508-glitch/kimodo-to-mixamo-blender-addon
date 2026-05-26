import json
import re
from datetime import datetime
from pathlib import Path

import bpy

from .. import bridge, mixamo_tools


def _safe_slug(text):
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "action"


def _target(context):
    st = context.scene.rro_bridge
    return bridge._armature_from_object(st.target_object)


def _library_root(context):
    addon = bpy.context.preferences.addons.get(__package__.split(".")[0])
    path = addon.preferences.action_library_path if addon else context.scene.rro_bridge.action_library_path
    return Path(path)


def _make_action_name(st):
    return _character_action_name(bpy.context, st.action_name)


def _current_character_slug(context):
    st = context.scene.rro_bridge
    target = _target(context)
    if st.character_prefix.strip():
        return _safe_slug(st.character_prefix)
    if target is not None:
        return _safe_slug(target.name)
    return "humanoid"


def _fill_item(item, meta, meta_path, blend_path):
    item.name = meta.get("name") or meta_path.parent.name
    item.character_prefix = meta.get("character_prefix") or ""
    item.category = meta.get("category") or ""
    item.path = str(blend_path)
    item.meta_path = str(meta_path)


def _read_meta(item):
    if not item.meta_path:
        return {}
    meta_path = Path(item.meta_path)
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _character_action_name(context, action_name):
    return f"{_current_character_slug(context)}_{_safe_slug(action_name)}"


def _action_slug_from_library_item(item, meta):
    name = _safe_slug(meta.get("name") or item.name)
    old_character = _safe_slug(meta.get("character_prefix") or "")
    if old_character and name.startswith(old_character + "_"):
        name = name[len(old_character) + 1 :]
    return name or "action"


def _prepare_target(context, *, auto_fix_axis=True):
    target = _target(context)
    if target is None:
        raise RuntimeError("Please select a Mixamo Target first.")

    context.scene.rsl_retargeting_armature_target = target
    axis = mixamo_tools.analyze_target_axis(target)
    if not axis["ok"] and auto_fix_axis:
        fixed_axis = mixamo_tools.fix_target_axis(target)
        if not fixed_axis["ok"] and not fixed_axis.get("fixed"):
            raise RuntimeError("Target axis is abnormal and cannot be fixed automatically: " + fixed_axis["status"])
    return target


def _save_target_action(context, action_slug, category_slug, *, source_meta=None, source_item=None):
    st = context.scene.rro_bridge
    target = _prepare_target(context, auto_fix_axis=False)
    if not target.animation_data or not target.animation_data.action:
        raise RuntimeError("Target has no current action to save.")

    action_name = _character_action_name(context, action_slug)
    category = _safe_slug(category_slug)
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
        "character_prefix": _current_character_slug(context),
        "prompt": st.prompt,
        "seed": st.prompt_seed,
        "duration": st.prompt_duration,
        "diffusion_steps": st.prompt_diffusion_steps,
        "target": target.name,
        "source_bvh": st.last_bvh_path,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "rig": "mixamo",
    }
    if source_meta:
        meta["adopted_from"] = {
            "name": source_meta.get("name", ""),
            "character_prefix": source_meta.get("character_prefix", ""),
            "category": source_meta.get("category", ""),
        }
    if source_item is not None:
        meta["adopted_from_path"] = source_item.path

    meta_path = action_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return action_name, blend_path


def _duplicate_target_as_source(context, action, name_slug):
    target = _prepare_target(context, auto_fix_axis=True)
    source = target.copy()
    source.data = target.data.copy()
    source.name = f"LibrarySource_{name_slug}"
    source.data.name = f"{source.name}_Armature"
    source.animation_data_clear()
    source.animation_data_create()
    source.animation_data.action = action
    source.hide_viewport = True
    source.hide_render = True

    collection = bpy.data.collections.get("Kimodo Library Sources")
    if collection is None:
        collection = bpy.data.collections.new("Kimodo Library Sources")
        context.scene.collection.children.link(collection)
    collection.objects.link(source)
    return source


def _load_library_action_data(item):
    blend_path = Path(item.path)
    if not blend_path.exists():
        raise RuntimeError(f"Action file not found: {blend_path}")

    with bpy.data.libraries.load(str(blend_path), link=False) as (data_from, data_to):
        data_to.actions = list(data_from.actions)

    if not data_to.actions:
        raise RuntimeError("No action found in selected library file.")

    action = data_to.actions[0]
    action.use_fake_user = True
    return action


class ActionLibraryRefresh(bpy.types.Operator):
    bl_idname = "rro_action_library.refresh"
    bl_label = "Refresh Action Library"
    bl_description = "Scan the external action library folder"
    bl_options = {"REGISTER"}

    def execute(self, context):
        root = _library_root(context)
        context.scene.rro_action_library_items.clear()
        context.scene.rro_character_action_items.clear()
        if not root.exists():
            self.report({"WARNING"}, f"Library folder does not exist: {root}")
            return {"FINISHED"}

        current_character = _current_character_slug(context)
        for meta_path in sorted(root.rglob("meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            blend_path = meta_path.parent / "action.blend"
            if not blend_path.exists():
                continue
            item = context.scene.rro_action_library_items.add()
            _fill_item(item, meta, meta_path, blend_path)
            if _safe_slug(meta.get("character_prefix") or "") == current_character:
                character_item = context.scene.rro_character_action_items.add()
                _fill_item(character_item, meta, meta_path, blend_path)

        context.scene.rro_bridge.last_status = (
            f"Loaded {len(context.scene.rro_character_action_items)} current-character actions, "
            f"{len(context.scene.rro_action_library_items)} total"
        )
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

        action_name, blend_path = _save_target_action(context, st.action_name, st.action_category)
        st.last_status = f"Saved action: {action_name}"
        bpy.ops.rro_action_library.refresh()
        self.report({"INFO"}, f"Saved action to {blend_path}")
        return {"FINISHED"}


def _load_library_item(context, item, *, auto_fix_axis=True):
    target = _prepare_target(context, auto_fix_axis=auto_fix_axis)
    action = _load_library_action_data(item)
    if target.animation_data is None:
        target.animation_data_create()
    target.animation_data.action = action
    context.scene.rro_bridge.last_status = f"Loaded action: {action.name}"
    return action


class ActionLibraryLoadSelected(bpy.types.Operator):
    bl_idname = "rro_action_library.load_selected"
    bl_label = "Load Selected Action"
    bl_description = "Load the selected external action and assign it to the current Mixamo target"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        items = context.scene.rro_action_library_items
        index = context.scene.rro_action_library_index
        if index < 0 or index >= len(items):
            self.report({"ERROR"}, "Select an action from the library list first.")
            return {"CANCELLED"}

        try:
            action = _load_library_item(context, items[index])
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Loaded action {action.name}")
        return {"FINISHED"}


class ActionLibraryApplySelectedToCharacter(bpy.types.Operator):
    bl_idname = "rro_action_library.apply_selected_to_character"
    bl_label = "Apply to Current Character"
    bl_description = "Load the selected library action onto the current Mixamo target and save it under Current Character Actions"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.rro_bridge
        items = context.scene.rro_action_library_items
        index = context.scene.rro_action_library_index
        if index < 0 or index >= len(items):
            self.report({"ERROR"}, "Select an action from the library list first.")
            return {"CANCELLED"}

        item = items[index]
        meta = _read_meta(item)
        category = _safe_slug(meta.get("category") or st.action_category)
        action_slug = _action_slug_from_library_item(item, meta)

        try:
            action = _load_library_action_data(item)
            source = _duplicate_target_as_source(context, action, action_slug)
            bridge.run_bind_workflow(context, source, auto_fix_axis=True, delete_source=True)
            action_name, _blend_path = _save_target_action(
                context,
                action_slug,
                category,
                source_meta=meta,
                source_item=item,
            )
        except Exception as exc:
            st.last_status = f"Error: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        st.action_category = category
        st.action_name = action_slug
        st.last_status = f"Applied and saved for current character: {action_name}"
        bpy.ops.rro_action_library.refresh()
        self.report({"INFO"}, f"Applied and saved {action_name}")
        return {"FINISHED"}


class ActionLibraryLoadCharacterSelected(bpy.types.Operator):
    bl_idname = "rro_action_library.load_character_selected"
    bl_label = "Load Current Character Action"
    bl_description = "Load the selected action saved for the current character"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        items = context.scene.rro_character_action_items
        index = context.scene.rro_character_action_index
        if index < 0 or index >= len(items):
            self.report({"ERROR"}, "Select an action from the current character list first.")
            return {"CANCELLED"}

        try:
            action = _load_library_item(context, items[index])
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Loaded action {action.name}")
        return {"FINISHED"}


class RRO_UL_ActionLibrary(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        detail = " / ".join(part for part in (item.character_prefix, item.category) if part)
        if detail:
            layout.label(text=f"{item.name}  [{detail}]", icon="ACTION")
        else:
            layout.label(text=item.name, icon="ACTION")
