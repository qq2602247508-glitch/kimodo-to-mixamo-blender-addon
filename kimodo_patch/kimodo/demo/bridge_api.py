# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import os
import queue
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
from urllib.parse import urlparse

from kimodo.exports.bvh import motion_to_bvh_bytes


_SERVER = None
_THREAD = None
_QUEUE = queue.Queue()
_WORKER = None


def _primary_session(demo):
    if not demo.client_sessions:
        raise RuntimeError("Open Kimodo WebUI once before sending prompts from Blender.")
    return next(iter(demo.client_sessions.values()))


def _primary_motion(session):
    if not session.motions:
        raise RuntimeError("No motion is available after generation.")
    return next(iter(session.motions.values()))


def _safe_stem(text):
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in text.lower()).strip("_")
    return (cleaned[:48] or "kimodo_prompt")


def _parse_prompt_segments(payload, session, fps):
    segments = payload.get("segments")
    if segments:
        texts = []
        durations = []
        last_end = None
        for index, segment in enumerate(segments):
            prompt = str(segment.get("prompt") or "").strip()
            if not prompt:
                raise ValueError(f"segments[{index}].prompt is required")
            start = float(segment.get("start", 0.0))
            end = float(segment.get("end", 0.0))
            if end <= start:
                raise ValueError(f"segments[{index}] end must be greater than start")
            if last_end is not None and start < last_end:
                raise ValueError("segments must be ordered and non-overlapping")
            texts.append(prompt)
            durations.append(end - start)
            last_end = end
        if not texts:
            raise ValueError("segments must not be empty")
        num_frames = [max(2, int(round(duration * fps))) for duration in durations]
        print(
            "[Kimodo Bridge API] Multi prompt request:",
            list(zip(texts, durations, num_frames)),
            flush=True,
        )
        return texts, num_frames, sum(durations)

    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    duration = float(payload.get("duration") or session.cur_duration or 6.0)
    duration = max(1.0, min(10.0, duration))
    num_frames = [max(2, int(round(duration * fps)))]
    print(
        "[Kimodo Bridge API] Single prompt request:",
        list(zip([prompt], [duration], num_frames)),
        flush=True,
    )
    return [prompt], num_frames, duration


def _export_bvh(session, out_path):
    motion = _primary_motion(session)
    payload = motion_to_bvh_bytes(
        motion.joints_local_rot,
        motion.joints_pos[:, session.skeleton.root_idx, :],
        skeleton=session.skeleton,
        fps=float(session.model_fps),
        standard_tpose=True,
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(payload)


def _send_to_blender(path, blender_url):
    body = json.dumps({"path": str(path)}).encode("utf-8")
    req = urlrequest.Request(
        blender_url.rstrip("/") + "/import-bvh",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=10) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Blender returned HTTP {resp.status}")


def _generate_and_send(demo, payload):
    session = _primary_session(demo)
    client = session.client
    fps = float(session.model_fps)
    prompts, num_frames, total_duration = _parse_prompt_segments(payload, session, fps)
    seed = int(payload.get("seed") if payload.get("seed") is not None else 42)
    diffusion_steps = int(payload.get("diffusion_steps") if payload.get("diffusion_steps") is not None else 100)
    blender_url = str(payload.get("blender_url") or os.environ.get("KIMODO_BLENDER_BRIDGE_URL") or "http://127.0.0.1:8765")

    demo.generate(
        client,
        prompts,
        num_frames,
        1,
        seed,
        diffusion_steps,
        cfg_weight=[2.0, 2.0],
        cfg_type="separated",
        postprocess_parameters={"post_processing": False, "root_margin": 0.04},
        transitions_parameters={"num_transition_frames": 5},
        real_robot_rotations=False,
    )

    session.max_frame_idx = int(session.cur_duration * session.model_fps) - 1
    demo.set_frame(client.client_id, 0)

    out_dir = Path(os.environ.get("KIMODO_BRIDGE_OUTPUT_DIR") or Path(tempfile.gettempdir()) / "kimodo_blender_bridge")
    filename = f"{_safe_stem(prompts[0])}_{time.strftime('%Y%m%d_%H%M%S')}.bvh"
    out_path = out_dir / filename
    _export_bvh(session, out_path)
    _send_to_blender(out_path, blender_url)
    return {
        "ok": True,
        "path": str(out_path),
        "prompt": prompts[0],
        "prompts": prompts,
        "num_frames": num_frames,
        "segment_durations": [frame_count / fps for frame_count in num_frames],
        "duration": total_duration,
        "blender_url": blender_url,
    }


def _worker_loop(demo):
    while _SERVER is not None:
        item = _QUEUE.get()
        if item is None:
            return
        payload, result_queue = item
        try:
            result_queue.put(_generate_and_send(demo, payload))
        except Exception as exc:
            result_queue.put({"ok": False, "error": str(exc)})


class _Handler(BaseHTTPRequestHandler):
    server_version = "KimodoBridgeAPI/0.1"

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
        if urlparse(self.path).path != "/kimodo-bridge/generate":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body or "{}")
            result_queue = queue.Queue(maxsize=1)
            _QUEUE.put((payload, result_queue))
            result = result_queue.get(timeout=float(payload.get("timeout") or 600.0))
            self._send_json(200 if result.get("ok") else 500, result)
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})


def start_bridge_api(demo, port=None):
    global _SERVER, _THREAD, _WORKER
    if _SERVER is not None:
        return
    port = int(port or os.environ.get("KIMODO_COMMAND_PORT") or 7870)
    _SERVER = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    _THREAD = threading.Thread(target=_SERVER.serve_forever, daemon=True)
    _THREAD.start()
    _WORKER = threading.Thread(target=_worker_loop, args=(demo,), daemon=True)
    _WORKER.start()
    print(f"[Kimodo Bridge API] Listening on http://127.0.0.1:{port}")


def stop_bridge_api():
    global _SERVER, _THREAD, _WORKER
    if _SERVER is not None:
        _SERVER.shutdown()
        _SERVER.server_close()
    _SERVER = None
    _THREAD = None
    _QUEUE.put(None)
    _WORKER = None
