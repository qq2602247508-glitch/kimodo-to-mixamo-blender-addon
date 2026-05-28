import bpy
import json
import os
import subprocess
import time
import urllib.request
import random
import tempfile

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


def _post_generate(st, payload):
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
    return result


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
        payload = {
            "prompt": segments[0]["prompt"],
            "duration": max(segment["end"] for segment in segments),
            "segments": segments,
            "seed": st.prompt_seed,
            "diffusion_steps": st.prompt_diffusion_steps,
            "blender_url": f"http://127.0.0.1:{st.port}",
        }
        output_dir = bpy.path.abspath(st.cache_output_dir).strip()
        if output_dir:
            payload["output_dir"] = output_dir
        return payload

    payload = {
        "prompt": st.prompt,
        "duration": st.prompt_duration,
        "seed": st.prompt_seed,
        "diffusion_steps": st.prompt_diffusion_steps,
        "blender_url": f"http://127.0.0.1:{st.port}",
    }
    output_dir = bpy.path.abspath(st.cache_output_dir).strip()
    if output_dir:
        payload["output_dir"] = output_dir
    return payload


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
    if st.randomize_seed_on_generate:
        payload["seed"] = random.randint(1, 2147483646)
    payload["loop_workflow"] = bool(loop_workflow)
    payload["style_strength"] = st.loop_style_strength
    payload["use_path_constraint"] = bool(loop_workflow or st.use_path_constraint)
    if loop_workflow or st.use_path_constraint:
        payload["loop_path_points"] = st.loop_path_points
        payload["loop_height_axis"] = "AUTO"
    if loop_workflow:
        payload["loop_exact"] = True
        payload["loop_inplace"] = True
        payload["loop_auto_pose"] = st.loop_auto_pose
        payload["loop_close_tail"] = st.loop_close_tail
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
            "use_path_constraint": bool(loop_workflow or st.use_path_constraint),
            "path_points": st.loop_path_points if loop_workflow or st.use_path_constraint else None,
            "send_debug_versions": st.loop_send_debug_versions if loop_workflow else None,
            "warmup_before_bind": bool(loop_workflow and bind and st.loop_warmup_before_bind),
            "loop_close_tail": bool(st.loop_close_tail) if loop_workflow else None,
            "randomize_seed": bool(st.randomize_seed_on_generate),
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

    if loop_workflow and bind and st.loop_warmup_before_bind:
        warmup_payload = dict(payload)
        warmup_payload["request_id"] = request_id + "_warmup"
        warmup_payload["blender_url"] = ""
        warmup_payload["send_original_comparison"] = False
        st.last_status = f"Warming up Kimodo loop workflow... ({request_id})"
        _post_generate(st, warmup_payload)
        bridge.clear_pending_queue()
        st.last_status = f"Warmup done. Generating loop motion in Kimodo, then binding... ({request_id})"

    result = _post_generate(st, payload)

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
        "warmup_before_bind": bool(loop_workflow and bind and st.loop_warmup_before_bind),
        "loop_close_tail": bool(st.loop_close_tail) if loop_workflow else None,
        "randomize_seed": bool(st.randomize_seed_on_generate),
        "payload": payload,
    }
    st.last_debug_json = json.dumps(debug_result, ensure_ascii=False)
    max_items = max(1, len(result.get("blender_results") or []))
    processed = bridge.process_request_queue(
        request_id,
        expected_loop=bool(loop_workflow or bind),
        max_items=max_items,
        wait_seconds=8.0,
    )
    return request_id, result, processed, will_bind


class BridgeStart(bpy.types.Operator):
    bl_idname = "rro_bridge.start"
    bl_label = "启动接收器"
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
    bl_label = "停止接收器"
    bl_options = {"REGISTER"}

    def execute(self, _context):
        bridge.stop_server()
        return {"FINISHED"}


class BridgeUseRokokoTarget(bpy.types.Operator):
    bl_idname = "rro_bridge.use_rokoko_target"
    bl_label = "使用当前 Mixamo 目标"
    bl_description = "使用当前重定向面板里的目标骨架作为绑定目标"
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
    bl_label = "生成并发送 BVH"
    bl_description = "发送提示词到本地 Kimodo，并接收生成的 BVH，不自动绑定"
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
            payload["use_path_constraint"] = bool(st.use_path_constraint)
            if st.use_path_constraint:
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
                    "use_path_constraint": result.get("use_path_constraint"),
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
    bl_label = "一键生成并绑定"
    bl_description = "生成 Kimodo BVH，自动检查目标、重建骨骼列表并绑定到 Mixamo 角色"
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
    bl_description = "生成适合循环的 Kimodo BVH，自动检查目标、重建骨骼列表并绑定"
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
    bl_label = "清空待接收队列"
    bl_description = "清空已经排队但尚未导入的 BVH"
    bl_options = {"REGISTER"}

    def execute(self, context):
        count = bridge.clear_pending_queue()
        context.scene.rro_bridge.last_status = f"Cleared {count} pending BVH item(s)"
        self.report({"INFO"}, f"Cleared {count} pending BVH item(s)")
        return {"FINISHED"}


class BridgeClearGeneratedCache(bpy.types.Operator):
    bl_idname = "rro_bridge.clear_generated_cache"
    bl_label = "删除生成缓存文件"
    bl_description = "删除生成缓存目录里的 Kimodo BVH 过程文件"
    bl_options = {"REGISTER"}

    def execute(self, context):
        st = context.scene.rro_bridge
        cache_dir = bpy.path.abspath(st.cache_output_dir).strip()
        if not cache_dir:
            cache_dir = os.path.join(tempfile.gettempdir(), "kimodo_blender_bridge")
        if not os.path.isdir(cache_dir):
            st.last_status = f"Cache directory does not exist: {cache_dir}"
            self.report({"WARNING"}, st.last_status)
            return {"CANCELLED"}

        removed = 0
        errors = []
        for name in os.listdir(cache_dir):
            path = os.path.join(cache_dir, name)
            if not os.path.isfile(path):
                continue
            if not name.lower().endswith((".bvh", ".json", ".txt")):
                continue
            try:
                os.remove(path)
                removed += 1
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        st.last_status = f"Deleted {removed} generated cache file(s) from {cache_dir}"
        if errors:
            st.last_status += f"; {len(errors)} file(s) failed"
            self.report({"WARNING"}, st.last_status)
        else:
            self.report({"INFO"}, st.last_status)
        return {"FINISHED"}


class BridgeProcessQueue(bpy.types.Operator):
    bl_idname = "rro_bridge.process_queue"
    bl_label = "处理待接收 BVH"
    bl_description = "导入接收队列中等待处理的 BVH"
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
    bl_label = "绑定当前 BVH"
    bl_description = "自动检查目标朝向、重建骨骼列表并绑定当前 BVH"
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
    bl_label = "复制调试日志"
    bl_description = "复制最新 Kimodo 状态和诊断信息到剪贴板"
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
    bl_label = "启动本地 Kimodo"
    bl_description = "启动本地 Kimodo WebUI 和命令服务"
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
    bl_label = "关闭 Kimodo 端口"
    bl_description = "关闭当前占用 Kimodo 端口 7860、7863、7870 的进程"
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
