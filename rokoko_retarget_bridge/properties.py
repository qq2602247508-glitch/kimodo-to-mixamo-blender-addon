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
    kimodo_url: bpy.props.StringProperty(name="Kimodo URL", default="http://127.0.0.1:7870")
    kimodo_start_script: bpy.props.StringProperty(
        name="Start Script",
        default=r"E:\400-game assets\ai\kimodo\scripts\start_kimodo_demo_local_llama_logged.ps1",
        subtype="FILE_PATH",
    )
    kimodo_stop_script: bpy.props.StringProperty(
        name="Stop Script",
        default=r"E:\400-game assets\ai\kimodo\scripts\stop_kimodo_ports.ps1",
        subtype="FILE_PATH",
    )
    kimodo_open_browser_on_start: bpy.props.BoolProperty(name="Open WebUI After Start", default=True)
    prompt: bpy.props.StringProperty(name="Prompt", default="A person jumps.")
    prompt_duration: bpy.props.FloatProperty(name="Duration", default=4.0, min=1.0, max=10.0)
    prompt_seed: bpy.props.IntProperty(name="Seed", default=42)
    prompt_diffusion_steps: bpy.props.IntProperty(name="Steps", default=70, min=2, max=1000)
    loop_style_strength: bpy.props.FloatProperty(
        name="Style Strength",
        description="Higher values keep more of the prompt style while Kimodo builds the motion",
        default=5.0,
        min=0.0,
        max=10.0,
    )
    use_path_constraint: bpy.props.BoolProperty(
        name="Use Path Constraint",
        description="Constrain normal generation to move along a straight path. Turn this off for in-place actions.",
        default=True,
    )
    loop_path_points: bpy.props.IntProperty(
        name="Path Points",
        description="How many straight-path guide points Kimodo should use for loop generation",
        default=5,
        min=2,
        max=30,
    )
    loop_auto_pose: bpy.props.BoolProperty(
        name="Auto Pose Frame",
        description="Let Kimodo choose a stable loop pose frame instead of using frame 30",
        default=False,
    )
    loop_send_debug_versions: bpy.props.BoolProperty(
        name="Send Debug Versions",
        description="Also import original, stage1 straight, and stage2 moving BVHs for comparison",
        default=False,
    )
    last_status: bpy.props.StringProperty(name="Status", default="")
    last_debug_json: bpy.props.StringProperty(name="Debug", default="")
    last_bvh_path: bpy.props.StringProperty(name="Last BVH Path", default="")
    last_source_name: bpy.props.StringProperty(name="Last Source", default="")
    last_request_id: bpy.props.StringProperty(name="Last Request ID", default="")
    last_received_request_id: bpy.props.StringProperty(name="Last Received Request ID", default="")
    last_completed_request_id: bpy.props.StringProperty(name="Last Completed Request ID", default="")


class RROPromptSegment(bpy.types.PropertyGroup):
    start: bpy.props.FloatProperty(name="Start", default=0.0, min=0.0, max=60.0)
    end: bpy.props.FloatProperty(name="End", default=4.0, min=0.1, max=60.0)
    prompt: bpy.props.StringProperty(name="Prompt", default="A person jumps.")


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
    Scene.rro_prompt_segments = CollectionProperty(type=RROPromptSegment)
    Scene.rro_prompt_segment_index = EnumSafeIntProperty()

    for bone in animation_lists.get_bones().keys():
        setattr(Object, "rsl_actor_" + bone, StringProperty(name=bone))


def EnumSafeIntProperty():
    from bpy.props import IntProperty

    return IntProperty(name="Index for the retargeting bone list", default=0)
