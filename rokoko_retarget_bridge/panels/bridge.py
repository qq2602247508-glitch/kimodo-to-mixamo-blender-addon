import bpy

from .main import ToolPanel
from .. import bridge


class BridgePanel(ToolPanel, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_rro_bridge"
    bl_label = "Kimodo Bridge"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        st = context.scene.rro_bridge

        box = layout.box()
        box.label(text="Receiver")
        row = layout.row(align=True)
        row.prop(st, "port")
        if bridge.is_running():
            row.operator("rro_bridge.stop", text="", icon="PAUSE")
        else:
            row.operator("rro_bridge.start", text="", icon="PLAY")

        box.prop(st, "auto_start")
        box.prop(st, "target_object")
        box.prop(st, "auto_retarget_on_receive")
        box.prop(st, "delete_source_after_retarget")
        box.prop(st, "bvh_scale")

        row = box.row(align=True)
        row.operator("rro_bridge.use_rokoko_target", icon="EYEDROPPER")

        box = layout.box()
        box.label(text="Kimodo Prompt")
        box.prop(st, "kimodo_url")
        box.prop(st, "kimodo_start_script")
        box.operator("rro_bridge.start_kimodo", icon="URL")
        box.prop(st, "prompt")
        row = box.row(align=True)
        row.prop(st, "prompt_duration")
        row.prop(st, "prompt_seed")
        box.prop(st, "prompt_diffusion_steps")
        box.operator("rro_bridge.generate_prompt", icon="PLAY")
        box.operator("rro_bridge.one_click_generate_bind", icon="AUTO")
        box.operator("rro_bridge.one_click_bind_last", icon="CON_ARMATURE")

        if st.last_status:
            box = layout.box()
            box.label(text=st.last_status)
        if st.last_source_name:
            layout.label(text=f"Last source: {st.last_source_name}")
        if st.last_bvh_path:
            layout.label(text=f"Last BVH: {st.last_bvh_path}")
