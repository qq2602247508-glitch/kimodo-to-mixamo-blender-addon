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

import torch

from kimodo.constraints import FullBodyConstraintSet, Root2DConstraintSet
from kimodo.exports.bvh import motion_to_bvh_bytes
from kimodo.geometry import axis_angle_to_matrix, matrix_to_axis_angle
from kimodo.tools import seed_everything

from .embedding_cache import CachedTextEncoder


_SERVER = None
_THREAD = None
_QUEUE = queue.Queue()
_WORKER = None
_BRIDGE_VERSION = "straight-style-path-toggle-v13"


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


def _export_loop_bvh(session, out_path, payload):
    motion = _primary_motion(session)
    local_rot = motion.joints_local_rot.clone()
    root_positions = motion.joints_pos[:, session.skeleton.root_idx, :].clone()

    if bool(payload.get("loop_exact", True)) and local_rot.shape[0] >= 2:
        local_rot[-1] = local_rot[0]
        root_positions[-1] = root_positions[0]

    if bool(payload.get("loop_inplace", True)):
        height_axis = str(payload.get("loop_height_axis") or "Y").upper()
        height_idx = {"X": 0, "Y": 1, "Z": 2}.get(height_axis, 1)
        for idx in range(3):
            if idx != height_idx:
                root_positions[:, idx] = root_positions[0, idx]
        if bool(payload.get("loop_exact", True)) and root_positions.shape[0] >= 2:
            root_positions[-1, height_idx] = root_positions[0, height_idx]

    payload_bytes = motion_to_bvh_bytes(
        local_rot,
        root_positions,
        skeleton=session.skeleton,
        fps=float(session.model_fps),
        standard_tpose=True,
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(payload_bytes)


def _no_progress(iterable, *args, **kwargs):
    return iterable


def _call_model_with_session_cache(model, session, *args, **kwargs):
    encoder = getattr(model, "text_encoder", None)
    if isinstance(encoder, CachedTextEncoder):
        with encoder.session_context(session):
            return model(*args, **kwargs)
    return model(*args, **kwargs)


def _straight_root_constraint(
    skeleton,
    num_frames,
    forward_distance,
    device,
    num_points=5,
    use_heading=False,
    root_progress=None,
):
    num_points = max(2, min(int(num_points), int(num_frames)))
    frame_indices = torch.linspace(0, num_frames - 1, num_points, device=device).round().long().unique()
    root_2d = torch.zeros((num_frames, 2), device=device)
    if root_progress is None:
        root_2d[:, 1] = torch.linspace(0.0, float(forward_distance), num_frames, device=device)
    else:
        root_2d[:, 1] = root_progress.to(device=device, dtype=root_2d.dtype)
    heading = None
    if use_heading:
        heading = torch.zeros((len(frame_indices), 2), device=device)
        heading[:, 0] = 1.0
    return Root2DConstraintSet(
        skeleton,
        frame_indices,
        root_2d[frame_indices],
        global_root_heading=heading,
    )


def _slice_to_model_skeleton(output, model_skeleton, export_skeleton):
    posed = output["posed_joints"][0]
    rots = output["global_rot_mats"][0]
    if model_skeleton.nbjoints == posed.shape[1]:
        return posed, rots
    skel_slice = model_skeleton.get_skel_slice(export_skeleton)
    return posed[:, skel_slice], rots[:, skel_slice]


def _cfg_from_style_strength(payload):
    if payload.get("loop_cfg_weight") is not None:
        return payload.get("loop_cfg_weight")
    style = float(payload.get("style_strength") if payload.get("style_strength") is not None else 5.0)
    style = max(0.0, min(10.0, style))
    # Keep style=5 close to the previous good default [4.0, 2.0],
    # then make the two ends visibly different.
    text_cfg = 2.4 + style * 0.32
    constraint_cfg = max(1.5, 4.2 - style * 0.36)
    return [round(text_cfg, 3), round(constraint_cfg, 3)]


def _path_points_from_style(payload, total_frames):
    if payload.get("loop_path_points") is not None:
        return max(2, min(int(payload.get("loop_path_points")), int(total_frames)))
    style = float(payload.get("style_strength") if payload.get("style_strength") is not None else 5.0)
    style = max(0.0, min(10.0, style))
    # Fallback only; Blender normally sends loop_path_points explicitly.
    points = int(round(9.0 - style * 0.3))
    return max(5, min(points, int(total_frames)))


def _root_path_diagnostics(output, skeleton, forward_distance, target_root_2d=None):
    root = output["posed_joints"][0, :, skeleton.root_idx, :].detach()
    root_2d = root[:, [0, 2]]
    rel = root_2d - root_2d[0]
    if target_root_2d is None:
        target = torch.zeros_like(rel)
        target[:, 1] = torch.linspace(0.0, float(forward_distance), rel.shape[0], device=rel.device, dtype=rel.dtype)
    else:
        target = target_root_2d.to(device=rel.device, dtype=rel.dtype)
    deviation = rel - target
    lateral_abs = torch.abs(deviation[:, 0])
    forward_error = deviation[:, 1]
    return {
        "end_x": float(rel[-1, 0].detach().cpu()),
        "end_z": float(rel[-1, 1].detach().cpu()),
        "target_z": float(forward_distance),
        "max_lateral_abs": float(torch.max(lateral_abs).detach().cpu()),
        "mean_lateral_abs": float(torch.mean(lateral_abs).detach().cpu()),
        "end_forward_error": float(forward_error[-1].detach().cpu()),
        "mean_forward_error_abs": float(torch.mean(torch.abs(forward_error)).detach().cpu()),
    }


def _root_progress_from_motion(output, skeleton, forward_distance, device, total_frames):
    root = output["posed_joints"][0, :, skeleton.root_idx, [0, 2]].detach().to(device)
    deltas = torch.linalg.vector_norm(root[1:] - root[:-1], dim=-1)
    progress = torch.zeros(total_frames, device=device, dtype=root.dtype)
    progress[1:] = torch.cumsum(deltas[: total_frames - 1], dim=0)
    total = progress[-1].abs()
    if total < 1e-6:
        progress = torch.linspace(0.0, float(forward_distance), total_frames, device=device, dtype=root.dtype)
    else:
        progress = progress / total * float(forward_distance)
    return progress


def _target_root_2d_from_progress(root_progress):
    target = torch.zeros((int(root_progress.shape[0]), 2), device=root_progress.device, dtype=root_progress.dtype)
    target[:, 1] = root_progress
    return target


def _close_loop_tail(local_rot, root_positions, skeleton, payload):
    if not bool(payload.get("loop_close_tail", False)):
        return local_rot, root_positions, {"enabled": False}
    total_frames = int(local_rot.shape[0])
    close_frames = int(payload.get("loop_close_frames") if payload.get("loop_close_frames") is not None else 8)
    close_frames = max(2, min(close_frames, total_frames))
    start = total_frames - close_frames
    original_last_rot = local_rot[-1].clone()
    original_last_root = root_positions[-1].clone()

    for frame in range(start, total_frames):
        alpha = (frame - start + 1) / close_frames
        alpha = alpha * alpha * (3.0 - 2.0 * alpha)
        delta = local_rot[0] @ local_rot[frame].transpose(-1, -2)
        delta_axis = matrix_to_axis_angle(delta)
        correction = axis_angle_to_matrix(delta_axis * alpha)
        local_rot[frame] = correction @ local_rot[frame]
        root_positions[frame] = root_positions[frame] * (1.0 - alpha) + root_positions[0] * alpha

    local_rot[-1] = local_rot[0]
    root_positions[-1] = root_positions[0]
    closed_global_rot, closed_posed_joints, _ = skeleton.fk(local_rot, root_positions)
    rot_gap_before = torch.linalg.matrix_norm(local_rot[0] - original_last_rot, dim=(-2, -1)).mean()
    root_gap_before = torch.linalg.vector_norm(original_last_root - root_positions[0])
    rot_gap_after = torch.linalg.matrix_norm(local_rot[0] - local_rot[-1], dim=(-2, -1)).mean()
    root_gap_after = torch.linalg.vector_norm(root_positions[-1] - root_positions[0])
    return local_rot, root_positions, {
        "enabled": True,
        "frames": close_frames,
        "rot_gap_before": float(rot_gap_before.detach().cpu()),
        "root_gap_before": float(root_gap_before.detach().cpu()),
        "rot_gap_after": float(rot_gap_after.detach().cpu()),
        "root_gap_after": float(root_gap_after.detach().cpu()),
        "closed_global_rot": closed_global_rot,
        "closed_posed_joints": closed_posed_joints,
    }


def _prompt_for_style(prompt, payload):
    style = float(payload.get("style_strength") if payload.get("style_strength") is not None else 5.0)
    if style < 7.0:
        return prompt
    return f"{prompt}. Strongly emphasize the distinctive style and personality of this motion."


def _auto_select_loop_pose_frame(posed_joints, root_idx, payload):
    total_frames = int(posed_joints.shape[0])
    if total_frames < 12:
        return max(1, total_frames // 2), {"mode": "fallback_midpoint"}

    skip_ratio = float(payload.get("loop_pose_skip_ratio") if payload.get("loop_pose_skip_ratio") is not None else 0.25)
    skip_ratio = max(0.1, min(0.4, skip_ratio))
    start = max(2, int(round(total_frames * skip_ratio)))
    end = min(total_frames - 3, int(round(total_frames * (1.0 - skip_ratio))))
    if end <= start:
        start = max(2, total_frames // 3)
        end = min(total_frames - 3, total_frames * 2 // 3)

    root = posed_joints[:, root_idx, :]
    root_2d = root[:, [0, 2]]
    velocity = torch.linalg.vector_norm(root_2d[1:] - root_2d[:-1], dim=-1)
    accel = torch.zeros_like(velocity)
    if velocity.shape[0] > 1:
        accel[1:] = torch.abs(velocity[1:] - velocity[:-1])

    rel_pose = posed_joints - posed_joints[:, root_idx : root_idx + 1]
    pose_delta = torch.linalg.vector_norm(rel_pose[1:] - rel_pose[:-1], dim=-1).mean(dim=-1)
    pose_delta_full = torch.zeros(total_frames, device=posed_joints.device, dtype=posed_joints.dtype)
    pose_delta_full[1:] = pose_delta

    velocity_full = torch.zeros(total_frames, device=posed_joints.device, dtype=posed_joints.dtype)
    velocity_full[1:] = velocity
    accel_full = torch.zeros(total_frames, device=posed_joints.device, dtype=posed_joints.dtype)
    accel_full[1:] = accel

    candidates = torch.arange(start, end + 1, device=posed_joints.device)
    center = (total_frames - 1) * 0.5
    half_window = max(1.0, (end - start) * 0.5)
    median_velocity = torch.median(velocity_full[candidates])
    median_pose_delta = torch.median(pose_delta_full[candidates])

    velocity_score = torch.abs(velocity_full[candidates] - median_velocity) / (median_velocity.abs() + 1e-6)
    accel_score = accel_full[candidates] / (median_velocity.abs() + 1e-6)
    pose_score = torch.abs(pose_delta_full[candidates] - median_pose_delta) / (median_pose_delta.abs() + 1e-6)
    center_score = torch.abs(candidates.float() - center) / half_window
    score = velocity_score * 0.45 + accel_score * 0.3 + pose_score * 0.15 + center_score * 0.1
    best_idx = int(candidates[int(torch.argmin(score))].detach().cpu())
    diagnostics = {
        "mode": "auto_stable_mid_motion",
        "search_start": int(start),
        "search_end": int(end),
        "best_score": float(torch.min(score).detach().cpu()),
        "best_velocity": float(velocity_full[best_idx].detach().cpu()),
        "median_velocity": float(median_velocity.detach().cpu()),
        "best_accel": float(accel_full[best_idx].detach().cpu()),
        "best_pose_delta": float(pose_delta_full[best_idx].detach().cpu()),
    }
    return best_idx, diagnostics


def _export_model_output_bvh(output, skeleton, out_path, fps):
    local_rot = output["local_rot_mats"][0].clone()
    root_positions = output["posed_joints"][0, :, skeleton.root_idx, :].clone()
    payload_bytes = motion_to_bvh_bytes(
        local_rot,
        root_positions,
        skeleton=skeleton,
        fps=fps,
        standard_tpose=True,
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(payload_bytes)


def _export_unconstrained_original_bvh(demo, session, out_path, payload, prompts, num_frames, seed, diffusion_steps):
    model_bundle = demo.load_model(session.model_name)
    model = model_bundle.model
    total_frames = max(32, int(sum(num_frames)))
    raw_prompt = " ".join(prompts).strip() if len(prompts) > 1 else prompts[0]
    prompt = _prompt_for_style(raw_prompt, payload)
    cfg_weight = _cfg_from_style_strength(payload)

    print(
        "[Kimodo Bridge API] Original comparison: unconstrained prompt generation",
        {"prompt": prompt, "frames": total_frames, "cfg_weight": cfg_weight},
        flush=True,
    )
    seed_everything(seed)
    output = _call_model_with_session_cache(
        model,
        session,
        prompt,
        total_frames,
        diffusion_steps,
        multi_prompt=False,
        constraint_lst=[],
        cfg_weight=cfg_weight,
        num_samples=1,
        cfg_type="separated",
        post_processing=False,
        progress_bar=_no_progress,
    )
    _export_model_output_bvh(output, session.skeleton, out_path, float(session.model_fps))
    return output


def _export_two_stage_loop_bvh(
    demo,
    session,
    out_path,
    payload,
    prompts,
    num_frames,
    seed,
    diffusion_steps,
    stage1_out_path=None,
    stage2_out_path=None,
    original_output=None,
):
    model_bundle = demo.load_model(session.model_name)
    model = model_bundle.model
    model_skeleton = model.skeleton
    export_skeleton = session.skeleton
    device = model.device
    total_frames = max(32, int(sum(num_frames)))
    fps = float(session.model_fps)
    duration = total_frames / fps
    if bool(payload.get("loop_auto_pose", False)):
        requested_pose_frame = None
    else:
        requested_pose_frame = payload.get("loop_pose_frame")
        if requested_pose_frame is None:
            requested_pose_frame = 30
    speed_mps = float(payload.get("loop_speed_mps") if payload.get("loop_speed_mps") is not None else 1.2)
    forward_distance = float(
        payload.get("loop_forward_distance")
        if payload.get("loop_forward_distance") is not None
        else max(0.6, duration * speed_mps)
    )
    raw_prompt = " ".join(prompts).strip() if len(prompts) > 1 else prompts[0]
    prompt = _prompt_for_style(raw_prompt, payload)
    path_points = _path_points_from_style(payload, total_frames)
    use_heading = bool(payload.get("loop_use_heading", False))
    style_strength = float(payload.get("style_strength") if payload.get("style_strength") is not None else 5.0)
    style_strength = max(0.0, min(10.0, style_strength))
    cfg_weight = _cfg_from_style_strength(payload)
    if original_output is not None and bool(payload.get("use_original_speed_profile", True)):
        root_progress = _root_progress_from_motion(original_output, export_skeleton, forward_distance, device, total_frames)
        root_profile_mode = "original_speed_profile"
    else:
        root_progress = torch.linspace(0.0, float(forward_distance), total_frames, device=device)
        root_profile_mode = "linear_uniform"
    target_root_2d = _target_root_2d_from_progress(root_progress)

    print(
        "[Kimodo Bridge API] Loop workflow stage 1: straight root path",
        {
            "prompt": prompt,
            "frames": total_frames,
            "pose_frame_request": requested_pose_frame if requested_pose_frame is not None else "auto",
            "forward_distance": forward_distance,
            "path_points": path_points,
            "style_strength": style_strength,
            "cfg_weight": cfg_weight,
            "root_profile_mode": root_profile_mode,
        },
        flush=True,
    )
    seed_everything(seed)
    stage1 = _call_model_with_session_cache(
        model,
        session,
        prompt,
        total_frames,
        diffusion_steps,
        multi_prompt=False,
        constraint_lst=[
            [
                _straight_root_constraint(
                    model_skeleton,
                    total_frames,
                    forward_distance,
                    device,
                    num_points=path_points,
                    use_heading=use_heading,
                    root_progress=root_progress,
                )
            ]
        ],
        cfg_weight=cfg_weight,
        num_samples=1,
        cfg_type="separated",
        post_processing=False,
        progress_bar=_no_progress,
    )
    if stage1_out_path is not None:
        _export_model_output_bvh(stage1, export_skeleton, stage1_out_path, fps)
    stage1_path_diagnostics = _root_path_diagnostics(stage1, export_skeleton, forward_distance, target_root_2d)

    base_pos, base_rot = _slice_to_model_skeleton(stage1, model_skeleton, export_skeleton)
    if requested_pose_frame is None or str(requested_pose_frame).strip().lower() in ("", "auto"):
        pose_frame, pose_frame_diagnostics = _auto_select_loop_pose_frame(base_pos, model_skeleton.root_idx, payload)
    else:
        pose_frame = int(requested_pose_frame)
        pose_frame = max(1, min(total_frames - 2, pose_frame))
        pose_frame_diagnostics = {"mode": "manual"}
    print(
        "[Kimodo Bridge API] Loop workflow selected pose frame",
        {"pose_frame": pose_frame, "diagnostics": pose_frame_diagnostics},
        flush=True,
    )
    pose0 = base_pos[pose_frame].clone()
    rot0 = base_rot[pose_frame].clone()
    start_root_2d = torch.tensor([0.0, 0.0], device=device)
    end_root_2d = torch.tensor([0.0, forward_distance], device=device)

    pose_start = pose0.clone()
    pose_start[:, 0] += start_root_2d[0] - pose_start[model_skeleton.root_idx, 0]
    pose_start[:, 2] += start_root_2d[1] - pose_start[model_skeleton.root_idx, 2]
    pose_end = pose0.clone()
    pose_end[:, 0] += end_root_2d[0] - pose_end[model_skeleton.root_idx, 0]
    pose_end[:, 2] += end_root_2d[1] - pose_end[model_skeleton.root_idx, 2]

    fullbody = FullBodyConstraintSet(
        model_skeleton,
        torch.tensor([0, total_frames - 1], device=device),
        torch.stack([pose_start, pose_end], dim=0),
        torch.stack([rot0, rot0], dim=0),
        smooth_root_2d=torch.stack([start_root_2d, end_root_2d], dim=0),
    )
    straight = _straight_root_constraint(
        model_skeleton,
        total_frames,
        forward_distance,
        device,
        num_points=path_points,
        use_heading=use_heading,
        root_progress=root_progress,
    )

    print(
        "[Kimodo Bridge API] Loop workflow stage 2: frame pose constrained at first/last",
        flush=True,
    )
    seed_everything(seed + 1)
    stage2 = _call_model_with_session_cache(
        model,
        session,
        prompt,
        total_frames,
        diffusion_steps,
        multi_prompt=False,
        constraint_lst=[[fullbody, straight]],
        cfg_weight=cfg_weight,
        num_samples=1,
        cfg_type="separated",
        post_processing=False,
        progress_bar=_no_progress,
    )
    stage2_path_diagnostics = _root_path_diagnostics(stage2, export_skeleton, forward_distance, target_root_2d)
    if stage2_out_path is not None:
        _export_model_output_bvh(stage2, export_skeleton, stage2_out_path, fps)

    local_rot = stage2["local_rot_mats"][0].clone()
    root_positions = stage2["posed_joints"][0, :, export_skeleton.root_idx, :].clone()
    raw_root_positions = root_positions.clone()
    if bool(payload.get("loop_inplace", True)):
        height_axis = str(payload.get("loop_height_axis") or "Y").upper()
        height_idx = {"X": 0, "Y": 1, "Z": 2}.get(height_axis, 1)
        for idx in range(3):
            if idx != height_idx:
                root_positions[:, idx] = root_positions[0, idx]
    local_rot, root_positions, close_diagnostics = _close_loop_tail(
        local_rot,
        root_positions,
        export_skeleton,
        payload,
    )
    display_global_rot = close_diagnostics.get("closed_global_rot") if close_diagnostics.get("enabled") else stage2["global_rot_mats"][0]
    display_posed_joints = close_diagnostics.get("closed_posed_joints") if close_diagnostics.get("enabled") else stage2["posed_joints"][0]

    payload_bytes = motion_to_bvh_bytes(
        local_rot,
        root_positions,
        skeleton=export_skeleton,
        fps=fps,
        standard_tpose=True,
    )
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_bytes(payload_bytes)

    demo.clear_motions(session.client.client_id)
    demo.add_character_motion(
        session.client,
        export_skeleton,
        display_posed_joints,
        display_global_rot,
        stage2.get("foot_contacts", torch.empty(1, 0, device=device))[0] if "foot_contacts" in stage2 else None,
    )
    session.max_frame_idx = total_frames - 1
    demo.set_frame(session.client.client_id, 0)

    first_pose = display_posed_joints[0]
    last_pose = display_posed_joints[-1]
    first_rel_pose = first_pose - first_pose[export_skeleton.root_idx]
    last_rel_pose = last_pose - last_pose[export_skeleton.root_idx]
    pose_gap = torch.linalg.vector_norm(first_rel_pose - last_rel_pose, dim=-1).mean()
    root_gap = torch.linalg.vector_norm(root_positions[-1] - root_positions[0])
    height_gap = torch.abs(root_positions[-1, 1] - root_positions[0, 1])
    rot_gap = torch.linalg.matrix_norm(local_rot[0] - local_rot[-1], dim=(-2, -1)).mean()
    return {
        "loop_workflow": True,
        "loop_mode": "two_stage_straight_path_frame_pose",
        "stage1": "same_prompt_with_dense_straight_root2d",
        "stage2": "same_prompt_with_frame_pose_at_first_last_plus_straight_root2d",
        "stage1_path": str(stage1_out_path) if stage1_out_path else None,
        "stage2_path": str(stage2_out_path) if stage2_out_path else None,
        "stage1_path_diagnostics": stage1_path_diagnostics,
        "stage2_path_diagnostics": stage2_path_diagnostics,
        "loop_close_diagnostics": {
            key: value for key, value in close_diagnostics.items() if key not in ("closed_global_rot", "closed_posed_joints")
        },
        "pose_frame": pose_frame,
        "pose_frame_selection": pose_frame_diagnostics,
        "forward_distance": forward_distance,
        "speed_mps": speed_mps,
        "path_points": path_points,
        "use_heading": use_heading,
        "style_strength": style_strength,
        "cfg_weight": cfg_weight,
        "root_profile_mode": root_profile_mode,
        "first_last_pose_gap": float(pose_gap.detach().cpu()),
        "first_last_root_gap": float(root_gap.detach().cpu()),
        "first_last_root_height_gap": float(height_gap.detach().cpu()),
        "first_last_rot_gap": float(rot_gap.detach().cpu()),
    }


def _export_straight_prompt_bvh(demo, session, out_path, payload, prompts, num_frames, seed, diffusion_steps):
    model_bundle = demo.load_model(session.model_name)
    model = model_bundle.model
    model_skeleton = model.skeleton
    export_skeleton = session.skeleton
    device = model.device
    total_frames = max(32, int(sum(num_frames)))
    fps = float(session.model_fps)
    duration = total_frames / fps
    speed_mps = float(payload.get("loop_speed_mps") if payload.get("loop_speed_mps") is not None else 1.2)
    forward_distance = float(
        payload.get("loop_forward_distance")
        if payload.get("loop_forward_distance") is not None
        else max(0.6, duration * speed_mps)
    )
    raw_prompt = " ".join(prompts).strip() if len(prompts) > 1 else prompts[0]
    prompt = _prompt_for_style(raw_prompt, payload)
    path_points = _path_points_from_style(payload, total_frames)
    use_path_constraint = bool(payload.get("use_path_constraint", True))
    use_heading = bool(payload.get("loop_use_heading", False))
    style_strength = float(payload.get("style_strength") if payload.get("style_strength") is not None else 5.0)
    style_strength = max(0.0, min(10.0, style_strength))
    cfg_weight = _cfg_from_style_strength(payload)

    seed_everything(seed)
    constraint_lst = []
    if use_path_constraint:
        constraint_lst = [
            [
                _straight_root_constraint(
                    model_skeleton,
                    total_frames,
                    forward_distance,
                    device,
                    num_points=path_points,
                    use_heading=use_heading,
                )
            ]
        ]

    output = _call_model_with_session_cache(
        model,
        session,
        prompt,
        total_frames,
        diffusion_steps,
        multi_prompt=False,
        constraint_lst=constraint_lst,
        cfg_weight=cfg_weight,
        num_samples=1,
        cfg_type="separated",
        post_processing=False,
        progress_bar=_no_progress,
    )
    _export_model_output_bvh(output, export_skeleton, out_path, fps)
    demo.clear_motions(session.client.client_id)
    demo.add_character_motion(
        session.client,
        export_skeleton,
        output["posed_joints"][0],
        output["global_rot_mats"][0],
        output.get("foot_contacts", torch.empty(1, 0, device=device))[0] if "foot_contacts" in output else None,
    )
    session.max_frame_idx = total_frames - 1
    demo.set_frame(session.client.client_id, 0)
    return {
        "loop_workflow": False,
        "generation_mode": "straight_path_prompt" if use_path_constraint else "prompt_only",
        "use_path_constraint": use_path_constraint,
        "forward_distance": forward_distance if use_path_constraint else None,
        "path_points": path_points if use_path_constraint else None,
        "style_strength": style_strength,
        "cfg_weight": cfg_weight,
        "stage1_path_diagnostics": _root_path_diagnostics(output, export_skeleton, forward_distance)
        if use_path_constraint
        else None,
    }


def _send_to_blender(path, blender_url, request_id="", metadata=None):
    body_payload = {"path": str(path), "request_id": str(request_id or "")}
    if metadata:
        body_payload.update(metadata)
    body = json.dumps(body_payload).encode("utf-8")
    req = urlrequest.Request(
        blender_url.rstrip("/") + "/import-bvh",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=20) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Blender returned HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8") or "{}")


def _generate_and_send(demo, payload):
    session = _primary_session(demo)
    client = session.client
    fps = float(session.model_fps)
    prompts, num_frames, total_duration = _parse_prompt_segments(payload, session, fps)
    seed = int(payload.get("seed") if payload.get("seed") is not None else 42)
    diffusion_steps = int(payload.get("diffusion_steps") if payload.get("diffusion_steps") is not None else 100)
    blender_url = str(
        payload.get("blender_url")
        if payload.get("blender_url") is not None
        else os.environ.get("KIMODO_BLENDER_BRIDGE_URL")
        or "http://127.0.0.1:8765"
    )
    send_to_blender = bool(blender_url.strip()) and not bool(payload.get("skip_blender_send", False))
    request_id = str(payload.get("request_id") or "")

    out_dir = Path(
        payload.get("output_dir")
        or os.environ.get("KIMODO_BRIDGE_OUTPUT_DIR")
        or Path(tempfile.gettempdir()) / "kimodo_blender_bridge"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    loop_workflow = bool(payload.get("loop_workflow", False))
    suffix = "_loop" if loop_workflow else ""
    filename = f"{_safe_stem(prompts[0])}{suffix}_{time.strftime('%Y%m%d_%H%M%S')}.bvh"
    out_path = out_dir / filename
    loop_info = {}
    blender_results = []
    original_path = None
    stage1_path = None
    stage2_path = None
    if loop_workflow:
        send_debug_comparisons = bool(payload.get("send_debug_comparisons", payload.get("send_original_comparison", False)))
        original_filename = f"{_safe_stem(prompts[0])}_original_{time.strftime('%Y%m%d_%H%M%S')}.bvh"
        original_path = out_dir / original_filename
        stage1_filename = f"{_safe_stem(prompts[0])}_stage1_straight_{time.strftime('%Y%m%d_%H%M%S')}.bvh"
        stage1_path = out_dir / stage1_filename
        stage2_filename = f"{_safe_stem(prompts[0])}_stage2_moving_{time.strftime('%Y%m%d_%H%M%S')}.bvh"
        stage2_path = out_dir / stage2_filename
        original_output = _export_unconstrained_original_bvh(
            demo,
            session,
            original_path,
            payload,
            prompts,
            num_frames,
            seed,
            diffusion_steps,
        )
        if send_debug_comparisons and send_to_blender:
            blender_results.append(
                _send_to_blender(
                    original_path,
                    blender_url,
                    request_id=request_id,
                    metadata={
                        "clip_role": "original",
                        "loop_workflow": False,
                        "style_strength": payload.get("style_strength"),
                    },
                )
            )
        loop_info = _export_two_stage_loop_bvh(
            demo,
            session,
            out_path,
            payload,
            prompts,
            num_frames,
            seed,
            diffusion_steps,
            stage1_out_path=stage1_path,
            stage2_out_path=stage2_path,
            original_output=original_output,
        )
        if send_debug_comparisons and send_to_blender:
            blender_results.append(
                _send_to_blender(
                    stage1_path,
                    blender_url,
                    request_id=request_id,
                    metadata={
                        "clip_role": "stage1",
                        "loop_workflow": False,
                        "style_strength": payload.get("style_strength"),
                        "path_points": loop_info.get("path_points"),
                        "cfg_weight": loop_info.get("cfg_weight"),
                    },
                )
            )
            blender_results.append(
                _send_to_blender(
                    stage2_path,
                    blender_url,
                    request_id=request_id,
                    metadata={
                        "clip_role": "stage2",
                        "loop_workflow": False,
                        "style_strength": payload.get("style_strength"),
                        "path_points": loop_info.get("path_points"),
                        "cfg_weight": loop_info.get("cfg_weight"),
                    },
                )
            )
    else:
        loop_info = _export_straight_prompt_bvh(
            demo,
            session,
            out_path,
            payload,
            prompts,
            num_frames,
            seed,
            diffusion_steps,
        )
    if send_to_blender:
        loop_metadata = dict(loop_info)
        loop_metadata["clip_role"] = "loop"
        blender_results.append(_send_to_blender(out_path, blender_url, request_id=request_id, metadata=loop_metadata))
    result = {
        "ok": True,
        "bridge_version": _BRIDGE_VERSION,
        "request_id": request_id,
        "path": str(out_path),
        "original_path": str(original_path) if original_path else None,
        "stage1_path": str(stage1_path) if stage1_path else None,
        "stage2_path": str(stage2_path) if stage2_path else None,
        "prompt": prompts[0],
        "prompts": prompts,
        "num_frames": num_frames,
        "segment_durations": [frame_count / fps for frame_count in num_frames],
        "duration": total_duration,
        "loop_workflow": loop_workflow,
        "blender_url": blender_url,
        "blender_result": blender_results[-1] if blender_results else None,
        "blender_results": blender_results,
    }
    result.update(loop_info)
    return result


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
            self._send_json(200, {"ok": True, "bridge_version": _BRIDGE_VERSION})
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
