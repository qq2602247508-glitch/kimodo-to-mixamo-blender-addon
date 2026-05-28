import bpy

from .main import ToolPanel
from .. import bridge


def _prefs(context):
    addon_name = __package__.split(".")[0]
    addon = context.preferences.addons.get(addon_name)
    return addon.preferences if addon else None


def _is_zh(context):
    prefs = _prefs(context)
    return getattr(prefs, "ui_language", "ZH") == "ZH"


def _t(context, zh, en):
    return zh if _is_zh(context) else en


class BridgePanel(ToolPanel, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_rro_bridge"
    bl_label = "Kimodo 动作桥"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        st = context.scene.rro_bridge

        box = layout.box()
        box.label(text=_t(context, "角色绑定", "Character Binding"))
        row = box.row(align=True)
        row.prop(st, "port", text=_t(context, "接收端口", "Receiver Port"))
        if bridge.is_running():
            row.operator("rro_bridge.stop", text="", icon="PAUSE")
        else:
            row.operator("rro_bridge.start", text="", icon="PLAY")

        box.prop(st, "auto_start", text=_t(context, "自动启动接收器", "Auto Start Receiver"))
        box.prop(st, "target_object", text=_t(context, "Mixamo 目标", "Mixamo Target"))
        box.prop(st, "auto_retarget_on_receive", text=_t(context, "接收后自动绑定", "Auto Bind After Receive"))
        box.prop(st, "bvh_scale", text=_t(context, "BVH 缩放", "BVH Scale"))

        row = box.row(align=True)
        row.operator(
            "rro_bridge.use_rokoko_target",
            text=_t(context, "使用当前 Mixamo 目标", "Use Current Mixamo Target"),
            icon="EYEDROPPER",
        )

        box = layout.box()
        box.label(text=_t(context, "生成动作", "Generate Motion"))

        header = box.row(align=True)
        header.label(text=_t(context, "分段提示词", "Prompt Segments"))
        header.operator("rro_bridge.add_prompt_segment", text="", icon="ADD")

        if len(context.scene.rro_prompt_segments) == 0:
            box.prop(st, "prompt", text=_t(context, "提示词", "Prompt"))
            box.prop(st, "prompt_duration", text=_t(context, "时长", "Duration"))
        else:
            labels = box.row(align=True)
            labels.label(text=_t(context, "开始", "Start"))
            labels.label(text=_t(context, "结束", "End"))
            labels.label(text=_t(context, "提示词", "Prompt"))
            labels.label(text="")

            for index, segment in enumerate(context.scene.rro_prompt_segments):
                row = box.row(align=True)
                row.prop(segment, "start", text="")
                row.prop(segment, "end", text="")
                row.prop(segment, "prompt", text="")
                op = row.operator("rro_bridge.remove_prompt_segment", text="", icon="REMOVE")
                op.index = index

        row = box.row(align=True)
        row.prop(st, "prompt_seed", text="Seed")
        row.prop(st, "prompt_diffusion_steps", text=_t(context, "步数", "Steps"))

        generation_box = box.box()
        generation_box.label(text=_t(context, "生成设置", "Generation Settings"))
        generation_box.prop(st, "loop_style_strength", text=_t(context, "风格化程度", "Style Strength"), slider=True)
        generation_box.prop(st, "use_path_constraint", text=_t(context, "使用路径约束", "Use Path Constraint"))
        generation_box.prop(st, "loop_path_points", text=_t(context, "路径点数量", "Path Points"))
        generation_box.prop(st, "loop_auto_pose", text=_t(context, "自动选择循环帧", "Auto Pick Loop Frame"))
        generation_box.prop(st, "loop_warmup_before_bind", text=_t(context, "循环生成前预热", "Warm Up Loop Generation"))
        generation_box.prop(st, "loop_close_tail", text=_t(context, "强制尾帧闭环", "Force Tail Closure"))
        generation_box.prop(st, "randomize_seed_on_generate", text=_t(context, "随机 Seed", "Randomize Seed"))

        box.operator("rro_bridge.generate_prompt", text=_t(context, "生成并发送 BVH", "Generate and Send BVH"), icon="PLAY")
        box.operator("rro_bridge.one_click_generate_bind", text=_t(context, "一键生成并绑定", "One Click Generate and Bind"), icon="CON_ARMATURE")
        box.operator("rro_bridge.one_click_generate_loop_bind", text=_t(context, "循环生成并绑定", "Generate Loop and Bind"), icon="FILE_REFRESH")
        box.operator("rro_bridge.one_click_bind_last", text=_t(context, "绑定当前 BVH", "Bind Current BVH"), icon="CON_ARMATURE")

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
            layout.label(text=f"{_t(context, '最近源骨架', 'Last source')}: {st.last_source_name}")
        if st.last_bvh_path:
            layout.label(text=f"{_t(context, '最近 BVH', 'Last BVH')}: {st.last_bvh_path}")


class BridgeAdvancedPanel(ToolPanel, bpy.types.Panel):
    bl_idname = "VIEW3D_PT_rro_bridge_advanced"
    bl_label = "Kimodo 高级"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        prefs = _prefs(context)
        return getattr(prefs, "show_advanced_panel", True)

    def draw(self, context):
        layout = self.layout
        st = context.scene.rro_bridge

        box = layout.box()
        box.label(text=_t(context, "本地 Kimodo", "Local Kimodo"))
        box.prop(st, "kimodo_url", text="Kimodo URL")
        box.prop(st, "kimodo_start_script", text=_t(context, "启动脚本", "Start Script"))
        box.prop(st, "kimodo_stop_script", text=_t(context, "停止脚本", "Stop Script"))
        box.prop(st, "kimodo_open_browser_on_start", text=_t(context, "启动后打开 WebUI", "Open WebUI After Start"))
        row = box.row(align=True)
        row.operator("rro_bridge.start_kimodo", text=_t(context, "启动 Kimodo", "Start Kimodo"), icon="URL")
        row.operator("rro_bridge.stop_kimodo", text=_t(context, "关闭端口", "Stop Ports"), icon="CANCEL")

        box = layout.box()
        box.label(text=_t(context, "生成缓存", "Generated Cache"))
        box.prop(st, "cache_output_dir", text=_t(context, "缓存目录", "Cache Directory"))
        box.operator("rro_bridge.clear_generated_cache", text=_t(context, "删除生成缓存文件", "Delete Generated Cache Files"), icon="TRASH")

        box = layout.box()
        box.label(text=_t(context, "调试版本", "Debug Versions"))
        box.prop(st, "loop_send_debug_versions", text=_t(context, "发送并显示调试源骨架", "Send and Show Debug Source Armatures"))

        box = layout.box()
        box.label(text=_t(context, "接收队列", "Receive Queue"))
        box.operator("rro_bridge.process_queue", text=_t(context, "处理待接收 BVH", "Process Pending BVH"), icon="IMPORT")
        box.operator("rro_bridge.clear_queue", text=_t(context, "清空待接收队列", "Clear Pending Queue"), icon="TRASH")

        box = layout.box()
        box.label(text=_t(context, "调试日志", "Debug Log"))
        box.operator("rro_bridge.copy_debug_log", text=_t(context, "复制调试日志", "Copy Debug Log"), icon="COPYDOWN")
        if st.last_status:
            box.label(text=f"Status: {st.last_status}")
        if st.last_debug_json:
            text = st.last_debug_json
            for index in range(0, min(len(text), 900), 95):
                box.label(text=text[index : index + 95])
