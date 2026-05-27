import bpy
import json
import subprocess
import time
import urllib.request

from .. import bridge


def _request_id():
    return time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"


def _ping_json(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _ensure_receiver(context):
    st = context.scene.rro_bridge
    try:
        bridge.ensure_running(st.port)
    except Exception as exc:
        raise RuntimeError(f"Could not start receiver: {exc}")
    try:
        return _ping_json(f"http://127.0.0.1:{st.port}/health", timeout=3)
    except Exception as exc:
        raise RuntimeError(f"Blender receiver is not healthy on port {st.port}: {exc}")


def _ensure_kimodo(st):
    try:
        return _ping_json(st.kimodo_url.rstrip("/") + "/health", timeout=5)
    except Exception as exc:
        message = str(exc)
        if "WinError 10061" in message or "actively refused" in message:
            message = "Kimodo is not listening on 7870 yet. Start Kimodo and wait until WebUI opens."
        raise RuntimeError(message)


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


def _send_generation_request(context, *, loop_workflow=False, bind=False):
    st = context.scene.rro_bridge
    target = bridge._armature_from_object(st.target_object) or context.scene.rsl_retargeting_armature_target
    will_bind = bool(bind and target is not None)
    if will_bind:
        st.target_object = target
        st.auto_retarget_on_receive = True
    elif bind:
        st.auto_retarget_on_receive = False

    cleared = bridge.clear_pending_queue() if bind else 0
    health = _ensure_receiver(context)
    if not health.get("ok"):
        raise RuntimeError("Blender receiver health check failed")
    kimodo_health = _ensure_kimodo(st)

    payload = prompt_payload(context)
    request_id = _request_id()
    payload["request_id"] = request_id
    payload["loop_workflow"] = bool(loop_workflow)
    payload["style_strength"] = st.loop_style_strength
    payload["loop_path_points"] = st.loop_path_points
    payload["loop_height_axis"] = "AUTO"
    if loop_workflow:
        payload["loop_exact"] = True
        payload["loop_inplace"] = True
        payload["loop_auto_pose"] = st.loop_auto_pose
        payload["send_original_comparison"] = st.loop_send_debug_versions
    st.last_request_id = request_id
    st.last_received_request_id = ""
    st.last_completed_request_id = ""
    st.last_debug_json = json.dumps(
        {
            "health": kimodo_health,
            "request_id": request_id,
            "loop_workflow": bool(loop_workflow),
            "style_strength": st.loop_style_strength,
            "path_points": st.loop_path_points if loop_workflow else None,
            "send_debug_versions": st.loop_send_debug_versions if loop_workflow else None,
            "payload": payload,
        },
        ensure_ascii=False,
    )

    if loop_workflow and will_bind:
        st.last_status = f"Generating loop motion in Kimodo, then binding... ({request_id})"
    elif loop_workflow and bind:
        st.last_status = f"Generating loop motion in Kimodo without binding; no Mixamo Target selected... ({request_id})"
    elif will_bind:
        st.last_status = f"Generating in Kimodo, then binding... ({request_id})"
    elif bind:
        st.last_status = f"Generating in Kimodo without binding; no Mixamo Target selected... ({request_id})"
    else:
        st.last_status = f"Sending prompt to Kimodo... ({request_id})"
    if cleared:
        st.last_status += f" Cleared {cleared} stale queued BVH item(s)."

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

    debug_result = {
        "bridge_version": result.get("bridge_version"),
        "loop_workflow": result.get("loop_workflow"),
        "loop_mode": result.get("loop_mode"),
        "pose_frame": result.get("pose_frame"),
        "pose_frame_selection": result.get("pose_frame_selection"),
        "root_profile_mode": result.get("root_profile_mode"),
        "style_strength": result.get("style_strength"),
        "cfg_weight": result.get("cfg_weight"),
        "path_points": result.get("path_points"),
        "stage1_path_diagnostics": result.get("stage1_path_diagnostics"),
        "stage2_path_diagnostics": result.get("stage2_path_diagnostics"),
        "loop_close_diagnostics": result.get("loop_close_diagnostics"),
        "first_last_pose_gap": result.get("first_last_pose_gap"),
        "first_last_root_gap": result.get("first_last_root_gap"),
        "first_last_root_height_gap": result.get("first_last_root_height_gap"),
        "first_last_rot_gap": result.get("first_last_rot_gap"),
        "path": result.get("path"),
        "original_path": result.get("original_path"),
        "stage1_path": result.get("stage1_path"),
        "stage2_path": result.get("stage2_path"),
        "blender_results": result.get("blender_results"),
        "payload": payload,
    }
    st.last_debug_json = json.dumps(debug_result, ensure_ascii=False)
    max_items = max(1, len(result.get("blender_results") or []))
    processed = bridge.process_pending_queue(max_items=max_items)
    return request_id, result, processed, will_bind


class BridgeStart(bpy.types.Operator):
    bl_idname = "rro_bridge.start"
    bl_label = "Start Bridge"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            bridge.ensure_running(context.scene.rro_bridge.port)
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
                bridge.ensure_running(st.port)
            except Exception as exc:
                st.auto_retarget_on_receive = previous_auto_retarget
                self.report({"ERROR"}, f"Could not start receiver: {exc}")
                return {"CANCELLED"}

        try:
            _ensure_receiver(context)
            _ensure_kimodo(st)
            payload = prompt_payload(context)
            request_id = _request_id()
            payload["request_id"] = request_id
            payload["style_strength"] = st.loop_style_strength
            payload["loop_path_points"] = st.loop_path_points
            payload["loop_height_axis"] = "AUTO"
            st.last_request_id = request_id
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
            st.last_debug_json = json.dumps(
                {
                    "bridge_version": result.get("bridge_version"),
                    "generation_mode": result.get("generation_mode"),
                    "style_strength": result.get("style_strength"),
                    "cfg_weight": result.get("cfg_weight"),
                    "path_points": result.get("path_points"),
                    "stage1_path_diagnostics": result.get("stage1_path_diagnostics"),
                    "path": result.get("path"),
                    "payload": payload,
                },
                ensure_ascii=False,
            )
            processed = bridge.process_pending_queue(max_items=1)
            if st.last_received_request_id == request_id or st.last_completed_request_id == request_id:
                st.last_status = f"Generated and imported BVH ({request_id}): {result.get('path', '')}"
                self.report({"INFO"}, "Kimodo motion generated and imported as BVH")
            elif processed:
                st.last_status = f"Generated and imported a BVH, but completion id did not match ({request_id}). Last received: {st.last_received_request_id}"
                self.report({"WARNING"}, st.last_status)
            else:
                st.last_status = f"Generated but Blender queue was not processed ({request_id}). Try Process Pending BVH Queue."
                self.report({"WARNING"}, st.last_status)
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
        try:
            request_id, result, processed, will_bind = _send_generation_request(context, bind=True)
            if st.last_completed_request_id == request_id and will_bind:
                st.last_status = f"Generated and bound ({request_id}): {result.get('path', '')}"
                self.report({"INFO"}, "Kimodo motion generated and bound")
            elif st.last_completed_request_id == request_id:
                st.last_status = f"Generated and imported ({request_id}); select a Mixamo Target to bind: {result.get('path', '')}"
                self.report({"WARNING"}, "Kimodo motion generated, but no Mixamo Target was selected")
            elif processed:
                st.last_status = f"Generated and imported, but completion id did not match ({request_id}). Last completed: {st.last_completed_request_id}"
                self.report({"WARNING"}, st.last_status)
            else:
                st.last_status = f"Generated but Blender queue was not processed ({request_id}). Try Bind Current BVH or Restart Blender receiver."
                self.report({"WARNING"}, st.last_status)
        except Exception as exc:
            message = str(exc)
            if "WinError 10061" in message or "actively refused" in message:
                message = "Kimodo is not listening on 7870 yet. Start Kimodo and wait until WebUI opens."
            st.last_status = f"Error: {message}"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        return {"FINISHED"}


class BridgeOneClickGenerateLoopBind(bpy.types.Operator):
    bl_idname = "rro_bridge.one_click_generate_loop_bind"
    bl_label = "循环生成并绑定"
    bl_description = "Generate a loop-ready Kimodo BVH with the v8 workflow, then auto-fix target, rebuild bones, and retarget"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = context.scene.rro_bridge
        try:
            request_id, result, processed, will_bind = _send_generation_request(context, loop_workflow=True, bind=True)
            if st.last_completed_request_id == request_id and will_bind:
                st.last_status = f"Generated loop and bound ({request_id}): {result.get('path', '')}"
                self.report({"INFO"}, "Kimodo loop motion generated and bound")
            elif st.last_completed_request_id == request_id:
                st.last_status = f"Generated loop and imported ({request_id}); select a Mixamo Target to bind: {result.get('path', '')}"
                self.report({"WARNING"}, "Kimodo loop motion generated, but no Mixamo Target was selected")
            elif processed:
                st.last_status = f"Generated loop and imported, but completion id did not match ({request_id}). Last completed: {st.last_completed_request_id}"
                self.report({"WARNING"}, st.last_status)
            else:
                st.last_status = f"Generated loop but Blender queue was not processed ({request_id}). Try Bind Current BVH or Restart Blender receiver."
                self.report({"WARNING"}, st.last_status)
        except Exception as exc:
            message = str(exc)
            if "WinError 10061" in message or "actively refused" in message:
                message = "Kimodo is not listening on 7870 yet. Start Kimodo and wait until WebUI opens."
            st.last_status = f"Error: {message}"
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        return {"FINISHED"}


class BridgeClearQueue(bpy.types.Operator):
    bl_idname = "rro_bridge.clear_queue"
    bl_label = "Clear Pending BVH Queue"
    bl_description = "Clear BVH files that were queued but not imported"
    bl_options = {"REGISTER"}

    def execute(self, context):
        count = bridge.clear_pending_queue()
        context.scene.rro_bridge.last_status = f"Cleared {count} pending BVH item(s)"
        self.report({"INFO"}, f"Cleared {count} pending BVH item(s)")
        return {"FINISHED"}


class BridgeProcessQueue(bpy.types.Operator):
    bl_idname = "rro_bridge.process_queue"
    bl_label = "Process Pending BVH Queue"
    bl_description = "Import and optionally retarget BVH files that are waiting in the Blender receiver queue"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        before = bridge.queue_size()
        processed = bridge.process_pending_queue()
        after = bridge.queue_size()
        context.scene.rro_bridge.last_status = f"Processed {processed} pending BVH item(s). Queue: {before} -> {after}"
        self.report({"INFO"}, context.scene.rro_bridge.last_status)
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


class BridgeCopyDebugLog(bpy.types.Operator):
    bl_idname = "rro_bridge.copy_debug_log"
    bl_label = "Copy Debug Log"
    bl_description = "Copy the latest Kimodo bridge status and diagnostics to the clipboard"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = context.scene.rro_bridge
        payload = {
            "status": st.last_status,
            "request_id": st.last_request_id,
            "received_request_id": st.last_received_request_id,
            "completed_request_id": st.last_completed_request_id,
            "last_source": st.last_source_name,
            "last_bvh": st.last_bvh_path,
            "debug": None,
        }
        if st.last_debug_json:
            try:
                payload["debug"] = json.loads(st.last_debug_json)
            except Exception:
                payload["debug"] = st.last_debug_json
        context.window_manager.clipboard = json.dumps(payload, ensure_ascii=False, indent=2)
        self.report({"INFO"}, "Copied Kimodo debug log")
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
            args = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script,
            ]
            if st.kimodo_open_browser_on_start:
                args.append("-OpenWebUI")
            subprocess.Popen(
                args,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            st.last_status = "Starting Kimodo... browser will open when 7860 is ready"
            self.report({"INFO"}, "Starting Kimodo")
        except Exception as exc:
            st.last_status = f"Error: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class BridgeStopKimodo(bpy.types.Operator):
    bl_idname = "rro_bridge.stop_kimodo"
    bl_label = "Stop Local Kimodo Ports"
    bl_description = "Stop processes currently occupying local Kimodo ports 7860, 7863, and 7870"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = context.scene.rro_bridge
        script = bpy.path.abspath(st.kimodo_stop_script)
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
            st.last_status = "Stopping Kimodo ports 7860/7863/7870..."
            self.report({"INFO"}, "Stopping Kimodo ports")
        except Exception as exc:
            st.last_status = f"Error: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}
