"""Global SI motion solvers; candidate generation never claims native quality."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from .motion_context import MotionInputError, SolverResult, validate_samples
from .motion_math import hemisphere_continuous, solve_two_bone, temporal_operators


def repair_rotation_spikes(wxyz, time_s, *, spike_angle_rad, editable_mask=None, locks=None,
                           max_duration_s=0.1):
    """Repair isolated outliers only; retain gestures and pi chart crossings."""
    q = hemisphere_continuous(wxyz)
    times = np.asarray(time_s, dtype=float)
    if (times.shape != (len(q),) or not np.isfinite(times).all() or np.any(np.diff(times) <= 0)
            or not np.isfinite([spike_angle_rad, max_duration_s]).all()
            or min(spike_angle_rad, max_duration_s) <= 0):
        raise MotionInputError("INVALID_POLICY", "invalid spike policy/time grid")
    editable = np.ones(len(q), dtype=bool) if editable_mask is None else np.asarray(editable_mask, dtype=bool)
    locked = np.zeros(len(q), dtype=bool) if locks is None else np.asarray(locks, dtype=bool)
    if editable.shape != (len(q),) or locked.shape != (len(q),):
        raise MotionInputError("INVALID_POLICY", "invalid spike lock coverage")
    r = Rotation.from_quat(q[:, [1, 2, 3, 0]])
    out, corrected, ambiguous = q.copy(), [], []
    for i in range(1, len(q) - 1):
        if not editable[i] or locked[i] or locked[i - 1] or locked[i + 1]:
            continue
        neighbors = (r[i - 1].inv() * r[i + 1]).magnitude()
        interpolation = Slerp(times[[i - 1, i + 1]], r[[i - 1, i + 1]])([times[i]])[0]
        error = (r[i].inv() * interpolation).magnitude()
        if error > spike_angle_rad:
            if neighbors <= np.radians(5) and times[i + 1] - times[i - 1] <= max_duration_s:
                out[i] = interpolation.as_quat()[[3, 0, 1, 2]]
                corrected.append(i)
            else:
                ambiguous.append(i)
    return {"quaternion_wxyz": hemisphere_continuous(out), "corrected_rows": corrected,
            "ambiguous_rows": ambiguous, "reason_codes": ["AMBIGUOUS_HIGH_FREQUENCY_MOTION"] if ambiguous else []}


@dataclass(frozen=True)
class KeyModel:
    frames: np.ndarray
    keys_by_id: dict
    mode_by_id: dict
    capability: str
    descriptor_digest: str | None = None
    source_fingerprint: str | None = None


def build_key_model(capture, rig, *, interpolation_capabilities=None, key_layout=None, verifier=None):
    descriptor_digest=source_fingerprint=None
    capability="declared_only"
    if key_layout is not None:
        from .motion_key_layout import verify_key_layout
        observed,descriptor_digest=verify_key_layout(key_layout,capture,verifier)
        source_fingerprint=observed.source_fingerprint
        interpolation_capabilities={}
        for driver in observed.drivers:
            if driver.channel!="position" or driver.space!=capture.space:
                continue
            modes=set(driver.segment_modes)
            # Explicit observation of *no* controller/blend/cycle influence is
            # required; an absent influence entry is not proof of independence.
            if (set(driver.influences)!={"controllers","blend","cycle"}
                    or any(driver.influences.values()) or driver.reason_codes
                    or modes-set(("LINEAR","STEP"))):
                raise MotionInputError("INTERPOLATION_MODEL_UNVERIFIED","native evaluator for nonlinear or influenced keys is unavailable")
            if driver.native_model not in observed.qualified_models:
                raise MotionInputError("INTERPOLATION_MODEL_UNVERIFIED","driver model is not in the authenticated evaluator qualification")
            interpolation_capabilities[driver.object_id]={"frames":driver.frames,"segment_modes":driver.segment_modes,
                                                          "mode":"CONSTANT" if len(driver.frames)==1 else None}
        capability="verified"
    interpolation_capabilities=interpolation_capabilities or {}
    keys, modes = {}, {}
    for object_id in rig.writable_ids:
        spec = interpolation_capabilities.get(object_id)
        if not isinstance(spec, dict) or not spec.get("frames"):
            raise MotionInputError("KEY_LAYOUT_INSUFFICIENT", f"missing keys: {object_id}")
        grid = np.asarray(spec["frames"])
        if grid.ndim!=1 or grid.dtype.kind not in "iu" or np.any(grid<0) or np.any(np.diff(grid) <= 0):
            raise MotionInputError("INVALID_POLICY", "key grids must be unique increasing integers")
        if np.any(grid<capture.context.frames[0]) or np.any(grid>capture.context.frames[-1]):
            raise MotionInputError("KEY_LAYOUT_INSUFFICIENT","key influence extends outside the captured impact interval")
        keys[object_id]=grid
        modes[object_id]=(tuple(spec["segment_modes"]) if len(grid)>1 and "segment_modes" in spec
                          else str(spec.get("mode","unknown")))
    if any((isinstance(mode,tuple) and (len(mode)!=len(keys[key])-1 or set(mode)-{"LINEAR","STEP"}))
           or (not isinstance(mode,tuple) and mode not in ("LINEAR","STEP","CONSTANT"))
           for key,mode in modes.items()):
        raise MotionInputError("INTERPOLATION_MODEL_UNVERIFIED","unsupported declared interpolation")
    return KeyModel(capture.context.frames, keys, modes, capability,descriptor_digest,source_fingerprint)


def fit_keys(goal, original, key_model, constraints, limits):
    """Constrained least squares on each driver's own grid; no key intersection."""
    import osqp
    import scipy.sparse as sp
    from .motion_cleanup import linear_interpolation
    from .motion_math import temporal_operators
    targets, residuals = {}, {}
    if not goal:
        return SolverResult("failed", ["EMPTY_GOAL"])
    if any(not np.isfinite(value) or value<0 for value in limits.values() if isinstance(value,(int,float))):
        return SolverResult("failed",["INVALID_POLICY"])
    if type(limits.get("fit_iterations",10000)) is not int or not 0<limits.get("fit_iterations",10000)<=1_000_000:
        return SolverResult("failed",["INVALID_POLICY"])
    from .capture import estimate_motion_resources,enforce_motion_budget
    estimate=estimate_motion_resources(len(original.context.frames),
        {key:len(key_model.keys_by_id.get(key,())) for key in goal},
        retained_capture_bytes=sum(value.nbytes for value in original.position_m.values())*3,
        factorization_workspace_bytes=limits.get("factorization_workspace_bytes"))
    try:
        enforce_motion_budget(estimate,{"max_variables":1_000_000,"max_nonzeros":2_000_000,
                                       "max_memory_bytes":512*1024*1024,**limits})
    except MotionInputError as exc:
        return SolverResult("failed",[exc.code],report={"resources":estimate})
    d1, d2 = temporal_operators(original.context.time_s)
    for object_id, wanted in goal.items():
        if object_id not in key_model.keys_by_id:
            return SolverResult("failed", ["KEY_LAYOUT_INSUFFICIENT"])
        wanted = np.asarray(wanted, dtype=float)
        if wanted.shape != (len(original.context.frames), 3) or not np.isfinite(wanted).all():
            return SolverResult("failed", ["INVALID_GOAL"])
        keys = key_model.keys_by_id[object_id]
        if not set(map(int,keys))<=set(map(int,original.context.frames)):
            return SolverResult("failed",["KEY_LAYOUT_INSUFFICIENT"],report={"detail":"original authored key values were not captured"})
        mode = key_model.mode_by_id[object_id]
        b = linear_interpolation(original.context.frames, keys)
        if mode == "STEP" or isinstance(mode,tuple):
            index = np.clip(np.searchsorted(keys, original.context.frames, side="right") - 1, 0, len(keys) - 1)
            if mode=="STEP":
                b = sp.csr_matrix((np.ones(len(index)), (np.arange(len(index)), index)), shape=b.shape)
            else:
                b=b.tolil()
                for row,key_index in enumerate(index):
                    if key_index<len(mode) and mode[key_index]=="STEP":
                        b.rows[row]=[int(key_index)];b.data[row]=[1.]
                b=b.tocsr()
        base = np.asarray(original.position_m[object_id])
        original_keys = np.column_stack([np.interp(keys, original.context.frames, base[:, axis]) for axis in range(3)])
        smooth = float(limits.get("velocity_weight", 0.01)) * (d1 @ b).T @ (d1 @ b)
        smooth += float(limits.get("acceleration_weight", 0.001)) * (d2 @ b).T @ (d2 @ b)
        hessian = (b.T @ b + smooth + sp.identity(len(keys)) * 1e-10).tocsc()
        cap = float(limits.get("position_correction_m", 0.03))
        output = np.empty_like(original_keys)
        for axis in range(3):
            lower, upper = original_keys[:, axis] - cap, original_keys[:, axis] + cap
            locks = constraints.get(object_id, {})
            for frame, position in locks.items():
                at = np.where(keys == int(frame))[0]
                if not len(at):
                    return SolverResult("failed", ["KEY_LAYOUT_INSUFFICIENT"])
                lower[at] = upper[at] = float(position[axis])
            linear = -2 * (b.T @ wanted[:, axis] + smooth @ original_keys[:, axis])
            solver = osqp.OSQP()
            solver.setup(sp.triu(2 * hessian).tocsc(), linear, sp.identity(len(keys), format="csc"),
                         lower, upper, verbose=False, eps_abs=1e-8, eps_rel=1e-8,
                         max_iter=int(limits.get("fit_iterations",10000)))
            result = solver.solve(raise_error=False)
            if (result.info.status not in ("solved", "solved inaccurate") or result.x is None
                    or not np.isfinite(result.x).all() or result.info.prim_res > 1e-6
                    or result.info.dual_res > 1e-6):
                return SolverResult("failed", ["KEY_FIT_FAILED"], report={"solver_status": result.info.status})
            output[:, axis] = result.x
        residual = np.linalg.norm(b @ output - wanted, axis=1)
        residuals[object_id] = float(residual.max())
        if residual.max() > float(limits.get("fit_error_m", 0.0005)):
            return SolverResult("failed", ["KEY_LAYOUT_INSUFFICIENT"], report={"fit_residual_m": residuals})
        targets[object_id] = {"frames": keys.tolist(), "position_m": output}
    return SolverResult("candidate", values=targets, report={"fit_residual_m": residuals,
                         "prediction_model": key_model.capability, "runtime_quality": "unverified",
                         "key_layout_digest":key_model.descriptor_digest,"model_source_fingerprint":key_model.source_fingerprint,
                         "sample_frames":original.context.frames.tolist(),"resources":estimate})


def _refinement_interpolant(frames, keys, modes):
    """The observed frame-domain LINEAR/STEP model, over the complete grid."""
    import scipy.sparse as sp
    rows, columns, values = [], [], []
    for row, frame in enumerate(frames):
        left = int(np.clip(np.searchsorted(keys, frame, side="right") - 1, 0, len(keys) - 1))
        rows.append(row); columns.append(left)
        if left == len(keys) - 1 or frame <= keys[0] or modes[left] == "STEP":
            values.append(1.)
        else:
            alpha = float(frame - keys[left]) / (keys[left + 1] - keys[left])
            values.append(1. - alpha)
            rows.append(row); columns.append(left + 1); values.append(alpha)
    return sp.csr_matrix((values, (rows, columns)), shape=(len(frames), len(keys)))


def _fit_refinement_grid(original, base, wanted, keys, modes, original_values, locks, cap, limits):
    """Eliminate old keys exactly; solve only new values against all samples."""
    import osqp
    import scipy.sparse as sp
    frames = original.context.frames
    if all(frame in original_values for frame in keys):
        # No insertion means the independently observed source remains exact;
        # native float32 cache rounding is not a reason to invent old writes.
        return base.copy(), {}
    b = _refinement_interpolant(frames, keys, modes)
    old_columns = [i for i, frame in enumerate(keys) if frame in original_values]
    new_columns = [i for i, frame in enumerate(keys) if frame not in original_values]
    fixed = b[:, old_columns] @ np.asarray([original_values[keys[i]] for i in old_columns])
    z = b[:, new_columns].tocsc()
    d1, d2 = temporal_operators(original.context.time_s)
    v, a = d1 @ z, d2 @ z
    velocity, acceleration = limits.get("velocity_weight", .01), limits.get("acceleration_weight", .001)
    h = (z.T @ z + velocity * v.T @ v + acceleration * a.T @ a
         + sp.identity(len(new_columns)) * 1e-10).tocsc()
    frame_rows = {int(frame): row for row, frame in enumerate(frames)}
    lock_frames = sorted(locks)
    lock_rows = [frame_rows[frame] for frame in lock_frames]
    matrix = sp.vstack((sp.identity(len(new_columns), format="csc"), z, z[lock_rows]), format="csc")
    new_base = base[[frame_rows[keys[i]] for i in new_columns]]
    output = np.empty((len(new_columns), 3))
    for axis in range(3):
        lock_values = np.asarray([locks[frame][axis] - fixed[frame_rows[frame], axis] for frame in lock_frames])
        lower = np.concatenate((new_base[:, axis] - cap, base[:, axis] - fixed[:, axis] - cap, lock_values))
        upper = np.concatenate((new_base[:, axis] + cap, base[:, axis] - fixed[:, axis] + cap, lock_values))
        linear = -2 * (z.T @ (wanted[:, axis] - fixed[:, axis])
            + velocity * v.T @ (d1 @ (base[:, axis] - fixed[:, axis]))
            + acceleration * a.T @ (d2 @ (base[:, axis] - fixed[:, axis])) + new_base[:, axis] * 1e-10)
        solver = osqp.OSQP()
        solver.setup(sp.triu(2 * h).tocsc(), linear, matrix, lower, upper,
                     verbose=False, eps_abs=1e-8, eps_rel=1e-8, max_iter=limits.get("fit_iterations", 10000))
        result = solver.solve(raise_error=False)
        if (result.info.status not in ("solved", "solved inaccurate") or result.x is None
                or not np.isfinite(result.x).all() or result.info.prim_res > 1e-6 or result.info.dual_res > 1e-6):
            raise MotionInputError("KEY_FIT_FAILED", "global insertion fit: " + result.info.status)
        output[:, axis] = result.x
    predicted = fixed + z @ output
    # These are feasibility checks, never post-solve clipping or replacement.
    if np.max(np.linalg.norm(predicted - base, axis=1)) > cap + 1e-9:
        raise MotionInputError("ORIGINAL_INTENT_VIOLATION", "insertion fit exceeds the original position envelope")
    if any(np.linalg.norm(predicted[frame_rows[frame]] - value) > 1e-8 for frame, value in locks.items()):
        raise MotionInputError("INTENT_LOCK_VIOLATION", "global insertion fit changes a protected pose")
    return predicted, {keys[column]: output[index] for index, column in enumerate(new_columns)}


def refine_sparse_keys(goal, original, rig, intent, constraints, limits, *, key_layout, verifier,
                       allow_key_insertion=False, max_added_keys=0):
    """Propose bounded independent local position keys; never issue native proof.

    The existing ``fit_keys`` path is unchanged. This explicit opt-in route
    fixes every original key, greedily selects the largest eligible residual
    (earliest frame breaks ties), then globally refits all proposed keys.
    Positions returned in additions are solver-space metres, not native write
    vectors. Tangents and actual topology authority require the native planner.
    """
    from bisect import bisect_right
    from .capture import canonical_digest, estimate_motion_resources, enforce_motion_budget
    from .motion_key_layout import verify_key_layout
    if allow_key_insertion is not True or not intent.allow_key_insertion:
        return SolverResult("failed", ["KEY_INSERTION_NOT_AUTHORIZED"])
    if type(max_added_keys) is not int or not 0 <= max_added_keys <= 8:
        return SolverResult("failed", ["INVALID_POLICY"])
    names = {"position_correction_m", "velocity_weight", "acceleration_weight", "fit_error_m",
             "fit_iterations", "max_variables", "max_nonzeros", "max_memory_bytes", "factorization_workspace_bytes",
             "require_factorization_bound"}
    if (not isinstance(limits, dict) or set(limits) - names or not isinstance(constraints, dict)
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value < 0
                   for key, value in limits.items() if key != "require_factorization_bound")
            or type(limits.get("require_factorization_bound", False)) is not bool
            or type(limits.get("fit_iterations", 10000)) is not int
            or not 0 < limits.get("fit_iterations", 10000) <= 1_000_000):
        return SolverResult("failed", ["INVALID_POLICY"])
    try:
        observed, layout_digest = verify_key_layout(key_layout, original, verifier)
        if len(observed.drivers) != 1 or not isinstance(goal, dict) or len(goal) != 1:
            raise MotionInputError("KEY_INSERTION_ADAPTER_UNVERIFIED", "one observed independent position driver required")
        driver = observed.drivers[0]
        object_id = driver.object_id
        models = {"linear_position_independent_v1", "step_position_independent_v1",
                  "piecewise_linear_step_position_independent_v1"}
        if (set(goal) != {object_id} or original.space != "local" or driver.space != "local"
                or driver.channel != "position" or driver.key_id_kind != "layer_frame_locator"
                or driver.layer_objects != (object_id,) or driver.data_mode != "Animation" or not driver.data_id
                or driver.native_model not in models or driver.native_model not in observed.qualified_models
                or driver.reason_codes or set(driver.influences) != {"controllers", "blend", "cycle"}
                or any(driver.influences.values()) or not 2 <= len(driver.frames) <= 16
                or set(driver.segment_modes) - {"LINEAR", "STEP"}
                or original.object_ids != (object_id,) or rig.writable_ids != frozenset((object_id,))
                or driver.key_ids != tuple(driver.layer_id + ":" + str(frame) for frame in driver.frames)):
            raise MotionInputError("KEY_INSERTION_ADAPTER_UNVERIFIED", "descriptor is outside the finite local independent domain")
        frames = original.context.frames
        if (not 3 <= len(frames) <= 33 or not np.array_equal(frames, np.arange(len(frames)))
                or not set(driver.frames) <= set(map(int, frames))):
            raise MotionInputError("KEY_LAYOUT_INSUFFICIENT", "complete bounded original key/sample grid required")
        validate_samples(original, {object_id: ("position",)})
        wanted = np.asarray(goal[object_id], dtype=float)
        base = original.position_m[object_id]
        if wanted.shape != base.shape or not np.isfinite(wanted).all():
            raise MotionInputError("INVALID_GOAL", "finite complete position goal required")
        if len(driver.values) != len(driver.frames) or len(driver.tangents) != len(driver.frames):
            raise MotionInputError("KEY_LAYOUT_INSUFFICIENT", "original values and tangents are incomplete")
        raw_values = original.context.positions_to_solver(driver.values)
        frame_rows = {int(frame): row for row, frame in enumerate(frames)}
        if not np.array_equal(raw_values, base[[frame_rows[frame] for frame in driver.frames]]):
            raise MotionInputError("INCOMPLETE_CAPTURE", "authored keys differ from the exact source capture")
        projection = observed.raw_sample_projection
        samples = projection.get("samples")
        if (projection.get("space") != "local" or projection.get("frames") != frames.tolist()
                or not isinstance(samples, list) or len(samples) != len(frames)
                or any(not isinstance(row, dict) or row.get("id") != object_id or type(row.get("frame")) is not int
                       or row["frame"] != int(frame) for row, frame in zip(samples, frames, strict=True))):
            raise MotionInputError("INCOMPLETE_CAPTURE", "exact independent raw sample projection required")
        raw_samples = np.asarray([row.get("position") for row in samples], dtype=float)
        if (raw_samples.shape != base.shape or not np.isfinite(raw_samples).all()
                or not np.array_equal(original.context.positions_to_solver(raw_samples), base)):
            raise MotionInputError("INCOMPLETE_CAPTURE", "raw source projection differs from canonical capture")
        original_values = dict(zip(driver.frames, raw_values, strict=True))
        roles = [role for role, key in rig.role_ids.items() if key == object_id]
        cap = min([intent.correction_envelope.get("position_m", 0.), limits.get("position_correction_m", float("inf")),
                   *(intent.correction_envelope[role + ".position_m"] for role in roles
                     if role + ".position_m" in intent.correction_envelope)])
        grant = min(max_added_keys, int(intent.correction_envelope.get("added_keys", 0)), 16 - len(driver.frames))
        if set(constraints) - {object_id} or not isinstance(constraints.get(object_id, {}), dict):
            raise MotionInputError("INVALID_POLICY", "constraints escape the exact driver")
        locks = {}
        def lock(frame, value):
            if type(frame) is not int or frame not in frame_rows:
                raise MotionInputError("INVALID_POLICY", "position lock outside complete captured frame grid")
            value = np.asarray(value, dtype=float)
            if value.shape != (3,) or not np.isfinite(value).all() or (frame in locks and not np.array_equal(locks[frame], value)):
                raise MotionInputError("INTENT_LOCK_VIOLATION", "invalid or conflicting position lock")
            locks[frame] = value
        for frame, value in constraints.get(object_id, {}).items():
            lock(frame, value)
        for role in roles:
            for frame in intent.locked_roles_frames.get(role, ()):
                lock(frame, base[frame_rows[frame]] if frame in frame_rows else [])
            for frame, value in intent.key_pose_locks.get(role, {}).items():
                if len(value) == 3:
                    lock(frame, value)
        if rig.role_ids.get("root") == object_id and intent.root_policy == "preserve":
            for frame in frames:
                lock(int(frame), base[frame_rows[int(frame)]])
        for contact in intent.contacts:
            if rig.role_ids.get(contact.role) == object_id:
                for frame in (contact.first_frame, contact.last_frame):
                    lock(frame, base[frame_rows[frame]] if frame in frame_rows else [])
        for frame in frames:
            if not intent.editable_frames[0] <= frame <= intent.editable_frames[1]:
                lock(int(frame), base[frame_rows[int(frame)]])
        for row in driver.boundary_keys:
            if row.get("event") or row.get("locked"):
                frame = row.get("frame")
                lock(frame, base[frame_rows[frame]] if frame in frame_rows else [])
        if any(frame in original_values and not np.array_equal(value, original_values[frame]) for frame, value in locks.items()):
            raise MotionInputError("INTENT_LOCK_VIOLATION", "original key preservation conflicts with a declared pose")
        # Every retained full-grid array and the maximum refined topology is
        # reserved before creating interpolation/temporal matrices or OSQP.
        retained = sum(value.nbytes for value in original.position_m.values()) + wanted.nbytes
        retained += len(frames) * (3 * 8 * 5 + 8 * 12) + (len(driver.frames) + grant) * 3 * 8 * 4
        resources = estimate_motion_resources(len(frames), {object_id: len(driver.frames) + grant},
            variables=3 * grant, constraint_nonzeros=6 * len(frames) + 6 * len(locks) + 3 * grant,
            retained_capture_bytes=retained, factorization_workspace_bytes=limits.get("factorization_workspace_bytes"))
        enforce_motion_budget(resources, {"max_variables": 1_000_000, "max_nonzeros": 2_000_000,
                                         "max_memory_bytes": 512 * 1024 * 1024, **limits})
        keys = list(driver.frames)
        modes = list(driver.segment_modes)
        baseline_raw = _refinement_interpolant(frames, keys, modes) @ np.asarray(driver.values)
        baseline_raw_error = float(np.linalg.norm(baseline_raw - raw_samples, axis=1).max())
        if baseline_raw_error > 1e-5:
            raise MotionInputError("INTERPOLATION_MODEL_UNVERIFIED", "raw samples disagree with the qualified finite model")
        del baseline_raw
        predicted, values = _fit_refinement_grid(original, base, wanted, keys, modes, original_values, locks, cap, limits)
        selected = []
        tolerance = limits.get("fit_error_m", .0005)
        forbidden = set(locks) | {row["frame"] for row in driver.sections}
        while True:
            errors = np.linalg.norm(predicted - wanted, axis=1)
            maximum = float(errors.max())
            if maximum <= tolerance:
                if any(np.linalg.norm(predicted[frame_rows[frame]] - value) > 1e-8 for frame, value in locks.items()):
                    raise MotionInputError("INTENT_LOCK_VIOLATION", "fit does not satisfy every protected pose")
                additions = [{"object_id": object_id, "channel": "position", "layer_id": driver.layer_id,
                    "frame": frame, "position_m": values[frame].tolist(),
                    "mode": driver.segment_modes[bisect_right(driver.frames, frame) - 1]} for frame in sorted(selected)]
                return SolverResult("candidate" if additions else "no_change", values={"existing_writes": [],
                    "additions": additions, "predicted_position_m": {object_id: predicted.tolist()}}, report={
                    "fit_residual_m": {object_id: maximum}, "selected_frames": selected,
                    "original_topology_digest": canonical_digest([row.model_dump(mode="json") for row in observed.drivers]),
                    "key_layout_digest": layout_digest, "model_source_fingerprint": observed.source_fingerprint,
                    "capture_digest": canonical_digest(original.as_dict()), "context_digest": canonical_digest(original.context.as_dict()),
                    "source_binding_digest": canonical_digest(original.as_dict()["source_binding"]),
                    "baseline_raw_fit_scene_units": baseline_raw_error,
                    "sample_frames": frames.tolist(), "resources": resources, "runtime_quality": "unverified",
                    "position_units": "solver_metres", "selection_rule": "max_residual_then_earliest_frame"})
            if len(selected) >= grant:
                raise MotionInputError("KEY_LAYOUT_INSUFFICIENT", "finite insertion grant cannot fit the complete goal")
            eligible = [int(frame) for frame in frames if frame not in forbidden
                and intent.editable_frames[0] <= frame <= intent.editable_frames[1]
                and driver.frames[0] < frame < driver.frames[-1] and min(abs(int(frame) - key) for key in keys) >= 2]
            if not eligible:
                raise MotionInputError("KEY_LAYOUT_INSUFFICIENT", "no unlocked absent interior frame with the required two-frame gap")
            frame = max(eligible, key=lambda value: (errors[frame_rows[value]], -value))
            index = bisect_right(keys, frame)
            mode = modes[index - 1]
            keys.insert(index, frame); modes.insert(index, mode); selected.append(frame)
            # resources reserves the final grant, not just the current iterate.
            enforce_motion_budget(resources, {"max_variables": 1_000_000, "max_nonzeros": 2_000_000,
                                             "max_memory_bytes": 512 * 1024 * 1024, **limits})
            predicted, values = _fit_refinement_grid(original, base, wanted, keys, modes, original_values, locks, cap, limits)
    except MotionInputError as exc:
        return SolverResult("failed", [exc.code], report={"detail": str(exc),
            **({"resources": resources} if "resources" in locals() else {})})


def _skew(vector):
    x, y, z = vector
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])


def _sequence_resource_gate(batch, count, limits, *, constraint_nonzeros, retained_working_bytes=0):
    from .capture import estimate_motion_resources,enforce_motion_budget
    estimate=estimate_motion_resources(len(batch.context.frames),{},variables=count,
        constraint_nonzeros=constraint_nonzeros+count*6,
        retained_capture_bytes=sum(x.nbytes for x in batch.position_m.values())*3+retained_working_bytes,
        factorization_workspace_bytes=limits.get("factorization_workspace_bytes"))
    estimate["retained_working_bytes"]=retained_working_bytes
    enforce_motion_budget(estimate,{"max_variables":1_000_000,"max_nonzeros":2_000_000,
                                   "max_memory_bytes":512*1024*1024,**limits})
    return estimate


def _joint_angle_allowed(rig,role,first,middle,last):
    bounds=rig.joint_limits_rad.get(role)
    if bounds is None:
        return True
    if not isinstance(bounds,(list,tuple)) or len(bounds)!=2 or not np.isfinite(bounds).all() or bounds[0]>bounds[1]:
        raise MotionInputError("JOINT_LIMITS_UNAVAILABLE","hinge limits must be declared [min,max] radians")
    upper,lower=middle-first,last-middle
    denominator=np.linalg.norm(upper)*np.linalg.norm(lower)
    if denominator<1e-15:
        return False
    angle=np.arccos(np.clip(upper@lower/denominator,-1,1))
    return bounds[0]-1e-8<=angle<=bounds[1]+1e-8


def solve_arm_clearance_v2(batch, rig, surfaces, intent, limits):
    """One global SQP over both arms with exact post-IK and pair constraints.

    surfaces[side][row] is an evaluated TriangleSurface of the declared body
    obstacle. This host model predicts a candidate; it cannot certify reskinning.
    """
    import osqp
    import scipy.sparse as sp
    from .motion_geometry import segment_distance
    sides = [side for side in ("Left", "Right") if f"{side}.wrist" in rig.role_ids]
    n, count = len(batch.context.frames), 6 * len(batch.context.frames) * len(sides)
    if not sides or not surfaces:
        return SolverResult("unsupported", ["COLLISION_GEOMETRY_UNAVAILABLE"])
    required, base = {}, {}
    declared_lengths={}
    for side in sides:
        if side not in surfaces or len(surfaces[side]) != n:
            return SolverResult("unsupported", ["INCOMPLETE_CAPTURE"])
        for role in ("shoulder", "elbow", "wrist"):
            key = rig.role_ids.get(f"{side}.{role}")
            if key is None:
                return SolverResult("unsupported", ["RIG_MAPPING_AMBIGUOUS"])
            required[key] = ("position",)
        base[side] = [np.asarray(batch.position_m[rig.role_ids[f"{side}.{role}"]]) for role in ("shoulder", "elbow", "wrist")]
        lengths=(rig.bone_lengths_m.get(f"{side}.upper_arm"),rig.bone_lengths_m.get(f"{side}.forearm"))
        if any(length is None for length in lengths):
            return SolverResult("unsupported",["MISSING_BONE_LENGTHS"])
        declared_lengths[side]=lengths
    validate_samples(batch, required)
    cap = float(limits.get("position_correction_m", .03))
    margin = float(limits.get("collision_clearance_m", .002))
    tolerance = float(limits.get("collision_residual_m", .0001))
    radius = float(limits.get("arm_radius_m", .025))
    max_iterations = limits.get("iterations", 12)
    if (not np.isfinite([cap, margin, tolerance, radius]).all() or min(cap, tolerance, radius) <= 0
            or margin < 0 or isinstance(max_iterations, bool) or not isinstance(max_iterations, int) or not 0 < max_iterations <= 100):
        return SolverResult("failed", ["INVALID_POLICY"])
    try:
        resources=_sequence_resource_gate(batch,count,limits,constraint_nonzeros=count*50)
    except MotionInputError as exc:
        return SolverResult("unsupported",[exc.code],report={"detail":str(exc)})
    d1, d2 = temporal_operators(batch.context.time_s)
    hessian = sp.kron(sp.identity(len(sides)), sp.kron(sp.identity(n) + .01*d1.T@d1 + .001*d2.T@d2, sp.identity(6))).tocsc()
    current = np.zeros((len(sides), n, 6))
    history = []

    def points(side_index, row, value):
        shoulder, elbow, wrist = base[sides[side_index]]
        return shoulder[row], elbow[row] + value[:3], wrist[row] + value[3:]

    max_nonzeros=int(limits.get('max_nonzeros',2_000_000))
    if count*50>max_nonzeros:
        return SolverResult('unsupported',['RESOURCE_BUDGET_EXCEEDED'],report={'estimated_nonzeros':count*50})

    def dot(jacobian,value):
        return sum(coefficient*value[index] for index,coefficient in jacobian.items())

    def sparse_rows(rows):
        r,c,v=[],[],[]
        for row,values in enumerate(rows):
            for col,coefficient in values.items():
                if coefficient:
                    r.append(row);c.append(col);v.append(coefficient)
        if len(v)>max_nonzeros:
            raise MotionInputError('RESOURCE_BUDGET_EXCEEDED','global arm constraints exceed the sparse nonzero budget')
        return sp.csc_matrix((v,(r,c)),shape=(len(rows),count))

    def constraints(value):
        lower, jacobians, worst = [], [], 0.
        for s, side in enumerate(sides):
            for f in range(n):
                shoulder, elbow, wrist = points(s, f, value[s, f])
                surface=surfaces[side][f]
                for a, b, wa, wb in ((shoulder, elbow, 0., 1.), (elbow, wrist, 1., 0.)):
                    # Bound sample spacing by radius; endpoints alone miss long triangle interiors.
                    sample_count = max(3, int(np.ceil(np.linalg.norm(b-a)/max(radius*.5, .002)))+1)
                    if sample_count > 1000:
                        raise MotionInputError("RESOURCE_BUDGET_EXCEEDED", "arm collision sampling exceeds bounded mesh budget")
                    for t in np.linspace(0, 1, sample_count):
                        point = a + t*(b-a)
                        query = surface.closest(point)
                        if query.signed_distance_m is None:
                            raise MotionInputError("COLLISION_SIGN_UNVERIFIED", "declared surface does not certify volume/patch sign")
                        residual = margin + radius - query.signed_distance_m
                        worst = max(worst, residual)
                        if residual > -cap:
                            normal = query.oriented_normal
                            jacobian = {}
                            start = (s*n+f)*6
                            elbow_weight, wrist_weight = ((t, 0.) if wa == 0 else (1-t, t))
                            for axis in range(3):
                                jacobian[start+axis]=elbow_weight*normal[axis]
                                jacobian[start+3+axis]=wrist_weight*normal[axis]
                            jacobians.append(jacobian)
                            lower.append(residual + dot(jacobian,value.reshape(-1)))
                            if (len(jacobians)*12>max_nonzeros
                                    or resources["estimated_peak_bytes"]+len(jacobians)*1024>limits.get("max_memory_bytes",512*1024*1024)):
                                raise MotionInputError("RESOURCE_BUDGET_EXCEEDED","arm constraint assembly exceeds its resource budget")
        # Both arms move in this same iterate, including segment interiors.
        for left in range(len(sides)):
            for right in range(left+1, len(sides)):
                for f in range(n):
                    lp, rp = points(left, f, value[left,f]), points(right, f, value[right,f])
                    for li in (0,1):
                        for ri in (0,1):
                            distance, closest_l, closest_r = segment_distance(lp[li], lp[li+1], rp[ri], rp[ri+1], return_points=True)
                            residual = 2*radius + margin-distance
                            worst = max(worst, residual)
                            if residual <= -2*cap:
                                continue
                            vector = closest_l-closest_r
                            if distance < 1e-10:
                                vector = np.cross(lp[li+1]-lp[li], rp[ri+1]-rp[ri])
                                if np.linalg.norm(vector) < 1e-10:
                                    vector = np.array([1.,0.,0.])
                            normal = vector / np.linalg.norm(vector)
                            jacobian = {}
                            for side_index, chain, seg, point, sign in ((left,lp,li,closest_l,1),(right,rp,ri,closest_r,-1)):
                                edge = chain[seg+1]-chain[seg]
                                t = np.clip((point-chain[seg]) @ edge/max(edge@edge,1e-20),0,1)
                                weights = (t,0.) if seg == 0 else (1-t,t)
                                index=(side_index*n+f)*6
                                for axis in range(3):
                                    jacobian[index+axis]=jacobian.get(index+axis,0)+sign*weights[0]*normal[axis]
                                    jacobian[index+3+axis]=jacobian.get(index+3+axis,0)+sign*weights[1]*normal[axis]
                            jacobians.append(jacobian)
                            lower.append(residual+dot(jacobian,value.reshape(-1)))
                            if (len(jacobians)*12>max_nonzeros
                                    or resources["estimated_peak_bytes"]+len(jacobians)*1024>limits.get("max_memory_bytes",512*1024*1024)):
                                raise MotionInputError("RESOURCE_BUDGET_EXCEEDED","coupled arm constraint assembly exceeds its resource budget")
        return jacobians, lower, max(worst, 0.)

    try:
        for iteration in range(max_iterations):
            jacobians, lower, residual = constraints(current)
            history.append({"iteration":iteration,"collision_residual_m":residual})
            if residual <= tolerance:
                status = "no_change" if np.max(np.abs(current)) < 1e-10 else "candidate"
                break
            flat=current.reshape(-1)
            lo, hi = np.maximum(-cap,flat-.01),np.minimum(cap,flat+.01)
            equalities, targets = [], []
            for s,side in enumerate(sides):
                shoulder0,elbow0,wrist0=base[side]
                for f,frame in enumerate(batch.context.frames):
                    shoulder,elbow,wrist=points(s,f,current[s,f])
                    for role,offset in (("elbow",0),("wrist",3)):
                        key=rig.role_ids[f"{side}.{role}"]
                        if key not in rig.writable_ids or not intent.editable_frames[0]<=frame<=intent.editable_frames[1] or frame in intent.locked_roles_frames.get(f"{side}.{role}",()):
                            index=(s*n+f)*6+offset
                            lo[index:index+3]=hi[index:index+3]=0
                    for segment,first,second,original in ((0,shoulder,elbow,elbow0[f]-shoulder0[f]),(1,elbow,wrist,wrist0[f]-elbow0[f])):
                        direction=second-first
                        length=np.linalg.norm(direction)
                        if length<1e-12:
                            raise MotionInputError("INVALID_BONE_LENGTH","zero arm bone")
                        direction/=length
                        jac={}; index=(s*n+f)*6
                        for axis in range(3):
                            jac[index+axis]=direction[axis] if segment==0 else -direction[axis]
                            if segment==1: jac[index+3+axis]=direction[axis]
                        equalities.append(jac); targets.append(declared_lengths[side][segment]-length+dot(jac,flat))
            slack_count=len(jacobians)
            resources=_sequence_resource_gate(batch,count+slack_count,limits,
                constraint_nonzeros=sum(map(len,jacobians))+sum(map(len,equalities))+slack_count*3)
            collision=sp.hstack([sparse_rows(jacobians),sp.identity(slack_count)],format="csc")
            bone=sp.hstack([sparse_rows(equalities),sp.csc_matrix((len(equalities),slack_count))],format="csc")
            a=sp.vstack([collision,bone,sp.identity(count+slack_count)],format="csc")
            objective=sp.block_diag([hessian,sp.identity(slack_count)*1e6],format="csc")
            solver=osqp.OSQP()
            solver.setup(sp.triu(2*objective).tocsc(),np.zeros(count+slack_count),a,np.r_[lower,targets,lo,np.zeros(slack_count)],
                         np.r_[np.full(len(lower),np.inf),targets,hi,np.full(slack_count,np.inf)],verbose=False,eps_abs=1e-8,eps_rel=1e-8,max_iter=20000)
            result=solver.solve(raise_error=False)
            history[-1]["solver_status"]=result.info.status
            dual_scale=max(1.,float(np.linalg.norm(2*objective@result.x,ord=np.inf))) if result.x is not None and np.isfinite(result.x).all() else 1.
            history[-1]["primal_residual"]=float(result.info.prim_res)
            history[-1]["normalized_dual_residual"]=float(result.info.dual_res/dual_scale)
            if result.info.status not in ("solved","solved inaccurate") or result.x is None or not np.isfinite(result.x).all() or result.info.prim_res>1e-7 or result.info.dual_res/dual_scale>1e-7:
                return SolverResult("failed",["ARM_COLLISION_REACH_CONFLICT"],report={"iterations":history})
            updated=result.x[:count].reshape(current.shape)
            for s,side in enumerate(sides):
                shoulder,elbow,wrist=base[side]
                for f in range(n):
                    ik=solve_two_bone(shoulder[f],elbow[f]+updated[s,f,:3],wrist[f]+updated[s,f,3:],
                                      *declared_lengths[side],
                                      pole_axis=rig.joint_axes.get(f"{side}.elbow_pole"))
                    if ik.status!="candidate":
                        return SolverResult("failed",["ARM_COLLISION_REACH_CONFLICT"],report={"iterations":history})
                    if not _joint_angle_allowed(rig,f"{side}.elbow",shoulder[f],ik.elbow_m,ik.wrist_m):
                        return SolverResult("failed",["JOINT_LIMIT_VIOLATION"],report={"frame":int(batch.context.frames[f])})
                    updated[s,f,:3]=ik.elbow_m-elbow[f]
            if np.max(np.abs(updated-current))<1e-10:
                return SolverResult("failed",["SOLVE_STALLED"],report={"iterations":history})
            current=updated
        else:
            status="candidate" if constraints(current)[2]<=tolerance else "failed"
        if status=="failed":
            return SolverResult("failed",["SOLVE_BUDGET_EXHAUSTED"],report={"iterations":history})
    except MotionInputError as exc:
        return SolverResult("unsupported",[exc.code],report={"detail":str(exc)})
    values={}
    for s,side in enumerate(sides):
        for role,index in (("elbow",0),("wrist",3)):
            delta=current[s,:,index:index+3]
            if np.linalg.norm(delta,axis=1).max(initial=0)>cap+1e-8:
                return SolverResult("failed",["CORRECTION_ENVELOPE_EXCEEDED"])
            values[rig.role_ids[f"{side}.{role}"]]=batch.position_m[rig.role_ids[f"{side}.{role}"]]+delta
    return SolverResult(status,values={"position_m":values},report={"iterations":history,"runtime_quality":"unverified",
                        "prediction_model":"coupled_capsules_triangle_surface","coverage":"sampled_frames","resources":resources})


def solve_contacts_v2(batch, rig, supports, contacts, intent, limits):
    """One global sequential sparse QP for foot translation and angular corrections.

    The original root is fixed. Knees are solved exactly after the foot targets;
    original heel/ball/toe articulation and approved support-relative anchors persist.
    """
    import osqp
    import scipy.sparse as sp
    from .motion_quality import contact_metrics
    if not contacts:
        return SolverResult("unsupported", ["CONTACT_INTENT_AMBIGUOUS"])
    if intent.action != "repair" or intent.root_policy != "preserve":
        return SolverResult("unsupported", ["UNSUPPORTED_ROOT_POLICY"])
    n = len(batch.context.frames)
    sides = sorted({contact.role.split(".")[0] for contact in contacts if contact.mode != "free"})
    if not sides:
        return SolverResult("no_change", report={"constraints_checked": True, "all_contacts_free": True})
    required = {}
    for side in sides:
        for suffix in ("ankle", "hip", "knee"):
            role = f"{side}.{suffix}"
            if role not in rig.role_ids:
                return SolverResult("unsupported", ["RIG_ADAPTER_UNVERIFIED"], report={"missing_role": role})
            required[rig.role_ids[role]] = ("position",)
    for contact in contacts:
        if contact.role not in rig.role_ids or contact.support_id not in supports:
            return SolverResult("unsupported", ["CONTACT_INTENT_AMBIGUOUS"])
        required[rig.role_ids[contact.role]] = ("position",)
    validate_samples(batch, required)
    try:
        baseline = contact_metrics(batch, rig, supports, contacts)
    except MotionInputError as exc:
        return SolverResult("unsupported", [exc.code])
    gap_limit = float(limits.get("contact_gap_m", 0.002))
    drift_limit = float(limits.get("contact_drift_m", 0.002))
    if all(metric["max"] <= (gap_limit if name == "contact_gap_m" else drift_limit)
           for name, metric in baseline.items()):
        return SolverResult("no_change", report={"constraints_checked": True, "baseline": baseline})
    count = 6 * n * len(sides)
    contact_rows=sum(int(np.searchsorted(batch.context.frames,contact.last_frame,side="right")
                         -np.searchsorted(batch.context.frames,contact.first_frame,side="left"))
                     for contact in contacts if contact.mode!="free")
    # prepared_contacts keeps local, target, world normals and local normals
    # for the full clip for EACH contact, even if its active interval is short.
    # These arrays coexist with the sparse solve and every subsequent iterate.
    prepared_contact_bytes=sum(contact.mode!="free" for contact in contacts)*n*4*3*np.dtype(np.float64).itemsize
    try:
        resources=_sequence_resource_gate(batch,count,limits,constraint_nonzeros=max(count*36,contact_rows*18),
                                          retained_working_bytes=prepared_contact_bytes)
    except MotionInputError as exc:
        return SolverResult("unsupported",[exc.code],report={"detail":str(exc)})
    d1, d2 = temporal_operators(batch.context.time_s)
    smooth = (sp.identity(n) + 0.01 * d1.T @ d1 + 0.001 * d2.T @ d2).tocsc()
    hessian = sp.kron(sp.identity(len(sides)), sp.kron(smooth, sp.identity(6))).tocsc()
    current = np.zeros((len(sides), n, 6))
    frame_to_row = {int(frame): i for i, frame in enumerate(batch.context.frames)}
    prepared_contacts = []
    for contact in contacts:
        if contact.mode == "free":
            continue
        support = supports[contact.support_id]
        geometry = support.geometry
        q = hemisphere_continuous(support.rotation_wxyz)
        r = Rotation.from_quat(q[:, [1, 2, 3, 0]])
        point = batch.position_m[rig.role_ids[contact.role]]
        rows = [i for i, frame in enumerate(batch.context.frames)
                if contact.first_frame <= frame <= contact.last_frame]
        if not rows or contact.first_frame not in frame_to_row or contact.last_frame not in frame_to_row:
            return SolverResult("failed", ["INCOMPLETE_CAPTURE"])
        local = r.inv().apply(point - support.origin_m)
        effective=contact
        if contact.anchor_local_m is None and isinstance(geometry,dict) and geometry.get("kind")=="plane":
            normal=np.asarray(geometry["normal_local"],dtype=float)
            normal/=np.linalg.norm(normal)
            anchor=local[rows[0]].copy()
            anchor-=(anchor@normal-float(geometry.get("offset_m",0)))*normal
            effective=contact.model_copy(update={"anchor_local_m":tuple(anchor)})
        try:
            anchors,normal,_=support.contact_reference(effective,local)
        except MotionInputError as exc:
            return SolverResult("unsupported",[exc.code],report={"detail":str(exc)})
        target=support.anchors_world(anchors)
        normals=r.apply(normal)
        prepared_contacts.append((effective, rows, point, target, normals, local, normal, geometry))
    log = []
    iterations = int(limits.get("iterations", 8))
    position_cap = float(limits.get("position_correction_m", 0.03))
    rotation_cap = float(limits.get("rotation_correction_rad", np.radians(15)))
    if not 0 < iterations <= 100 or min(position_cap, rotation_cap) <= 0:
        return SolverResult("failed", ["INVALID_POLICY"])
    targets = {}
    for iteration in range(iterations):
        rows, cols, data, rhs = [], [], [], []
        maximum = 0.0
        for contact, active_rows, original, target, normals, local, normal_local, geometry in prepared_contacts:
            side = sides.index(contact.role.split(".")[0])
            ankle = batch.position_m[rig.role_ids[f"{sides[side]}.ankle"]]
            for i in active_rows:
                delta = current[side, i]
                relative = Rotation.from_rotvec(delta[3:]).apply(original[i] - ankle[i])
                point = ankle[i] + delta[:3] + relative
                jacobian = np.column_stack([np.eye(3), -_skew(relative)])
                offset = side * n * 6 + i * 6
                if contact.mode == "sliding":
                    error = (target[i]-point) @ normals[i]
                    matrix, residual = normals[i][None, :] @ jacobian, np.array([error])
                else:
                    matrix, residual = jacobian, target[i] - point
                maximum = max(maximum, float(np.linalg.norm(residual)))
                for j, residual_value in enumerate(residual):
                    row = len(rhs)
                    for axis in range(6):
                        rows.append(row)
                        cols.append(offset + axis)
                        data.append(float(matrix[j, axis]))
                    rhs.append(float(residual_value + matrix[j] @ delta))
        log.append({"iteration": iteration, "max_contact_residual_m": maximum})
        if maximum <= min(gap_limit, drift_limit):
            break
        try:
            resources=_sequence_resource_gate(batch,count,limits,constraint_nonzeros=len(data)+count*6,
                                              retained_working_bytes=prepared_contact_bytes)
        except MotionInputError as exc:
            return SolverResult("unsupported",[exc.code],report={"detail":str(exc)})
        a = sp.csc_matrix((data, (rows, cols)), shape=(len(rhs), count))
        cap = np.tile([position_cap] * 3 + [rotation_cap] * 3, n * len(sides))
        step = np.tile([0.01] * 3 + [np.radians(5)] * 3, n * len(sides))
        flat = current.reshape(-1)
        lower, upper = np.maximum(-cap, flat - step), np.minimum(cap, flat + step)
        for side_index, side in enumerate(sides):
            ankle_id = rig.role_ids[f"{side}.ankle"]
            for i, frame in enumerate(batch.context.frames):
                locked = (not intent.editable_frames[0] <= frame <= intent.editable_frames[1]
                          or frame in intent.locked_roles_frames.get(f"{side}.ankle", ()))
                if ankle_id not in rig.writable_ids or locked:
                    index = side_index * n * 6 + i * 6
                    lower[index:index + 6] = upper[index:index + 6] = 0
        # An elastic SQP objective can advance inside the trust region even
        # when the full anchor displacement is larger than one step. Final
        # nonlinear metrics remain hard acceptance conditions.
        contact_weight=1e6
        objective=(hessian+contact_weight*a.T@a).tocsc()
        linear=-2*contact_weight*np.asarray(a.T@np.asarray(rhs)).reshape(-1)
        matrix = sp.identity(count,format="csc")
        solver = osqp.OSQP()
        solver.setup(sp.triu(2 * objective).tocsc(), linear, matrix,
                     lower, upper, verbose=False,
                     eps_abs=1e-7, eps_rel=1e-7, max_iter=20000)
        result = solver.solve(raise_error=False)
        log[-1]["solver_status"] = result.info.status
        dual_scale=max(1.,float(np.linalg.norm(linear,ord=np.inf)))
        log[-1]["primal_residual"]=float(result.info.prim_res)
        log[-1]["normalized_dual_residual"]=float(result.info.dual_res/dual_scale)
        if (result.info.status not in ("solved", "solved inaccurate") or result.x is None
                or not np.isfinite(result.x).all() or result.info.prim_res > 1e-7 or result.info.dual_res/dual_scale > 1e-7):
            return SolverResult("failed", ["CONTACT_REACH_CONFLICT"], report={"iterations": log})
        next_value = result.x.reshape(current.shape)
        if np.max(np.abs(next_value - current)) < 1e-9:
            return SolverResult("failed", ["SOLVE_STALLED"], report={"iterations": log})
        current = next_value
    for side_index, side in enumerate(sides):
        ankle = batch.position_m[rig.role_ids[f"{side}.ankle"]]
        hip = batch.position_m[rig.role_ids[f"{side}.hip"]]
        knee = batch.position_m[rig.role_ids[f"{side}.knee"]]
        l1, l2 = rig.bone_lengths_m.get(f"{side}.upper_leg"), rig.bone_lengths_m.get(f"{side}.lower_leg")
        if l1 is None or l2 is None:
            return SolverResult("unsupported", ["MISSING_BONE_LENGTHS"])
        moved_ankle = ankle + current[side_index, :, :3]
        targets[rig.role_ids[f"{side}.ankle"]] = moved_ankle
        moved_knee = []
        for i in range(n):
            ik = solve_two_bone(hip[i], knee[i], moved_ankle[i], l1, l2,
                                pole_axis=rig.joint_axes.get(f"{side}.knee_pole"))
            if ik.status == "failed":
                return SolverResult("failed", ["CONTACT_REACH_CONFLICT"], report={"frame": int(batch.context.frames[i])})
            if not _joint_angle_allowed(rig,f"{side}.knee",hip[i],ik.elbow_m,ik.wrist_m):
                return SolverResult("failed",["JOINT_LIMIT_VIOLATION"],report={"frame":int(batch.context.frames[i])})
            moved_knee.append(ik.elbow_m)
        targets[rig.role_ids[f"{side}.knee"]] = np.asarray(moved_knee)
        for role, object_id in rig.role_ids.items():
            if role.startswith(f"{side}.") and role.split(".")[-1] in ("heel", "ball", "toe", "foot_direction", "foot_additional"):
                relative = batch.position_m[object_id] - ankle
                targets[object_id] = moved_ankle + Rotation.from_rotvec(current[side_index, :, 3:]).apply(relative)
    from dataclasses import replace
    checked = replace(batch, position_m={**batch.position_m, **targets})
    frozen_contacts=[item[0] for item in prepared_contacts]
    metrics = contact_metrics(checked, rig, supports, frozen_contacts,reference_batch=batch)
    if any(metric["max"] > (gap_limit if name == "contact_gap_m" else drift_limit)
           for name, metric in metrics.items()):
        return SolverResult("failed", ["SOLVE_BUDGET_EXHAUSTED"], report={"metrics": metrics, "iterations": log})
    for object_id in targets:
        delta = np.linalg.norm(targets[object_id] - batch.position_m[object_id], axis=1)
        if delta.max() > position_cap + 1e-7 or (delta.max() > 1e-9 and object_id not in rig.writable_ids):
            return SolverResult("failed", ["CORRECTION_ENVELOPE_EXCEEDED"])
    return SolverResult("candidate", values={"position_m": targets},
                        report={"metrics": metrics, "iterations": log, "runtime_quality": "unverified",
                                "root_preserved": True, "host_model_pass": True,"resources":resources})
