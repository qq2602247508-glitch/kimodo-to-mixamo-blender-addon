import bpy

from bpy.types import Scene, Object
from bpy.props import EnumProperty, BoolProperty, CollectionProperty, PointerProperty, StringProperty

from . import bridge
from .core import animation_lists, retargeting
from .panels import retargeting as retargeting_ui


class RROBridgeSettings(bpy.types.PropertyGroup):
    port: bpy.props.IntProperty(name="Port", default=8765, min=1024, max=65535)
    bvh_scale: bpy.props.FloatProperty(name="BVH Scale", default=1.0, min=0.001, max=1000.0)
    auto_start: bpy.props.BoolProperty(name="Auto Start", default=True)
    target_object: bpy.props.PointerProperty(
        name="Mixamo Target",
        type=bpy.types.Object,
        poll=bridge.poll_target_object,
    )
    auto_retarget_on_receive: bpy.props.BoolProperty(name="Auto Retarget on Receive", default=True)
    delete_source_after_retarget: bpy.props.BoolProperty(
        name="Delete Source After Retarget",
        description="Remove imported BVH/library source armatures after a successful retarget",
        default=True,
    )
    kimodo_url: bpy.props.StringProperty(name="Kimodo URL", default="http://127.0.0.1:7870")
    kimodo_start_script: bpy.props.StringProperty(
        name="Start Script",
        default=r"E:\400-game assets\ai\kimodo\scripts\start_kimodo_demo_local_llama_logged.ps1",
        subtype="FILE_PATH",
    )
    prompt: bpy.props.StringProperty(name="Prompt", default="A person jumps.")
    prompt_duration: bpy.props.FloatProperty(name="Duration", default=6.0, min=1.0, max=10.0)
    prompt_seed: bpy.props.IntProperty(name="Seed", default=42)
    prompt_diffusion_steps: bpy.props.IntProperty(name="Steps", default=100, min=2, max=1000)
    last_status: bpy.props.StringProperty(name="Status", default="")
    last_bvh_path: bpy.props.StringProperty(name="Last BVH Path", default="")
    last_source_name: bpy.props.StringProperty(name="Last Source", default="")
    action_library_path: bpy.props.StringProperty(
        name="Action Library",
        default=r"E:\400-game assets\ai\kimodo\action_library",
        subtype="DIR_PATH",
    )
    action_name: bpy.props.StringProperty(name="Action Name", default="idle")
    character_prefix: bpy.props.StringProperty(
        name="Character ID",
        description="Leave empty to use the selected Mixamo Target name",
        default="",
    )
    action_category: bpy.props.StringProperty(name="Category", default="general")
    show_all_library_actions: bpy.props.BoolProperty(name="Show All Actions", default=False)
    selected_library_action: bpy.props.StringProperty(name="Library Action", default="")


class RROActionLibraryItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty(name="Name", default="")
    character_prefix: bpy.props.StringProperty(name="Character", default="")
    category: bpy.props.StringProperty(name="Category", default="")
    path: bpy.props.StringProperty(name="Path", default="")
    meta_path: bpy.props.StringProperty(name="Meta Path", default="")


def register():
    Scene.rsl_retargeting_armature_source = PointerProperty(
        name="Source",
        description="Select the armature with the animation that you want to retarget",
        type=Object,
        poll=retargeting.poll_source_armatures,
        update=retargeting.clear_bone_list,
    )
    Scene.rsl_retargeting_armature_target = PointerProperty(
        name="Target",
        description="Select the armature that should receive the animation",
        type=Object,
        poll=retargeting.poll_target_armatures,
        update=retargeting.clear_bone_list,
    )
    Scene.rsl_retargeting_auto_scaling = BoolProperty(
        name="Auto Scale",
        description=(
            "This will scale the source armature to fit the height of the target armature."
            "\nBoth armatures have to be in T-pose for this to work correctly"
        ),
        default=True,
    )
    Scene.rsl_retargeting_use_pose = EnumProperty(
        name="Use Pose",
        description=(
            "Select which pose of the source and target armature to use to retarget the animation."
            "\nBoth armatures should be in the same pose before retargeting"
        ),
        items=[
            ("REST", "Rest", "Select this to use the rest pose during retargeting."),
            ("CURRENT", "Current", "Select this to use the current pose during retargeting."),
        ],
    )
    Scene.rsl_retargeting_bone_list = CollectionProperty(type=retargeting_ui.BoneListItem)
    Scene.rsl_retargeting_bone_list_index = EnumSafeIntProperty()
    Scene.rro_bridge = PointerProperty(type=RROBridgeSettings)
    Scene.rro_action_library_items = CollectionProperty(type=RROActionLibraryItem)
    Scene.rro_action_library_index = EnumSafeIntProperty()
    Scene.rro_character_action_items = CollectionProperty(type=RROActionLibraryItem)
    Scene.rro_character_action_index = EnumSafeIntProperty()

    for bone in animation_lists.get_bones().keys():
        setattr(Object, "rsl_actor_" + bone, StringProperty(name=bone))


def EnumSafeIntProperty():
    from bpy.props import IntProperty

    return IntProperty(name="Index for the retargeting bone list", default=0)
