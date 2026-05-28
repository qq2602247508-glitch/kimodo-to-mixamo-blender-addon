import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import bpy

from . import mixamo_tools

_SERVER = None
_THREAD = None
_PORT = None
_QUEUE = queue.Queue()
_TIMER_RUNNING = False
_LAST_ERROR = ""


def settings(context=None):
    return (context or bpy.context).scene.rro_bridge


def _armature_from_object(obj):
    if obj is None:
        return None
    if obj.type == "ARMATURE":
        return obj
    if obj.type == "MESH":
        if obj.parent and obj.parent.type == "ARMATURE":
            return obj.parent
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" and modifier.object:
                return modifier.object
    return None


def poll_target_object(_self, obj):
    return _armature_from_object(obj) is not None


def is_running():
    return _SERVER is not None


def queue_size():
    return _QUEUE.qsize()


def clear_pending_queue():
    count = 0
    try:
        while True:
            _QUEUE.get_nowait()
            count += 1
    except queue.Empty:
        pass
    try:
        settings().last_status = f"Cleared {count} pending BVH item(s)"
    except Exception:
        pass
    return count


def current_port():
    return _PORT


def ensure_running(port):
    if _SERVER is not None and _PORT != int(port):
        stop_server()
    if _SERVER is None:
        start_server(port)
    else:
        _ensure_timer()


def _set_active(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _target_for_scene(scene):
    st = settings()
    return _armature_from_object(st.target_object) or scene.rsl_retargeting_armature_target


def run_bind_workflow(context, source=None, *, auto_fix_axis=True):
    scene = context.scene
    st = settings(context)
    source = source or scene.rsl_retargeting_armature_source
    target = _target_for_scene(scene)
    if target is None:
        raise RuntimeError("Please select a Mixamo Target first, then try again.")
    if source is None:
        raise RuntimeError("No BVH source selected. Send/import a BVH first.")

    scene.rsl_retargeting_armature_source = source
    scene.rsl_retargeting_armature_target = target

    axis = mixamo_tools.analyze_target_axis(target)
    axis_fixed = False
    if not axis["ok"] and auto_fix_axis:
        fixed_axis = mixamo_tools.fix_target_axis(target)
        axis_fixed = bool(fixed_axis.get("fixed"))
        if not fixed_axis["ok"] and not axis_fixed:
            raise RuntimeError("Target axis is abnormal and cannot be fixed automatically: " + fixed_axis["status"])

    _set_active(source)
    bpy.ops.rsl.build_bone_list()
    fixed_mappings = mixamo_tools.force_mixamo_bone_map(scene)
    bpy.ops.rsl.retarget_animation()

    axis_text = ", axis fixed" if axis_fixed else ""
    map_text = f", {fixed_mappings} mappings fixed" if fixed_mappings else ""
    st.last_status = f"Bound {source.name} to {target.name}{axis_text}{map_text}"
    return {
        "source": source,
        "target": target,
        "axis_fixed": axis_fixed,
        "fixed_mappings": fixed_mappings,
    }


def _import_bvh(path, request_id="", clip_role="loop"):
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    scene = bpy.context.scene
    st = settings()
    clip_role = str(clip_role or "loop")
    is_loop_clip = clip_role == "loop"
    before = set(scene.objects)
    bpy.ops.import_anim.bvh(
        filepath=path,
        target="ARMATURE",
        global_scale=st.bvh_scale,
        frame_start=1,
        rotate_mode="NATIVE",
        use_fps_scale=False,
        update_scene_fps=False,
        update_scene_duration=True,
        use_cyclic=False,
        axis_forward="-Z",
        axis_up="Y",
    )
    created = list(set(scene.objects) - before)
    stem = os.path.splitext(os.path.basename(path))[0]
    imported = None
    collection = bpy.data.collections.get("Kimodo BVH Imports")
    if collection is None:
        collection = bpy.data.collections.new("Kimodo BVH Imports")
        scene.collection.children.link(collection)

    for obj in created:
        if obj.name not in collection.objects:
            collection.objects.link(obj)
        for parent_collection in list(obj.users_collection):
            if parent_collection != collection:
                parent_collection.objects.unlink(obj)
        if obj.type == "ARMATURE":
            role_prefix = f"{clip_role}_" if clip_role and clip_role != "loop" else ""
            obj.name = f"Kimodo_{role_prefix}{stem}"
            obj.data.name = f"{obj.name}_Armature"
            obj["kimodo_bridge_source_bvh"] = path
            obj["kimodo_clip_role"] = clip_role
            imported = obj

    if imported is None:
        raise RuntimeError("BVH imported, but no armature object was created")

    if is_loop_clip:
        scene.rsl_retargeting_armature_source = imported
    st.last_bvh_path = path
    st.last_source_name = imported.name
    st.last_received_request_id = request_id
    role_text = f" {clip_role}" if clip_role else ""
    st.last_status = f"Imported{role_text} BVH ({request_id})" if request_id else f"Imported{role_text} BVH"

    target = _armature_from_object(st.target_object) or scene.rsl_retargeting_armature_target
    if target is not None:
        scene.rsl_retargeting_armature_target = target

    if is_loop_clip and st.auto_retarget_on_receive:
        run_bind_workflow(bpy.context, imported, auto_fix_axis=True)
        if not st.loop_send_debug_versions:
            imported.hide_set(True)
            imported.hide_viewport = True
            imported.hide_render = True
    else:
        _set_active(imported)

    if is_loop_clip:
        st.last_completed_request_id = request_id
    return imported


def _timer_tick():
    global _TIMER_RUNNING, _LAST_ERROR
    process_pending_queue()

    if _SERVER is None:
        _TIMER_RUNNING = False
        return None
    return 0.5


def process_pending_queue(max_items=0):
    global _LAST_ERROR
    processed = 0
    try:
        while max_items <= 0 or processed < max_items:
            item = _QUEUE.get_nowait()
            request_id = item.get("request_id", "")
            clip_role = item.get("clip_role", "loop")
            if clip_role != "loop" and not settings().loop_send_debug_versions:
                processed += 1
                try:
                    settings().last_status = f"Skipped debug BVH {clip_role} ({request_id})"
                except Exception:
                    pass
                continue
            try:
                settings().last_status = (
                    f"Received {clip_role} BVH, importing... ({request_id})"
                    if request_id
                    else f"Received {clip_role} BVH, importing..."
                )
            except Exception:
                pass
            _import_bvh(item["path"], request_id=request_id, clip_role=clip_role)
            _LAST_ERROR = ""
            processed += 1
    except queue.Empty:
        pass
    except Exception as exc:
        _LAST_ERROR = str(exc)
        try:
            settings().last_status = f"Error: {exc}"
        except Exception:
            pass
        print(f"[Rokoko Retarget Bridge] Import/retarget failed: {exc}")
    return processed


def process_request_queue(request_id, *, expected_loop=True, max_items=0, wait_seconds=6.0):
    """Process only BVHs that belong to the active generation request.

    Late BVHs from older requests are discarded here so they cannot steal an
    automatic retarget from the current one-click generation.
    """
    global _LAST_ERROR
    deadline = time.time() + max(0.0, float(wait_seconds))
    processed = 0
    skipped = 0
    imported_loop = False
    request_id = str(request_id or "")

    while max_items <= 0 or processed + skipped < max_items:
        timeout = 0.1 if time.time() < deadline else 0.0
        try:
            item = _QUEUE.get(timeout=timeout) if timeout else _QUEUE.get_nowait()
        except queue.Empty:
            if imported_loop or time.time() >= deadline:
                break
            continue

        item_request_id = str(item.get("request_id", ""))
        clip_role = str(item.get("clip_role", "loop") or "loop")
        if request_id and item_request_id != request_id:
            skipped += 1
            try:
                settings().last_status = (
                    f"Skipped stale BVH {clip_role} ({item_request_id}); waiting for {request_id}"
                )
            except Exception:
                pass
            continue

        if expected_loop and clip_role != "loop":
            if settings().loop_send_debug_versions:
                try:
                    settings().last_status = f"Importing current debug BVH {clip_role} ({item_request_id})"
                    _import_bvh(item["path"], request_id=item_request_id, clip_role=clip_role)
                    processed += 1
                except Exception as exc:
                    _LAST_ERROR = str(exc)
                    try:
                        settings().last_status = f"Error importing debug BVH {clip_role}: {exc}"
                    except Exception:
                        pass
                    print(f"[Rokoko Retarget Bridge] Debug import failed: {exc}")
            else:
                try:
                    settings().last_status = f"Skipped current debug BVH {clip_role} ({item_request_id})"
                except Exception:
                    pass
                skipped += 1
            continue

        try:
            settings().last_status = f"Received current {clip_role} BVH, importing... ({item_request_id})"
        except Exception:
            pass
        try:
            _import_bvh(item["path"], request_id=item_request_id, clip_role=clip_role)
            _LAST_ERROR = ""
            processed += 1
            if clip_role == "loop":
                imported_loop = True
                if expected_loop:
                    break
        except Exception as exc:
            _LAST_ERROR = str(exc)
            try:
                settings().last_status = f"Error: {exc}"
            except Exception:
                pass
            print(f"[Rokoko Retarget Bridge] Import/retarget failed: {exc}")
            break

    return processed


class _Handler(BaseHTTPRequestHandler):
    server_version = "RokokoRetargetBridge/1.0"

    def log_message(self, fmt, *args):
        return

    def _send_json(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            st = settings()
            self._send_json(
                200,
                {
                    "ok": True,
                    "port": _PORT,
                    "queue_size": _QUEUE.qsize(),
                    "auto_retarget_on_receive": bool(st.auto_retarget_on_receive),
                    "target": st.target_object.name if st.target_object else "",
                    "last_status": st.last_status,
                    "last_error": _LAST_ERROR,
                },
            )
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/import-bvh":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
            path = os.path.abspath(payload["path"])
            request_id = str(payload.get("request_id") or "")
            clip_role = str(payload.get("clip_role") or "loop")
            if not path.lower().endswith(".bvh"):
                raise ValueError("path must point to a .bvh file")
            _QUEUE.put({"path": path, "request_id": request_id, "clip_role": clip_role, "metadata": payload})
            _ensure_timer()
            self._send_json(
                200,
                {
                    "ok": True,
                    "queued": path,
                    "request_id": request_id,
                    "clip_role": clip_role,
                    "queue_size": _QUEUE.qsize(),
                },
            )
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})


def _ensure_timer():
    global _TIMER_RUNNING
    try:
        is_registered = bpy.app.timers.is_registered(_timer_tick)
    except Exception:
        is_registered = _TIMER_RUNNING
    if not is_registered:
        bpy.app.timers.register(_timer_tick, first_interval=0.2)
    _TIMER_RUNNING = True


def start_server(port):
    global _SERVER, _THREAD, _PORT, _LAST_ERROR
    port = int(port)
    if _SERVER is not None:
        if _PORT == port:
            _ensure_timer()
            return
        stop_server()
    if _SERVER is not None:
        return
    _SERVER = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    _THREAD = threading.Thread(target=_SERVER.serve_forever, daemon=True)
    _THREAD.start()
    _PORT = port
    _ensure_timer()
    _LAST_ERROR = ""
    settings().last_status = f"Listening on http://127.0.0.1:{port}"
    print(f"[Rokoko Retarget Bridge] Listening on http://127.0.0.1:{port}")


def stop_server():
    global _SERVER, _THREAD, _PORT, _LAST_ERROR
    if _SERVER is not None:
        _SERVER.shutdown()
        _SERVER.server_close()
    _SERVER = None
    _THREAD = None
    _PORT = None
    _LAST_ERROR = ""
    if bpy.context.scene and hasattr(bpy.context.scene, "rro_bridge"):
        settings().last_status = "Stopped"
    print("[Rokoko Retarget Bridge] Stopped")


def maybe_auto_start():
    scene = bpy.context.scene
    if scene is not None and hasattr(scene, "rro_bridge") and scene.rro_bridge.auto_start:
        try:
            start_server(scene.rro_bridge.port)
        except Exception as exc:
            scene.rro_bridge.last_status = f"Error: {exc}"
    return None
