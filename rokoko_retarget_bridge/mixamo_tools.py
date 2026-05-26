import math

import bpy
from mathutils import Matrix, Vector


KEY_TO_MIXAMO_BONE = {
    "leftShoulder": "LeftShoulder",
    "leftUpperArm": "LeftArm",
    "leftLowerArm": "LeftForeArm",
    "leftHand": "LeftHand",
    "rightShoulder": "RightShoulder",
    "rightUpperArm": "RightArm",
    "rightLowerArm": "RightForeArm",
    "rightHand": "RightHand",
    "leftUpperLeg": "LeftUpLeg",
    "leftLowerLeg": "LeftLeg",
    "leftFoot": "LeftFoot",
    "leftToe": "LeftToeBase",
    "rightUpperLeg": "RightUpLeg",
    "rightLowerLeg": "RightLeg",
    "rightFoot": "RightFoot",
    "rightToe": "RightToeBase",
}


def _clean_name(name):
    return name.split(":")[-1].lower().replace("_", "").replace(" ", "")


def _find_bone(armature, candidates):
    wanted = {_clean_name(name) for name in candidates}
    for bone in armature.data.bones:
        if _clean_name(bone.name) in wanted:
            return bone
    return None


def _world_pos(obj, value):
    return obj.matrix_world @ value


def _axis_name(vec):
    axes = [
        ("+X", Vector((1, 0, 0))),
        ("-X", Vector((-1, 0, 0))),
        ("+Y", Vector((0, 1, 0))),
        ("-Y", Vector((0, -1, 0))),
        ("+Z", Vector((0, 0, 1))),
        ("-Z", Vector((0, 0, -1))),
    ]
    return max(axes, key=lambda item: vec.dot(item[1]))[0]


def analyze_target_axis(armature):
    hips = _find_bone(armature, ["Hips"])
    neck = _find_bone(armature, ["Neck", "Head"])
    left = _find_bone(armature, ["LeftShoulder", "LeftArm"])
    right = _find_bone(armature, ["RightShoulder", "RightArm"])
    if not (hips and neck and left and right):
        return {
            "ok": False,
            "status": "Cannot inspect axis: missing Hips/Neck/Shoulder bones",
            "fix_degrees_z": 0.0,
        }

    up = (_world_pos(armature, neck.head_local) - _world_pos(armature, hips.head_local)).normalized()
    side = (_world_pos(armature, left.head_local) - _world_pos(armature, right.head_local)).normalized()
    forward = side.cross(up).normalized()
    forward_axis = _axis_name(forward)
    side_axis = _axis_name(side)
    up_axis = _axis_name(up)

    ok = up_axis == "+Z" and side_axis == "+X" and forward_axis == "-Y"
    fix_degrees_z = 0.0
    if up_axis == "+Z" and side_axis == "+Y" and forward_axis == "+X":
        fix_degrees_z = -90.0
    elif up_axis == "+Z" and side_axis == "-Y" and forward_axis == "-X":
        fix_degrees_z = 90.0
    elif up_axis == "+Z" and side_axis == "-X" and forward_axis == "+Y":
        fix_degrees_z = 180.0

    status = (
        "Mixamo axis OK: faces -Y, shoulders on X"
        if ok
        else f"Axis mismatch: up {up_axis}, shoulders {side_axis}, faces {forward_axis}"
    )
    if fix_degrees_z:
        status += f"; suggested fix: rotate root {fix_degrees_z:g} deg around Z"

    return {
        "ok": ok,
        "status": status,
        "fix_degrees_z": fix_degrees_z,
        "up_axis": up_axis,
        "side_axis": side_axis,
        "forward_axis": forward_axis,
    }


def _root_objects_for_armature(armature):
    roots = set()
    for obj in bpy.data.objects:
        uses_armature = obj == armature
        if obj.type == "MESH":
            if obj.parent == armature:
                uses_armature = True
            for modifier in obj.modifiers:
                if modifier.type == "ARMATURE" and modifier.object == armature:
                    uses_armature = True
        if uses_armature:
            root = obj
            while root.parent is not None and root.parent != armature:
                root = root.parent
            roots.add(root)
    roots.add(armature)
    return [obj for obj in roots if obj.parent is None or obj.parent not in roots]


def fix_target_axis(armature, degrees_z=None):
    analysis = analyze_target_axis(armature)
    degrees = analysis["fix_degrees_z"] if degrees_z is None else float(degrees_z)
    if abs(degrees) < 0.001:
        return analysis | {"fixed": False}

    rot = Matrix.Rotation(math.radians(degrees), 4, "Z")
    for obj in _root_objects_for_armature(armature):
        obj.matrix_world = rot @ obj.matrix_world
    bpy.context.view_layer.update()
    after = analyze_target_axis(armature)
    return after | {"fixed": True, "applied_degrees_z": degrees}


def force_mixamo_bone_map(scene):
    target = scene.rsl_retargeting_armature_target
    if target is None:
        return 0

    target_names = {_clean_name(bone.name): bone.name for bone in target.pose.bones}
    changed = 0
    for item in scene.rsl_retargeting_bone_list:
        wanted = KEY_TO_MIXAMO_BONE.get(item.bone_name_key)
        if not wanted:
            continue
        actual = target_names.get(_clean_name(wanted))
        if actual and item.bone_name_target != actual:
            item.bone_name_target = actual
            changed += 1
    return changed
