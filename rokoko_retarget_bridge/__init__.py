bl_info = {
    "name": "Kimodo 动作桥",
    "author": "Rokoko Electronics ApS, trimmed by Codex",
    "category": "Animation",
    "location": "View 3D > Sidebar > Kimodo 动作",
    "description": "Kimodo 生成动作并绑定到 Mixamo 角色的本地工具。",
    "version": (1, 4, 3, 33),
    "blender": (2, 80, 0),
}

import bpy
import sys

from . import bridge
from . import core
from . import properties
from .operators.bridge import (
    BridgeGeneratePrompt,
    BridgeClearGeneratedCache,
    BridgeClearQueue,
    BridgeCopyDebugLog,
    BridgeProcessQueue,
    BridgeOneClickBindLast,
    BridgeOneClickGenerateBind,
    BridgeOneClickGenerateLoopBind,
    BridgeStart,
    BridgeStartKimodo,
    BridgeStop,
    BridgeStopKimodo,
    BridgeUseRokokoTarget,
)
from .operators.prompt_segments import AddPromptSegment, RemovePromptSegment, RRO_UL_PromptSegments
from .operators.detector import ClearCustomBones, ExportCustomBones, ImportCustomBones, SaveCustomBonesRetargeting
from .operators.retargeting import (
    AddBoneListItem,
    BuildBoneList,
    CheckMixamoTargetAxis,
    ClearBoneList,
    FixMixamoBoneMap,
    FixMixamoTargetAxis,
    RetargetAnimation,
)
from .panels.bridge import BridgeAdvancedPanel, BridgePanel
from .panels.retargeting import BoneListItem, RetargetingPanel, RSL_UL_BoneList


absolute_min_ver = (2, 80, 75)


class KimodoBridgePreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    ui_language: bpy.props.EnumProperty(
        name="界面语言 / UI Language",
        items=[
            ("ZH", "中文", "使用中文界面"),
            ("EN", "English", "Use English UI"),
        ],
        default="ZH",
    )
    show_advanced_panel: bpy.props.BoolProperty(
        name="显示高级面板 / Show Advanced Panel",
        description="在 3D 视图侧栏显示 Kimodo 高级面板",
        default=True,
    )

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "ui_language")
        layout.prop(self, "show_advanced_panel")


classes = [
    KimodoBridgePreferences,
    RetargetingPanel,
    BridgePanel,
    BridgeAdvancedPanel,
    RSL_UL_BoneList,
    RRO_UL_PromptSegments,
    BoneListItem,
    properties.RROPromptSegment,
    properties.RROBridgeSettings,
    BuildBoneList,
    AddBoneListItem,
    ClearBoneList,
    FixMixamoBoneMap,
    CheckMixamoTargetAxis,
    FixMixamoTargetAxis,
    RetargetAnimation,
    SaveCustomBonesRetargeting,
    ImportCustomBones,
    ExportCustomBones,
    ClearCustomBones,
    BridgeStart,
    BridgeStop,
    BridgeUseRokokoTarget,
    BridgeGeneratePrompt,
    BridgeClearGeneratedCache,
    BridgeClearQueue,
    BridgeCopyDebugLog,
    BridgeProcessQueue,
    BridgeOneClickGenerateBind,
    BridgeOneClickGenerateLoopBind,
    BridgeOneClickBindLast,
    BridgeStartKimodo,
    BridgeStopKimodo,
    AddPromptSegment,
    RemovePromptSegment,
]


def check_unsupported_blender_versions():
    if bpy.app.version < absolute_min_ver:
        unregister()
        sys.tracebacklimit = 0
        raise ImportError(
            "\n\nBlender versions older than 2.80 are not supported by Rokoko Retarget Bridge."
            "\nPlease use Blender 2.80 or later.\n"
        )


def register_classes():
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            print("Rokoko Retarget Bridge: skipped already registered class", cls.__name__)


def register():
    print("\n### Loading Rokoko Retarget Bridge...")
    check_unsupported_blender_versions()
    register_classes()
    properties.register()
    core.icon_manager.load_icons()
    core.detection_manager.load_detection_lists()
    bpy.app.timers.register(bridge.maybe_auto_start, first_interval=0.5)
    print("### Loaded Rokoko Retarget Bridge successfully!\n")


def unregister():
    print("### Unloading Rokoko Retarget Bridge...")
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    try:
        bridge.stop_server()
    except Exception:
        pass
    for attr in (
        "rsl_retargeting_armature_source",
        "rsl_retargeting_armature_target",
        "rsl_retargeting_auto_scaling",
        "rsl_retargeting_use_pose",
        "rsl_retargeting_bone_list",
        "rsl_retargeting_bone_list_index",
        "rro_prompt_segments",
        "rro_prompt_segment_index",
        "rro_bridge",
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)
    try:
        core.icon_manager.unload_icons()
    except Exception:
        pass
    print("### Unloaded Rokoko Retarget Bridge successfully!\n")


if __name__ == "__main__":
    register()
