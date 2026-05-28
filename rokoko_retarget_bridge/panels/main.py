class ToolPanel(object):
    bl_label = "Kimodo 动作"
    bl_idname = "VIEW3D_TS_rokoko"
    bl_category = "Kimodo 动作"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"


def separator(layout, scale=1):
    row = layout.row(align=True)
    row.scale_y = scale
    row.label(text="")
