import os
import tempfile

import bpy

from bpy.types import Scene, Object
from bpy.props import EnumProperty, BoolProperty, CollectionProperty, PointerProperty, StringProperty

from . import bridge
from .core import animation_lists, retargeting
from .panels import retargeting as retargeting_ui


class RROBridgeSettings(bpy.types.PropertyGroup):
    port: bpy.props.IntProperty(name="接收端口", default=8765, min=1024, max=65535)
    bvh_scale: bpy.props.FloatProperty(name="BVH 缩放", default=1.0, min=0.001, max=1000.0)
    auto_start: bpy.props.BoolProperty(name="自动启动接收器", default=True)
    target_object: bpy.props.PointerProperty(
        name="Mixamo 目标",
        type=bpy.types.Object,
        poll=bridge.poll_target_object,
    )
    auto_retarget_on_receive: bpy.props.BoolProperty(name="接收后自动绑定", default=True)
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
    kimodo_open_browser_on_start: bpy.props.BoolProperty(name="启动后打开 WebUI", default=True)
    cache_output_dir: bpy.props.StringProperty(
        name="生成缓存目录",
        description="Kimodo 过程文件和 BVH 的保存目录。留空则使用系统临时目录。",
        default=os.path.join(tempfile.gettempdir(), "kimodo_blender_bridge"),
        subtype="DIR_PATH",
    )
    prompt: bpy.props.StringProperty(name="提示词", default="A person jumps.")
    prompt_duration: bpy.props.FloatProperty(
        name="时长",
        default=3.0,
        min=1.0,
        max=10.0,
        description="循环动作建议：walk loop 2.0-3.0 秒；run loop 1.2-2.0 秒；idle loop 3.0-5.0 秒；dance loop 3.0-6.0 秒但更难。",
    )
    prompt_seed: bpy.props.IntProperty(name="Seed", default=42)
    prompt_diffusion_steps: bpy.props.IntProperty(name="Steps", default=70, min=2, max=1000)
    loop_style_strength: bpy.props.FloatProperty(
        name="风格化程度",
        description="数值越高越接近提示词风格，数值越低越听从约束。",
        default=5.0,
        min=0.0,
        max=10.0,
    )
    use_path_constraint: bpy.props.BoolProperty(
        name="使用路径约束",
        description="让普通生成沿直线移动。原地动作可以关闭。",
        default=True,
    )
    loop_path_points: bpy.props.IntProperty(
        name="路径点数量",
        description="Kimodo 生成路径约束时使用的直线引导点数量。",
        default=5,
        min=2,
        max=30,
    )
    loop_auto_pose: bpy.props.BoolProperty(
        name="自动选择循环帧",
        description="让 Kimodo 自动选择稳定循环帧，而不是固定使用第 30 帧。",
        default=False,
    )
    loop_send_debug_versions: bpy.props.BoolProperty(
        name="显示调试源骨架",
        description="导入 original/stage1/stage2/loop 等 Kimodo 源骨架用于对比。关闭时只保留绑定结果并隐藏源骨架。",
        default=False,
    )
    loop_warmup_before_bind: bpy.props.BoolProperty(
        name="循环生成前预热",
        description="正式生成前先运行一次不回传的循环生成，减少第一次生成不稳定。",
        default=True,
    )
    loop_close_tail: bpy.props.BoolProperty(
        name="强制尾帧闭环",
        description="强制最后几帧回到第一帧。若尾部重复或扭曲，建议关闭。",
        default=False,
    )
    randomize_seed_on_generate: bpy.props.BoolProperty(
        name="随机 Seed",
        description="每次生成使用不同 seed，避免固定 seed 重复同一个坏结果。",
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
