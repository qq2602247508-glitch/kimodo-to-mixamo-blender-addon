import bpy

from .main import ToolPanel


class ActionLibraryPanel(ToolPanel, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_rro_action_library"
    bl_label = "Kimodo Action Library"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        st = context.scene.rro_bridge

        box = layout.box()
        box.label(text="Library")
        box.prop(st, "action_library_path")
        box.operator("rro_action_library.refresh", icon="FILE_REFRESH")

        box = layout.box()
        box.label(text="Save Current Action")
        row = box.row(align=True)
        row.prop(st, "character_prefix")
        row.prop(st, "action_category")
        box.prop(st, "action_name")
        box.operator("rro_action_library.save_current", icon="FILE_TICK")

        box = layout.box()
        box.label(text="Actions")
        box.template_list(
            "RRO_UL_ActionLibrary",
            "Action Library",
            context.scene,
            "rro_action_library_items",
            context.scene,
            "rro_action_library_index",
            rows=5,
        )
        box.operator("rro_action_library.load_selected", icon="ACTION")
