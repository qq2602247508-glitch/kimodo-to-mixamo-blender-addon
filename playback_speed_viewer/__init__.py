bl_info = {
    "name": "动画循环预览与 Godot 导出",
    "author": "Codex",
    "version": (1, 4, 2),
    "blender": (4, 0, 0),
    "location": "3D View > Sidebar > 动画工具",
    "description": "预览动画速度，处理循环关键帧，并导出 Godot 友好的 GLB。",
    "category": "Animation",
}

import os
import re
import time
import traceback
from math import radians

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from mathutils import Euler, Quaternion


TEMP_TRACK_PREFIX = "__PSV_GODOT_EXPORT__"


_timer_state = {
    "last_time": None,
    "fraction": 0.0,
}


def _scene_fps(scene):
    base = scene.render.fps_base if scene.render.fps_base else 1.0
    return scene.render.fps / base


def _sanitize_name(name):
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", name.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "animation"


def _is_armature(obj):
    return obj is not None and obj.type == "ARMATURE"


def _find_selected_armature(context):
    active = context.object
    if _is_armature(active):
        return active

    if active and active.type == "MESH":
        for modifier in active.modifiers:
            if modifier.type == "ARMATURE" and _is_armature(modifier.object):
                return modifier.object
        if _is_armature(active.parent):
            return active.parent

    for obj in context.selected_objects:
        if _is_armature(obj):
            return obj
        if obj.type == "MESH":
            for modifier in obj.modifiers:
                if modifier.type == "ARMATURE" and _is_armature(modifier.object):
                    return modifier.object
            if _is_armature(obj.parent):
                return obj.parent
    return None


def _bound_meshes_for_armature(context, armature):
    meshes = []
    for obj in context.scene.objects:
        if obj.type != "MESH":
            continue

        uses_armature = obj.parent == armature
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" and modifier.object == armature:
                uses_armature = True
                break

        if uses_armature:
            meshes.append(obj)
    return meshes


def _safe_object_mode(context):
    active = context.view_layer.objects.active
    if not active or active.mode == "OBJECT":
        return
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except RuntimeError:
        pass


def _pose_bone_names_from_action(action):
    names = set()
    pattern = re.compile(r'pose\.bones\["([^"]+)"\]')
    if not action:
        return names
    for fcurve in action.fcurves:
        match = pattern.search(fcurve.data_path)
        if match:
            names.add(match.group(1))
    return names


def _compatible_action(action, armature):
    if not action or not _is_armature(armature):
        return False
    action_bones = _pose_bone_names_from_action(action)
    if not action_bones:
        return False
    target_bones = {bone.name for bone in armature.data.bones}
    return not bool(action_bones - target_bones)


def _remove_temp_tracks(armature):
    if not armature.animation_data:
        return
    for track in list(armature.animation_data.nla_tracks):
        if track.name.startswith(TEMP_TRACK_PREFIX):
            armature.animation_data.nla_tracks.remove(track)


def _compatible_actions_for_armature(armature):
    if not _is_armature(armature):
        return []

    ordered = []
    seen = set()

    def add(action):
        if action and action.name not in seen and _compatible_action(action, armature):
            ordered.append(action)
            seen.add(action.name)

    if armature.animation_data:
        add(armature.animation_data.action)
        for track in armature.animation_data.nla_tracks:
            for strip in track.strips:
                add(strip.action)

    for action in sorted(bpy.data.actions, key=lambda item: item.name.lower()):
        add(action)
    return ordered


def _action_enum_items(self, context):
    scene = context.scene
    armature = scene.psv_godot_target_armature or _find_selected_armature(context)
    actions = _compatible_actions_for_armature(armature)
    if not actions:
        return [("", "没有识别到兼容动作", "当前角色没有可导出的兼容 Action")]

    active = armature.animation_data.action if armature and armature.animation_data else None
    items = []
    for action in actions:
        start, end = action.frame_range
        label = action.name
        if active == action:
            label += "  [当前]"
        items.append(
            (
                action.name,
                label,
                f"Godot 动画名: {_sanitize_name(action.name)} | 帧范围 {start:g}-{end:g}",
            )
        )
    return items


def _selected_godot_action(scene, armature):
    selected = scene.psv_godot_action_name
    if selected:
        action = bpy.data.actions.get(selected)
        if _compatible_action(action, armature):
            return action

    if armature.animation_data and _compatible_action(armature.animation_data.action, armature):
        return armature.animation_data.action

    actions = _compatible_actions_for_armature(armature)
    return actions[0] if actions else None


def _create_temp_nla_tracks(armature, actions):
    armature.animation_data_create()
    _remove_temp_tracks(armature)
    for export_name, action in actions:
        start, end = action.frame_range
        start = int(round(start))
        end = max(int(round(end)), start + 1)
        track = armature.animation_data.nla_tracks.new()
        track.name = TEMP_TRACK_PREFIX + export_name
        strip = track.strips.new(export_name, start, action)
        strip.name = export_name
        strip.frame_start = start
        strip.frame_end = end
        track.mute = False
        track.lock = False


def _select_export_objects(context, armature):
    meshes = _bound_meshes_for_armature(context, armature)
    _safe_object_mode(context)
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)
    context.view_layer.objects.active = armature
    return meshes


def _output_path(context, armature, action_name=None):
    scene = context.scene
    output_dir = bpy.path.abspath(scene.psv_godot_output_dir)
    if not output_dir:
        output_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    os.makedirs(output_dir, exist_ok=True)

    file_name = scene.psv_godot_file_name.strip()
    if action_name and scene.psv_godot_auto_action_filename:
        file_name = f"{_sanitize_name(armature.name)}_{_sanitize_name(action_name)}.glb"
    if not file_name:
        file_name = _sanitize_name(armature.name) + "_godot.glb"
    if not file_name.lower().endswith(".glb"):
        file_name += ".glb"
    return os.path.join(output_dir, file_name)


def _speed_timer():
    scene = bpy.context.scene
    if scene is None or not scene.psv_enable_speed:
        _timer_state["last_time"] = None
        _timer_state["fraction"] = 0.0
        return None

    now = time.perf_counter()
    last_time = _timer_state["last_time"]
    _timer_state["last_time"] = now

    if last_time is None:
        return 0.01

    fps = _scene_fps(scene)
    delta_frames = (now - last_time) * fps * scene.psv_speed_multiplier
    delta_total = delta_frames + _timer_state["fraction"]
    whole = int(delta_total)
    _timer_state["fraction"] = delta_total - whole

    if whole <= 0:
        return 0.01

    frame_start = scene.frame_start
    frame_end = scene.frame_end
    next_frame = scene.frame_current + whole

    if next_frame > frame_end:
        span = max(1, frame_end - frame_start + 1)
        next_frame = frame_start + ((next_frame - frame_start) % span)

    scene.frame_set(next_frame)
    return 0.01


def _ensure_timer_running():
    if not bpy.app.timers.is_registered(_speed_timer):
        bpy.app.timers.register(_speed_timer)


def _stop_native_playback(context):
    screen = context.screen
    if screen and screen.is_animation_playing:
        bpy.ops.screen.animation_cancel(restore_frame=False)


def _active_action(context):
    obj = context.object
    if obj is None or obj.animation_data is None or obj.animation_data.action is None:
        return None
    return obj.animation_data.action


def _action_frame_range(action, scene):
    start = int(round(scene.frame_start))
    end = int(round(scene.frame_end))
    if action is not None and action.fcurves:
        a_start, a_end = action.frame_range
        start = int(round(a_start))
        end = int(round(a_end))
    return start, max(start, end)


def _set_interpolation(action, interpolation):
    for fcurve in action.fcurves:
        for key in fcurve.keyframe_points:
            key.interpolation = interpolation


def _location_axis_name(index):
    return ("X", "Y", "Z")[index]


def _horizontal_location_indices(height_axis):
    height_index = {"X": 0, "Y": 1, "Z": 2}[height_axis]
    return [idx for idx in (0, 1, 2) if idx != height_index]


def _is_location_fcurve(fcurve):
    return fcurve.data_path == "location" or fcurve.data_path.endswith(".location")


def _force_exact_loop(action, start_frame, end_frame):
    for fcurve in action.fcurves:
        first_value = fcurve.evaluate(start_frame)
        fcurve.keyframe_points.insert(end_frame, first_value, options={"REPLACE"})
    _set_interpolation(action, "BEZIER")


def _lock_horizontal_location(action, start_frame, height_axis):
    horizontal_indices = _horizontal_location_indices(height_axis)
    changed = 0
    for fcurve in action.fcurves:
        if not _is_location_fcurve(fcurve) or fcurve.array_index not in horizontal_indices:
            continue
        base_value = fcurve.evaluate(start_frame)
        for key in fcurve.keyframe_points:
            key.co.y = base_value
            key.handle_left.y = base_value
            key.handle_right.y = base_value
        changed += 1
    return changed


def _copy_trimmed_action(source_action, source_start, source_end, trim_start, trim_end, interpolation):
    new_start_source = source_start + trim_start
    new_end_source = source_end - trim_end
    if new_end_source <= new_start_source:
        raise ValueError("Trim range leaves fewer than 2 frames.")

    new_action = bpy.data.actions.new(
        f"{source_action.name}_trim{trim_start}_{trim_end}"
    )
    new_action.frame_start = 1
    new_action.frame_end = 1 + (new_end_source - new_start_source)

    for source_fcurve in source_action.fcurves:
        new_fcurve = new_action.fcurves.new(
            data_path=source_fcurve.data_path,
            index=source_fcurve.array_index,
            action_group=source_fcurve.group.name if source_fcurve.group else "",
        )
        for source_frame in range(new_start_source, new_end_source + 1):
            new_frame = 1 + (source_frame - new_start_source)
            new_value = source_fcurve.evaluate(source_frame)
            new_fcurve.keyframe_points.insert(new_frame, new_value, options={"FAST"})
        new_fcurve.update()

    _set_interpolation(new_action, interpolation)
    return new_action


def _copy_action_sampled(source_action, start_frame, end_frame, suffix, interpolation):
    new_action = bpy.data.actions.new(f"{source_action.name}_{suffix}")
    new_action.frame_start = start_frame
    new_action.frame_end = end_frame

    for source_fcurve in source_action.fcurves:
        new_fcurve = new_action.fcurves.new(
            data_path=source_fcurve.data_path,
            index=source_fcurve.array_index,
            action_group=source_fcurve.group.name if source_fcurve.group else "",
        )
        for frame in range(start_frame, end_frame + 1):
            new_fcurve.keyframe_points.insert(
                frame,
                source_fcurve.evaluate(frame),
                options={"FAST"},
            )
        new_fcurve.update()

    _set_interpolation(new_action, interpolation)
    return new_action


def _pose_bone_candidates(armature, side, include_shoulders, include_upper_arms):
    side_words = {
        "L": ("left", "_l", ".l"),
        "R": ("right", "_r", ".r"),
    }[side]
    role_words = []
    if include_shoulders:
        role_words.extend(("shoulder", "clavicle"))
    if include_upper_arms:
        role_words.extend(("arm", "upperarm", "uparm"))

    matches = []
    for bone in armature.pose.bones:
        normalized = bone.name.lower().replace("mixamorig:", "")
        is_side = any(word in normalized for word in side_words)
        is_role = any(word in normalized for word in role_words)
        if is_side and is_role and "forearm" not in normalized and "hand" not in normalized:
            matches.append(bone)
    return matches


def _rotation_mode_for_bone(pose_bone):
    mode = pose_bone.rotation_mode
    return mode if mode and mode != "QUATERNION" else "XYZ"


def _find_fcurve(action, data_path, array_index):
    if action is None:
        return None
    for fcurve in action.fcurves:
        if fcurve.data_path == data_path and fcurve.array_index == array_index:
            return fcurve
    return None


def _apply_euler_offset_to_bone(armature, bone_name, axis, angle_degrees, start_frame, end_frame):
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone is None:
        return

    scene = bpy.context.scene
    original_frame = scene.frame_current
    original_mode = pose_bone.rotation_mode
    axis_index = {"X": 0, "Y": 1, "Z": 2}[axis]
    delta = radians(angle_degrees)
    action = armature.animation_data.action if armature.animation_data else None
    euler_path = pose_bone.path_from_id("rotation_euler")
    quat_path = pose_bone.path_from_id("rotation_quaternion")
    axis_angle_path = pose_bone.path_from_id("rotation_axis_angle")

    quat_fcurves = [_find_fcurve(action, quat_path, idx) for idx in range(4)]
    euler_fcurves = [_find_fcurve(action, euler_path, idx) for idx in range(3)]
    has_quat = all(fcurve is not None for fcurve in quat_fcurves)
    has_euler = any(fcurve is not None for fcurve in euler_fcurves)

    sampled_eulers = []
    if has_quat:
        for frame in range(start_frame, end_frame + 1):
            quat = Quaternion(tuple(fcurve.evaluate(frame) for fcurve in quat_fcurves))
            sampled_eulers.append(quat.to_euler("XYZ"))
    elif has_euler:
        base = pose_bone.rotation_euler.copy()
        for frame in range(start_frame, end_frame + 1):
            sampled_eulers.append(
                Euler(
                    tuple(
                        euler_fcurves[idx].evaluate(frame)
                        if euler_fcurves[idx] is not None
                        else base[idx]
                        for idx in range(3)
                    ),
                    "XYZ",
                )
            )
    else:
        for frame in range(start_frame, end_frame + 1):
            scene.frame_set(frame)
            sampled_eulers.append(pose_bone.rotation_euler.copy())

    if action is not None:
        for data_path in (quat_path, axis_angle_path):
            for fcurve in list(action.fcurves):
                if fcurve.data_path == data_path:
                    action.fcurves.remove(fcurve)

    pose_bone.rotation_mode = "XYZ"
    for frame, euler in zip(range(start_frame, end_frame + 1), sampled_eulers):
        scene.frame_set(frame)
        euler[axis_index] += delta
        pose_bone.rotation_euler = euler
        pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame, options={"INSERTKEY_REPLACE"})

    if original_mode != "QUATERNION":
        pose_bone.rotation_mode = original_mode
    scene.frame_set(original_frame)


class PSV_OT_set_speed(bpy.types.Operator):
    bl_idname = "psv.set_speed"
    bl_label = "Set Preview Speed"
    bl_options = {"REGISTER", "UNDO"}

    speed: FloatProperty(name="Speed", default=1.0, min=0.05, max=4.0)

    def execute(self, context):
        context.scene.psv_speed_multiplier = self.speed
        return {"FINISHED"}


class PSV_OT_play_pause(bpy.types.Operator):
    bl_idname = "psv.play_pause"
    bl_label = "Play/Pause Speed Preview"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene = context.scene
        scene.psv_enable_speed = not scene.psv_enable_speed
        if scene.psv_enable_speed:
            _stop_native_playback(context)
            _ensure_timer_running()
        return {"FINISHED"}


class PSV_OT_stop(bpy.types.Operator):
    bl_idname = "psv.stop"
    bl_label = "Stop Speed Preview"
    bl_options = {"REGISTER"}

    def execute(self, context):
        context.scene.psv_enable_speed = False
        _timer_state["last_time"] = None
        _timer_state["fraction"] = 0.0
        return {"FINISHED"}


class PSV_OT_set_fps(bpy.types.Operator):
    bl_idname = "psv.set_fps"
    bl_label = "Set Scene FPS"
    bl_options = {"REGISTER", "UNDO"}

    fps: FloatProperty(name="FPS", default=30.0, min=1.0, max=240.0)

    def execute(self, context):
        context.scene.render.fps = int(round(self.fps))
        context.scene.render.fps_base = 1.0
        return {"FINISHED"}


class PSV_OT_set_godot_target(bpy.types.Operator):
    bl_idname = "psv.set_godot_target"
    bl_label = "设置导出角色"
    bl_options = {"REGISTER"}

    def execute(self, context):
        armature = _find_selected_armature(context)
        if not armature:
            self.report({"WARNING"}, "请先选择角色骨架，或选择绑定到骨架的模型。")
            return {"CANCELLED"}
        context.scene.psv_godot_target_armature = armature
        self.report({"INFO"}, "导出角色: " + armature.name)
        return {"FINISHED"}


class PSV_OT_export_godot_glb(bpy.types.Operator):
    bl_idname = "psv.export_godot_glb"
    bl_label = "导出 Godot GLB"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="导出模式",
        items=(
            ("ACTIVE", "当前动作", "只导出当前骨架正在使用的 Action"),
            ("SELECTED", "选中动作", "导出动作列表里选中的 Action，并按角色名_动作名命名"),
            ("COMPATIBLE", "全部兼容动作", "导出所有骨骼名匹配当前骨架的 Action"),
        ),
        default="SELECTED",
    )

    def execute(self, context):
        scene = context.scene
        armature = scene.psv_godot_target_armature or _find_selected_armature(context)
        if not armature:
            self.report({"ERROR"}, "请先选择导出角色骨架。")
            return {"CANCELLED"}
        scene.psv_godot_target_armature = armature

        actions = []
        export_action_name = None
        if self.mode == "ACTIVE":
            action = armature.animation_data.action if armature.animation_data else None
            if action is None:
                self.report({"ERROR"}, "当前角色没有活动 Action。")
                return {"CANCELLED"}
            if not _compatible_action(action, armature):
                self.report({"ERROR"}, "当前 Action 的骨骼名和目标骨架不匹配。")
                return {"CANCELLED"}
            export_action_name = action.name
            actions.append((_sanitize_name(action.name), action))
        elif self.mode == "SELECTED":
            action = _selected_godot_action(scene, armature)
            if action is None:
                self.report({"ERROR"}, "当前角色没有可导出的兼容动作。")
                return {"CANCELLED"}
            export_action_name = action.name
            scene.psv_godot_action_name = action.name
            actions.append((_sanitize_name(action.name), action))
        else:
            for action in _compatible_actions_for_armature(armature):
                actions.append((_sanitize_name(action.name), action))
            if not actions:
                self.report({"ERROR"}, "没有找到和当前骨架兼容的 Action。")
                return {"CANCELLED"}

        filepath = _output_path(context, armature, export_action_name if len(actions) == 1 else None)
        original_selection = list(context.selected_objects)
        original_active = context.view_layer.objects.active
        keep_tracks = scene.psv_godot_keep_tracks

        try:
            _safe_object_mode(context)
            meshes = _select_export_objects(context, armature)
            if not meshes:
                self.report({"WARNING"}, "没有找到绑定到该骨架的 Mesh，将只导出骨架和动画。")

            _create_temp_nla_tracks(armature, actions)
            bpy.ops.export_scene.gltf(
                filepath=filepath,
                export_format="GLB",
                use_selection=True,
                export_yup=True,
                export_apply=False,
                export_animations=True,
                export_animation_mode="NLA_TRACKS",
                export_nla_strips=True,
                export_anim_single_armature=True,
                export_force_sampling=True,
                export_frame_range=False,
                export_skins=True,
                export_def_bones=False,
                export_reset_pose_bones=True,
                export_leaf_bone=False,
                export_lights=False,
                export_cameras=False,
            )
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, "导出失败: " + str(exc))
            return {"CANCELLED"}
        finally:
            if not keep_tracks:
                _remove_temp_tracks(armature)
            try:
                bpy.ops.object.select_all(action="DESELECT")
                for obj in original_selection:
                    if obj.name in bpy.data.objects:
                        obj.select_set(True)
                if original_active and original_active.name in bpy.data.objects:
                    context.view_layer.objects.active = original_active
            except RuntimeError:
                pass

        self.report({"INFO"}, f"已导出 {len(actions)} 个动作: {filepath}")
        return {"FINISHED"}


class PSV_OT_force_exact_loop(bpy.types.Operator):
    bl_idname = "psv.force_exact_loop"
    bl_label = "Make First/Last Identical"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        action = _active_action(context)
        if action is None:
            self.report({"WARNING"}, "Select an object with an active action.")
            return {"CANCELLED"}

        start, end = _action_frame_range(action, context.scene)
        _force_exact_loop(action, start, end)
        self.report({"INFO"}, f"Matched frame {end} to frame {start}.")
        return {"FINISHED"}


class PSV_OT_make_inplace(bpy.types.Operator):
    bl_idname = "psv.make_inplace"
    bl_label = "Make In-place"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        action = _active_action(context)
        if action is None:
            self.report({"WARNING"}, "Select an object with an active action.")
            return {"CANCELLED"}

        start, _end = _action_frame_range(action, context.scene)
        changed = _lock_horizontal_location(action, start, context.scene.psv_height_axis)
        self.report(
            {"INFO"},
            f"Locked {changed} horizontal location curve(s); height axis is {_location_axis_name({'X': 0, 'Y': 1, 'Z': 2}[context.scene.psv_height_axis])}.",
        )
        return {"FINISHED"}


class PSV_OT_sparse_to_target_fps(bpy.types.Operator):
    bl_idname = "psv.sparse_to_target_fps"
    bl_label = "Sparse Keys To Target FPS"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        obj = context.object
        source_action = _active_action(context)
        if obj is None or source_action is None:
            self.report({"WARNING"}, "Select an object with an active action.")
            return {"CANCELLED"}

        key_step = max(1, int(scene.psv_key_step))
        source_fps = _scene_fps(scene)
        target_fps = max(1.0, float(scene.psv_target_fps))
        ratio = target_fps / source_fps
        start, end = _action_frame_range(source_action, scene)
        source_frames = list(range(start, end + 1, key_step))
        if source_frames[-1] != end:
            source_frames.append(end)

        new_action = bpy.data.actions.new(
            f"{source_action.name}_sparse{key_step}_{int(round(target_fps))}fps"
        )
        new_start = 1

        for source_fcurve in source_action.fcurves:
            new_fcurve = new_action.fcurves.new(
                data_path=source_fcurve.data_path,
                index=source_fcurve.array_index,
                action_group=source_fcurve.group.name if source_fcurve.group else "",
            )
            for source_frame in source_frames:
                new_frame = new_start + (source_frame - start) * ratio
                new_value = source_fcurve.evaluate(source_frame)
                new_fcurve.keyframe_points.insert(new_frame, new_value, options={"FAST"})
            new_fcurve.update()

        scene.render.fps = int(round(target_fps))
        scene.render.fps_base = 1.0
        new_end = int(round(new_start + (end - start) * ratio))
        scene.frame_start = new_start
        scene.frame_end = max(new_start, new_end)

        if scene.psv_loop_make_inplace:
            _lock_horizontal_location(new_action, new_start, scene.psv_height_axis)

        if scene.psv_loop_exact:
            _force_exact_loop(new_action, new_start, scene.frame_end)

        _set_interpolation(new_action, scene.psv_key_interpolation)
        obj.animation_data.action = new_action

        self.report(
            {"INFO"},
            f"Created {new_action.name}: step {key_step}, {target_fps:g} fps, frames {scene.frame_start}-{scene.frame_end}.",
        )
        return {"FINISHED"}


class PSV_OT_trim_action(bpy.types.Operator):
    bl_idname = "psv.trim_action"
    bl_label = "Trim Current Action"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        obj = context.object
        source_action = _active_action(context)
        if obj is None or source_action is None:
            self.report({"WARNING"}, "Select an object with an active action.")
            return {"CANCELLED"}

        trim_start = max(0, int(scene.psv_trim_start_frames))
        trim_end = max(0, int(scene.psv_trim_end_frames))
        if trim_start == 0 and trim_end == 0:
            self.report({"WARNING"}, "Set start or end trim frames first.")
            return {"CANCELLED"}

        source_start, source_end = _action_frame_range(source_action, scene)
        try:
            new_action = _copy_trimmed_action(
                source_action,
                source_start,
                source_end,
                trim_start,
                trim_end,
                scene.psv_key_interpolation,
            )
        except ValueError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        obj.animation_data.action = new_action
        scene.frame_start = int(new_action.frame_start)
        scene.frame_end = int(new_action.frame_end)
        scene.frame_current = scene.frame_start

        self.report(
            {"INFO"},
            f"Created {new_action.name}: removed {trim_start} start frame(s), {trim_end} end frame(s).",
        )
        return {"FINISHED"}


class PSV_OT_offset_arms(bpy.types.Operator):
    bl_idname = "psv.offset_arms"
    bl_label = "Offset Arms For Clearance"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        armature = context.object
        source_action = _active_action(context)
        if not _is_armature(armature) or source_action is None:
            self.report({"WARNING"}, "Select an armature with an active action.")
            return {"CANCELLED"}

        include_shoulders = bool(scene.psv_arm_include_shoulders)
        include_upper_arms = bool(scene.psv_arm_include_upper_arms)
        if not include_shoulders and not include_upper_arms:
            self.report({"WARNING"}, "Enable shoulders or upper arms first.")
            return {"CANCELLED"}

        start, end = _action_frame_range(source_action, scene)
        new_action = _copy_action_sampled(
            source_action,
            start,
            end,
            f"arm_clear_{int(round(scene.psv_arm_offset_degrees))}",
            scene.psv_key_interpolation,
        )
        armature.animation_data.action = new_action
        scene.frame_start = start
        scene.frame_end = end

        left_bones = _pose_bone_candidates(armature, "L", include_shoulders, include_upper_arms)
        right_bones = _pose_bone_candidates(armature, "R", include_shoulders, include_upper_arms)
        if not left_bones and not right_bones:
            self.report({"ERROR"}, "No matching left/right arm bones found.")
            return {"CANCELLED"}

        angle = float(scene.psv_arm_offset_degrees)
        axis = scene.psv_arm_offset_axis
        for bone in left_bones:
            _apply_euler_offset_to_bone(armature, bone.name, axis, angle, start, end)
        for bone in right_bones:
            _apply_euler_offset_to_bone(armature, bone.name, axis, -angle, start, end)

        self.report(
            {"INFO"},
            f"Created {new_action.name}: offset {len(left_bones)} left and {len(right_bones)} right arm bone(s).",
        )
        return {"FINISHED"}


class PSV_PT_panel(bpy.types.Panel):
    bl_label = "动画工具"
    bl_idname = "PSV_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "动画工具"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        fps = _scene_fps(scene)
        effective = fps * scene.psv_speed_multiplier

        row = layout.row(align=True)
        icon = "PAUSE" if scene.psv_enable_speed else "PLAY"
        row.operator("psv.play_pause", text="播放" if not scene.psv_enable_speed else "暂停", icon=icon)
        row.operator("psv.stop", text="", icon="SNAP_FACE")

        layout.prop(scene, "psv_speed_multiplier", text="播放速度")

        row = layout.row(align=True)
        for value in (0.5, 0.75, 1.0):
            op = row.operator("psv.set_speed", text=f"{value:g}x")
            op.speed = value

        row = layout.row(align=True)
        for value in (1.25, 1.5, 2.0):
            op = row.operator("psv.set_speed", text=f"{value:g}x")
            op.speed = value

        box = layout.box()
        box.label(text=f"场景 FPS: {fps:g}")
        box.label(text=f"预览 FPS: {effective:g}")
        box.label(text=f"当前帧: {scene.frame_current} / {scene.frame_end}")

        row = layout.row(align=True)
        op = row.operator("psv.set_fps", text="30 FPS")
        op.fps = 30
        op = row.operator("psv.set_fps", text="60 FPS")
        op.fps = 60

        layout.separator()
        layout.label(text="循环处理")
        row = layout.row(align=True)
        row.operator("psv.force_exact_loop", text="首尾一致")
        row.operator("psv.make_inplace", text="原地化")

        layout.prop(scene, "psv_height_axis", text="高度轴")
        layout.prop(scene, "psv_key_step", text="抽帧间隔")
        layout.prop(scene, "psv_target_fps", text="目标 FPS")
        layout.prop(scene, "psv_key_interpolation", text="插值")
        layout.prop(scene, "psv_loop_exact", text="生成后首尾一致")
        layout.prop(scene, "psv_loop_make_inplace", text="生成后原地化")
        layout.operator("psv.sparse_to_target_fps", text="抽帧并补到目标 FPS")

        layout.separator()
        layout.label(text="Godot 导出")
        layout.separator()
        layout.label(text="裁剪动作")
        row = layout.row(align=True)
        row.prop(scene, "psv_trim_start_frames", text="删开头")
        row.prop(scene, "psv_trim_end_frames", text="删结尾")
        layout.operator("psv.trim_action", text="裁剪当前动作")

        layout.separator()
        layout.label(text="手臂防穿模")
        layout.prop(scene, "psv_arm_offset_degrees", text="外扩角度")
        layout.prop(scene, "psv_arm_offset_axis", text="旋转轴")
        row = layout.row(align=True)
        row.prop(scene, "psv_arm_include_shoulders", text="肩膀")
        row.prop(scene, "psv_arm_include_upper_arms", text="上臂")
        layout.operator("psv.offset_arms", text="生成手臂外扩动作")

        layout.separator()
        layout.label(text="Godot Export")
        target = scene.psv_godot_target_armature
        layout.label(text="角色: " + (target.name if target else "未设置"))
        layout.operator("psv.set_godot_target", icon="EYEDROPPER")
        actions = _compatible_actions_for_armature(target) if target else []
        layout.label(text=f"识别动作: {len(actions)} 个")
        layout.prop(scene, "psv_godot_action_name", text="动作")
        layout.prop(scene, "psv_godot_output_dir", text="目录")
        layout.prop(scene, "psv_godot_file_name", text="文件名")
        layout.prop(scene, "psv_godot_auto_action_filename", text="按角色_动作自动命名")
        layout.prop(scene, "psv_godot_keep_tracks", text="保留临时 NLA")
        op = layout.operator("psv.export_godot_glb", text="导出选中动作", icon="EXPORT")
        op.mode = "SELECTED"
        row = layout.row(align=True)
        op = row.operator("psv.export_godot_glb", text="导出当前动作", icon="EXPORT")
        op.mode = "ACTIVE"
        op = row.operator("psv.export_godot_glb", text="导出全部兼容", icon="EXPORT")
        op.mode = "COMPATIBLE"


classes = (
    PSV_OT_set_speed,
    PSV_OT_play_pause,
    PSV_OT_stop,
    PSV_OT_set_fps,
    PSV_OT_set_godot_target,
    PSV_OT_export_godot_glb,
    PSV_OT_force_exact_loop,
    PSV_OT_make_inplace,
    PSV_OT_sparse_to_target_fps,
    PSV_OT_trim_action,
    PSV_OT_offset_arms,
    PSV_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.psv_speed_multiplier = FloatProperty(
        name="Speed Multiplier",
        default=1.0,
        min=0.05,
        max=4.0,
        description="Preview playback speed multiplier",
    )
    bpy.types.Scene.psv_enable_speed = BoolProperty(
        name="Speed Preview Enabled",
        default=False,
        description="Use custom speed preview playback",
    )
    bpy.types.Scene.psv_key_step = IntProperty(
        name="Key Step",
        default=3,
        min=1,
        max=60,
        description="Keep one animation key every N source frames",
    )
    bpy.types.Scene.psv_target_fps = FloatProperty(
        name="Target FPS",
        default=60.0,
        min=1.0,
        max=240.0,
        description="Target scene FPS for the rebuilt sparse action",
    )
    bpy.types.Scene.psv_height_axis = EnumProperty(
        name="Height Axis",
        items=(
            ("X", "X", "Treat X as vertical height"),
            ("Y", "Y", "Treat Y as vertical height"),
            ("Z", "Z", "Treat Z as vertical height"),
        ),
        default="Z",
        description="Axis to preserve when making root motion in-place",
    )
    bpy.types.Scene.psv_key_interpolation = EnumProperty(
        name="Interpolation",
        items=(
            ("BEZIER", "Bezier", "Smooth Blender interpolation"),
            ("LINEAR", "Linear", "Straight interpolation between sparse keys"),
            ("CONSTANT", "Constant", "Hold each sparse key until the next one"),
        ),
        default="BEZIER",
        description="Interpolation mode for generated sparse keys",
    )
    bpy.types.Scene.psv_loop_exact = BoolProperty(
        name="Exact First/Last",
        default=True,
        description="Force the final generated frame to match the first frame",
    )
    bpy.types.Scene.psv_loop_make_inplace = BoolProperty(
        name="Make In-place",
        default=True,
        description="Lock horizontal location curves after rebuilding the action",
    )
    bpy.types.Scene.psv_trim_start_frames = IntProperty(
        name="Trim Start Frames",
        default=0,
        min=0,
        max=1000,
        description="Number of frames to remove from the start of the active action copy",
    )
    bpy.types.Scene.psv_trim_end_frames = IntProperty(
        name="Trim End Frames",
        default=3,
        min=0,
        max=1000,
        description="Number of frames to remove from the end of the active action copy",
    )
    bpy.types.Scene.psv_arm_offset_degrees = FloatProperty(
        name="Arm Offset Degrees",
        default=8.0,
        min=-90.0,
        max=90.0,
        description="Mirrored arm rotation offset in degrees. Use a negative value if the direction is reversed",
    )
    bpy.types.Scene.psv_arm_offset_axis = EnumProperty(
        name="Arm Offset Axis",
        items=(
            ("X", "X", "Offset local X rotation"),
            ("Y", "Y", "Offset local Y rotation"),
            ("Z", "Z", "Offset local Z rotation"),
        ),
        default="Z",
        description="Local rotation axis used for the arm clearance offset",
    )
    bpy.types.Scene.psv_arm_include_shoulders = BoolProperty(
        name="Include Shoulders",
        default=True,
        description="Offset left/right shoulder or clavicle bones",
    )
    bpy.types.Scene.psv_arm_include_upper_arms = BoolProperty(
        name="Include Upper Arms",
        default=True,
        description="Offset left/right upper arm bones",
    )
    bpy.types.Scene.psv_godot_target_armature = PointerProperty(
        name="Godot Export Armature",
        type=bpy.types.Object,
        description="Target character armature for Godot GLB export",
        poll=lambda _self, obj: obj.type == "ARMATURE",
    )
    bpy.types.Scene.psv_godot_output_dir = StringProperty(
        name="Godot Export Folder",
        subtype="DIR_PATH",
        default=r"E:\400-game assets\ai\kimodo\outputs\godot",
        description="Folder for exported Godot GLB files",
    )
    bpy.types.Scene.psv_godot_file_name = StringProperty(
        name="Godot File Name",
        default="",
        description="Output GLB file name. Empty uses the armature name",
    )
    bpy.types.Scene.psv_godot_action_name = EnumProperty(
        name="Godot Action",
        items=_action_enum_items,
        description="Action detected for the current export character",
    )
    bpy.types.Scene.psv_godot_auto_action_filename = BoolProperty(
        name="Auto Action File Name",
        default=True,
        description="When exporting one action, name the GLB as character_action.glb for Godot",
    )
    bpy.types.Scene.psv_godot_keep_tracks = BoolProperty(
        name="Keep Temporary NLA Tracks",
        default=False,
        description="Keep generated temporary NLA tracks after exporting",
    )


def unregister():
    if bpy.app.timers.is_registered(_speed_timer):
        bpy.app.timers.unregister(_speed_timer)

    for attr in (
        "psv_speed_multiplier",
        "psv_enable_speed",
        "psv_key_step",
        "psv_target_fps",
        "psv_height_axis",
        "psv_key_interpolation",
        "psv_loop_exact",
        "psv_loop_make_inplace",
        "psv_trim_start_frames",
        "psv_trim_end_frames",
        "psv_arm_offset_degrees",
        "psv_arm_offset_axis",
        "psv_arm_include_shoulders",
        "psv_arm_include_upper_arms",
        "psv_godot_target_armature",
        "psv_godot_output_dir",
        "psv_godot_file_name",
        "psv_godot_action_name",
        "psv_godot_auto_action_filename",
        "psv_godot_keep_tracks",
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
