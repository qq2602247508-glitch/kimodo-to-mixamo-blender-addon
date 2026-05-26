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
        row = box.row(align=True)
        row.prop(st, "port")
        if bridge.is_running():
            row.operator("rro_bridge.stop", text="", icon="PAUSE")
        else:
            row.operator("rro_bridge.start", text="", icon="PLAY")

        box.prop(st, "auto_start")
        box.prop(st, "target_object")
        box.prop(st, "auto_retarget_on_receive")
        box.prop(st, "bvh_scale")

        row = box.row(align=True)
        row.operator("rro_bridge.use_rokoko_target", icon="EYEDROPPER")

        box = layout.box()
        box.label(text="Kimodo Prompt")
        box.prop(st, "kimodo_url")
        box.prop(st, "kimodo_start_script")
        box.operator("rro_bridge.start_kimodo", icon="URL")

        header = box.row(align=True)
        header.label(text="Timeline Prompt Segments")
        header.operator("rro_bridge.add_prompt_segment", text="", icon="ADD")

        if len(context.scene.rro_prompt_segments) == 0:
            box.prop(st, "prompt")
            box.prop(st, "prompt_duration")
        else:
            labels = box.row(align=True)
            labels.label(text="Start")
            labels.label(text="End")
            labels.label(text="Prompt")
            labels.label(text="")

            for index, segment in enumerate(context.scene.rro_prompt_segments):
                row = box.row(align=True)
                row.prop(segment, "start", text="")
                row.prop(segment, "end", text="")
                row.prop(segment, "prompt", text="")
                op = row.operator("rro_bridge.remove_prompt_segment", text="", icon="REMOVE")
                op.index = index

        row = box.row(align=True)
        row.prop(st, "prompt_seed")
        row.prop(st, "prompt_diffusion_steps")
        box.operator("rro_bridge.generate_prompt", icon="PLAY")
        box.operator("rro_bridge.one_click_generate_bind", icon="CON_ARMATURE")
        box.operator("rro_bridge.one_click_bind_last", icon="CON_ARMATURE")

        if st.last_status:
            box = layout.box()
            box.label(text=st.last_status)
        if st.last_source_name:
            layout.label(text=f"Last source: {st.last_source_name}")
        if st.last_bvh_path:
            layout.label(text=f"Last BVH: {st.last_bvh_path}")
