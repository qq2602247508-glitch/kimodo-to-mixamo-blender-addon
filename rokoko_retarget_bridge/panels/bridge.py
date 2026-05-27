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
        row = box.row(align=True)
        row.operator("rro_bridge.start_kimodo", icon="URL")
        row.operator("rro_bridge.stop_kimodo", icon="CANCEL")

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

        generation_box = box.box()
        generation_box.label(text="Generation Settings")
        generation_box.prop(st, "loop_style_strength", text="Style Strength", slider=True)
        generation_box.prop(st, "loop_path_points", text="Path Points")
        generation_box.prop(st, "loop_auto_pose")
        generation_box.prop(st, "loop_send_debug_versions")

        box.operator("rro_bridge.generate_prompt", icon="PLAY")
        box.operator("rro_bridge.one_click_generate_bind", icon="CON_ARMATURE")
        box.operator("rro_bridge.one_click_generate_loop_bind", icon="FILE_REFRESH")
        box.operator("rro_bridge.one_click_bind_last", icon="CON_ARMATURE")
        box.operator("rro_bridge.process_queue", icon="IMPORT")
        box.operator("rro_bridge.clear_queue", icon="TRASH")

        if st.last_status:
            box = layout.box()
            box.label(text=st.last_status)
            if st.last_request_id:
                box.label(text=f"Request: {st.last_request_id}")
            if st.last_received_request_id:
                box.label(text=f"Received: {st.last_received_request_id}")
            if st.last_completed_request_id:
                box.label(text=f"Completed: {st.last_completed_request_id}")
        if st.last_source_name:
            layout.label(text=f"Last source: {st.last_source_name}")
        if st.last_bvh_path:
            layout.label(text=f"Last BVH: {st.last_bvh_path}")


class BridgeAdvancedPanel(ToolPanel, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_rro_bridge_advanced"
    bl_label = "Kimodo Advanced"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        st = context.scene.rro_bridge

        box = layout.box()
        box.label(text="Local Kimodo")
        box.prop(st, "kimodo_url")
        box.prop(st, "kimodo_start_script")
        box.prop(st, "kimodo_stop_script")
        box.prop(st, "kimodo_open_browser_on_start")

        box = layout.box()
        box.label(text="Debug Log")
        box.operator("rro_bridge.copy_debug_log", icon="COPYDOWN")
        if st.last_status:
            box.label(text=f"Status: {st.last_status}")
        if st.last_debug_json:
            text = st.last_debug_json
            for index in range(0, min(len(text), 900), 95):
                box.label(text=text[index : index + 95])
