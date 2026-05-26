import json
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import bpy

from . import mixamo_tools

_SERVER = None
_THREAD = None
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


def _set_active(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.hide_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def delete_object_tree(obj):
    if obj is None or obj.name not in bpy.data.objects:
        return
    children = list(obj.children)
    for child in children:
        delete_object_tree(child)
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and data.users == 0 and isinstance(data, bpy.types.Armature):
        bpy.data.armatures.remove(data)


def _target_for_scene(scene):
    st = settings()
    return _armature_from_object(st.target_object)


def run_bind_workflow(context, source=None, *, auto_fix_axis=True, delete_source=None):
    scene = context.scene
    st = settings(context)
    source = source or scene.rsl_retargeting_armature_source
    target = _target_for_scene(scene)
    if target is None:
        raise RuntimeError("Please select a Mixamo Target in the Kimodo Bridge panel first, then try again.")
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

    should_delete_source = st.delete_source_after_retarget if delete_source is None else delete_source
    source_name = source.name
    source_deleted = False
    if should_delete_source and source != target:
        scene.rsl_retargeting_armature_source = None
        delete_object_tree(source)
        st.last_source_name = ""
        source_deleted = True

    axis_text = ", axis fixed" if axis_fixed else ""
    map_text = f", {fixed_mappings} mappings fixed" if fixed_mappings else ""
    delete_text = ", source deleted" if source_deleted else ""
    st.last_status = f"Bound {source_name} to {target.name}{axis_text}{map_text}{delete_text}"
    return {
        "source": None if source_deleted else source,
        "target": target,
        "axis_fixed": axis_fixed,
        "fixed_mappings": fixed_mappings,
        "source_deleted": source_deleted,
    }


def _import_bvh(path):
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    scene = bpy.context.scene
    st = settings()
    before = set(scene.objects)
    bpy.ops.import_anim.bvh(
        filepath=path,
        target="ARMATURE",
        global_scale=st.bvh_scale,
        rotate_mode="NATIVE",
        use_fps_scale=True,
        update_scene_fps=False,
        update_scene_duration=True,
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
            obj.name = f"Kimodo_{stem}"
            obj.data.name = f"{obj.name}_Armature"
            obj["kimodo_bridge_source_bvh"] = path
            imported = obj

    if imported is None:
        raise RuntimeError("BVH imported, but no armature object was created")

    scene.rsl_retargeting_armature_source = imported
    st.last_bvh_path = path
    st.last_source_name = imported.name
    st.last_status = "Imported BVH"

    target = _armature_from_object(st.target_object)
    if target is not None:
        scene.rsl_retargeting_armature_target = target

    if st.auto_retarget_on_receive:
        run_bind_workflow(bpy.context, imported, auto_fix_axis=True)
    else:
        _set_active(imported)

    return imported


def _timer_tick():
    global _TIMER_RUNNING, _LAST_ERROR
    try:
        while True:
            item = _QUEUE.get_nowait()
            _import_bvh(item["path"])
            _LAST_ERROR = ""
    except queue.Empty:
        pass
    except Exception as exc:
        _LAST_ERROR = str(exc)
        try:
            settings().last_status = f"Error: {exc}"
        except Exception:
            pass
        print(f"[Rokoko Retarget Bridge] Import/retarget failed: {exc}")

    if _SERVER is None:
        _TIMER_RUNNING = False
        return None
    return 0.5


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
            self._send_json(200, {"ok": True})
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
            if not path.lower().endswith(".bvh"):
                raise ValueError("path must point to a .bvh file")
            _QUEUE.put({"path": path})
            self._send_json(200, {"ok": True, "queued": path})
        except Exception as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})


def _ensure_timer():
    global _TIMER_RUNNING
    if not _TIMER_RUNNING:
        bpy.app.timers.register(_timer_tick, first_interval=0.2)
        _TIMER_RUNNING = True


def start_server(port):
    global _SERVER, _THREAD, _LAST_ERROR
    if _SERVER is not None:
        return
    _SERVER = ThreadingHTTPServer(("127.0.0.1", int(port)), _Handler)
    _THREAD = threading.Thread(target=_SERVER.serve_forever, daemon=True)
    _THREAD.start()
    _ensure_timer()
    _LAST_ERROR = ""
    settings().last_status = f"Listening on http://127.0.0.1:{port}"
    print(f"[Rokoko Retarget Bridge] Listening on http://127.0.0.1:{port}")


def stop_server():
    global _SERVER, _THREAD, _LAST_ERROR
    if _SERVER is not None:
        _SERVER.shutdown()
        _SERVER.server_close()
    _SERVER = None
    _THREAD = None
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
