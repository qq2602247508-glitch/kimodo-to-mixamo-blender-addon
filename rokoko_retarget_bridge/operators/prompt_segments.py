import bpy


def ensure_default_segment(scene):
    if len(scene.rro_prompt_segments) == 0:
        item = scene.rro_prompt_segments.add()
        item.start = 0.0
        item.end = scene.rro_bridge.prompt_duration
        item.prompt = scene.rro_bridge.prompt


class AddPromptSegment(bpy.types.Operator):
    bl_idname = "rro_bridge.add_prompt_segment"
    bl_label = "Add Prompt Segment"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ensure_default_segment(context.scene)
        last = context.scene.rro_prompt_segments[-1]
        item = context.scene.rro_prompt_segments.add()
        item.start = last.end
        item.end = last.end + max(1.0, last.end - last.start)
        item.prompt = ""
        context.scene.rro_prompt_segment_index = len(context.scene.rro_prompt_segments) - 1
        return {"FINISHED"}


class RemovePromptSegment(bpy.types.Operator):
    bl_idname = "rro_bridge.remove_prompt_segment"
    bl_label = "Remove Prompt Segment"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        ensure_default_segment(context.scene)
        index = self.index if self.index >= 0 else context.scene.rro_prompt_segment_index
        if len(context.scene.rro_prompt_segments) <= 1:
            context.scene.rro_prompt_segments[0].prompt = context.scene.rro_bridge.prompt
            context.scene.rro_prompt_segments[0].start = 0.0
            context.scene.rro_prompt_segments[0].end = context.scene.rro_bridge.prompt_duration
            return {"FINISHED"}
        index = max(0, min(index, len(context.scene.rro_prompt_segments) - 1))
        context.scene.rro_prompt_segments.remove(index)
        context.scene.rro_prompt_segment_index = min(index, len(context.scene.rro_prompt_segments) - 1)
        return {"FINISHED"}


class RRO_UL_PromptSegments(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        row.prop(item, "start", text="")
        row.prop(item, "end", text="")
        row.prop(item, "prompt", text="")
