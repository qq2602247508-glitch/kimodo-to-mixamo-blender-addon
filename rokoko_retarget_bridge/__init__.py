bl_info = {
    "name": "Rokoko Retarget Bridge",
    "author": "Rokoko Electronics ApS, trimmed by Codex",
    "category": "Animation",
    "location": "View 3D > Sidebar > Rokoko",
    "description": "Original Rokoko retargeting UI with Kimodo BVH Bridge, without login or cloud features.",
    "version": (1, 4, 7, 0),
    "blender": (2, 80, 0),
}

import bpy
import sys

from . import bridge
from . import core
from . import properties
from .operators.action_library import (
    ActionLibraryApplySelectedToCharacter,
    ActionLibraryLoadCharacterSelected,
    ActionLibraryLoadSelected,
    ActionLibraryRefresh,
    ActionLibrarySaveCurrent,
    RRO_UL_ActionLibrary,
)
from .operators.bridge import (
    BridgeGeneratePrompt,
    BridgeOneClickBindLast,
    BridgeOneClickGenerateBind,
    BridgeStart,
    BridgeStartKimodo,
    BridgeStop,
    BridgeUseRokokoTarget,
)
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
from .panels.bridge import BridgePanel
from .panels.action_library import ActionLibraryPanel, CurrentCharacterActionsPanel
from .panels.retargeting import BoneListItem, RetargetingPanel, RSL_UL_BoneList


absolute_min_ver = (2, 80, 75)


class RokokoRetargetBridgePreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    action_library_path: bpy.props.StringProperty(
        name="Action Library",
        description="External folder used by Current Character Actions and Action Library",
        default=r"E:\400-game assets\ai\kimodo\action_library",
        subtype="DIR_PATH",
    )

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "action_library_path")


classes = [
    RokokoRetargetBridgePreferences,
    RetargetingPanel,
    BridgePanel,
    CurrentCharacterActionsPanel,
    ActionLibraryPanel,
    RSL_UL_BoneList,
    RRO_UL_ActionLibrary,
    BoneListItem,
    properties.RROActionLibraryItem,
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
    BridgeOneClickGenerateBind,
    BridgeOneClickBindLast,
    BridgeStartKimodo,
    ActionLibraryRefresh,
    ActionLibrarySaveCurrent,
    ActionLibraryApplySelectedToCharacter,
    ActionLibraryLoadCharacterSelected,
    ActionLibraryLoadSelected,
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
        "rro_action_library_items",
        "rro_action_library_index",
        "rro_character_action_items",
        "rro_character_action_index",
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
