import bpy
import json
import subprocess
import urllib.request

from .. import bridge


def prompt_payload(context):
    st = context.scene.rro_bridge
    segments = []
    for item in context.scene.rro_prompt_segments:
        prompt = item.prompt.strip()
        if not prompt:
            continue
        segments.append({"start": item.start, "end": item.end, "prompt": prompt})

    if segments:
        segments.sort(key=lambda item: item["start"])
        last_end = None
        for index, segment in enumerate(segments):
            if segment["end"] <= segment["start"]:
                raise ValueError(f"Prompt segment {index + 1}: end time must be greater than start time.")
            if last_end is not None and segment["start"] < last_end:
                raise ValueError(f"Prompt segment {index + 1}: start time overlaps the previous segment.")
            last_end = segment["end"]
        return {
            "prompt": segments[0]["prompt"],
            "duration": max(segment["end"] for segment in segments),
            "segments": segments,
            "seed": st.prompt_seed,
            "diffusion_steps": st.prompt_diffusion_steps,
            "blender_url": f"http://127.0.0.1:{st.port}",
        }

    return {
        "prompt": st.prompt,
        "duration": st.prompt_duration,
        "seed": st.prompt_seed,
        "diffusion_steps": st.prompt_diffusion_steps,
        "blender_url": f"http://127.0.0.1:{st.port}",
    }


class BridgeStart(bpy.types.Operator):
    bl_idname = "rro_bridge.start"
    bl_label = "Start Bridge"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            bridge.start_server(context.scene.rro_bridge.port)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class BridgeStop(bpy.types.Operator):
    bl_idname = "rro_bridge.stop"
    bl_label = "Stop Bridge"
    bl_options = {"REGISTER"}

    def execute(self, _context):
        bridge.stop_server()
        return {"FINISHED"}


class BridgeUseRokokoTarget(bpy.types.Operator):
    bl_idname = "rro_bridge.use_rokoko_target"
    bl_label = "Use Rokoko Target"
    bl_description = "Use the current Rokoko Retargeting target as the Bridge Mixamo target"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = context.scene.rsl_retargeting_armature_target
        if target is None:
            self.report({"ERROR"}, "Choose a target in the Rokoko Retargeting panel first")
            return {"CANCELLED"}
        context.scene.rro_bridge.target_object = target
        self.report({"INFO"}, f"Bridge target set to {target.name}")
        return {"FINISHED"}


class BridgeGeneratePrompt(bpy.types.Operator):
    bl_idname = "rro_bridge.generate_prompt"
    bl_label = "Generate and Send BVH"
    bl_description = "Send the prompt to local Kimodo, then receive the generated standard T-pose BVH without retargeting"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = context.scene.rro_bridge
        previous_auto_retarget = st.auto_retarget_on_receive
        st.auto_retarget_on_receive = False
        if not bridge.is_running():
            try:
                bridge.start_server(st.port)
            except Exception as exc:
                st.auto_retarget_on_receive = previous_auto_retarget
                self.report({"ERROR"}, f"Could not start receiver: {exc}")
                return {"CANCELLED"}

        try:
            payload = prompt_payload(context)
            st.last_status = "Sending prompt to Kimodo..."
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                st.kimodo_url.rstrip("/") + "/kimodo-bridge/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=900) as resp:
                result = json.loads(resp.read().decode("utf-8") or "{}")
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "Kimodo generation failed")
            st.last_status = f"Generated and sent BVH: {result.get('path', '')}"
            self.report({"INFO"}, "Kimodo motion generated and sent as BVH")
        except Exception as exc:
            st.auto_retarget_on_receive = previous_auto_retarget
            message = str(exc)
            if "WinError 10061" in message or "actively refused" in message:
                message = "Kimodo is not listening on 7870 yet. Start Kimodo and wait until WebUI opens."
            st.last_status = f"Error: {message}"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        st.auto_retarget_on_receive = previous_auto_retarget
        return {"FINISHED"}


class BridgeOneClickGenerateBind(bpy.types.Operator):
    bl_idname = "rro_bridge.one_click_generate_bind"
    bl_label = "One Click Generate + Bind"
    bl_description = "Generate a Kimodo BVH, auto-fix the target if needed, rebuild bones, and retarget"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = context.scene.rro_bridge
        target = bridge._armature_from_object(st.target_object) or context.scene.rsl_retargeting_armature_target
        if target is None:
            message = "Please select a Mixamo Target first, then try again."
            st.last_status = message
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        st.target_object = target
        st.auto_retarget_on_receive = True

        if not bridge.is_running():
            try:
                bridge.start_server(st.port)
            except Exception as exc:
                self.report({"ERROR"}, f"Could not start receiver: {exc}")
                return {"CANCELLED"}

        try:
            payload = prompt_payload(context)
            st.last_status = "Generating in Kimodo, then binding..."
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                st.kimodo_url.rstrip("/") + "/kimodo-bridge/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=900) as resp:
                result = json.loads(resp.read().decode("utf-8") or "{}")
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "Kimodo generation failed")
            st.last_status = f"Generated and queued for binding: {result.get('path', '')}"
            self.report({"INFO"}, "Kimodo motion generated and queued for binding")
        except Exception as exc:
            message = str(exc)
            if "WinError 10061" in message or "actively refused" in message:
                message = "Kimodo is not listening on 7870 yet. Start Kimodo and wait until WebUI opens."
            st.last_status = f"Error: {message}"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        return {"FINISHED"}


class BridgeOneClickBindLast(bpy.types.Operator):
    bl_idname = "rro_bridge.one_click_bind_last"
    bl_label = "One Click Bind Current BVH"
    bl_description = "Auto-fix target axis if needed, rebuild bone list, fix Mixamo mapping, and retarget the current BVH source"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        st = context.scene.rro_bridge
        source = context.scene.rsl_retargeting_armature_source
        if source is None and st.last_source_name:
            source = bpy.data.objects.get(st.last_source_name)
        try:
            result = bridge.run_bind_workflow(context, source, auto_fix_axis=True)
            self.report(
                {"INFO"},
                f"Bound {result['source'].name} to {result['target'].name}",
            )
        except Exception as exc:
            st.last_status = f"Error: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class BridgeStartKimodo(bpy.types.Operator):
    bl_idname = "rro_bridge.start_kimodo"
    bl_label = "Start Local Kimodo"
    bl_description = "Start the local Kimodo WebUI and prompt command server"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = context.scene.rro_bridge
        script = bpy.path.abspath(st.kimodo_start_script)
        try:
            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    script,
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            st.last_status = "Starting Kimodo... wait for 7860/7870 before generating"
            self.report({"INFO"}, "Starting Kimodo")
        except Exception as exc:
            st.last_status = f"Error: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}
