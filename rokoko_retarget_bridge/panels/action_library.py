import bpy

from .main import ToolPanel


def _addon_preferences(context):
    addon = context.preferences.addons.get(__package__.split(".")[0])
    return addon.preferences if addon else None


class CurrentCharacterActionsPanel(ToolPanel, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_rro_current_character_actions"
    bl_label = "Current Model Action Library"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        st = context.scene.rro_bridge
        prefs = _addon_preferences(context)

        box = layout.box()
        box.label(text="Current Model")
        box.prop(st, "target_object")
        box.prop(st, "character_prefix")

        if prefs:
            box.prop(prefs, "action_library_path")

        box = layout.box()
        box.label(text="Current Model Actions")
        row = box.row(align=True)
        row.prop(st, "action_category")
        row.prop(st, "action_name")
        box.operator("rro_action_library.save_current", text="Send Current Action to Resource Library", icon="FILE_TICK")

        box = layout.box()
        row = box.row(align=True)
        row.label(text="Current Model Library")
        row.operator("rro_action_library.refresh", text="", icon="FILE_REFRESH")
        box.template_list(
            "RRO_UL_ActionLibrary",
            "Character Actions",
            context.scene,
            "rro_character_action_items",
            context.scene,
            "rro_character_action_index",
            rows=5,
        )
        row = box.row(align=True)
        row.operator("rro_action_library.load_character_selected", text="Show Selected Action", icon="ACTION")
        row.operator("rro_action_library.retarget_character_selected", text="Retarget Selected", icon="CON_ARMATURE")


class ActionLibraryPanel(ToolPanel, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_rro_action_library"
    bl_label = "Resource Action Library"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        prefs = _addon_preferences(context)

        box = layout.box()
        box.label(text="Resource Library")
        if prefs:
            box.prop(prefs, "action_library_path")
        box.operator("rro_action_library.refresh", icon="FILE_REFRESH")

        box = layout.box()
        box.label(text="Resource Actions")
        box.template_list(
            "RRO_UL_ActionLibrary",
            "Action Library",
            context.scene,
            "rro_action_library_items",
            context.scene,
            "rro_action_library_index",
            rows=5,
        )
        row = box.row(align=True)
        row.operator("rro_action_library.send_selected_to_character", text="Send to Current Model", icon="FILE_TICK")
        row.operator("rro_action_library.delete_selected", text="Delete", icon="TRASH")
