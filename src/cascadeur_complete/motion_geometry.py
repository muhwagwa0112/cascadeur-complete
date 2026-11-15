"""Exact triangle closest points, topology-aware sign, and bounded AABB queries."""
from __future__ import annotations

import heapq
import hashlib
from dataclasses import dataclass

import numpy as np

from .motion_context import MotionInputError


class ObservedSurfaceTrack:
    """Bounded in-memory evaluated geometry, normally decoded from a consumer.

    Hashes cover exact canonical float64 metres and int64 topology bytes. They
    identify observations; only the consumer/native verifier authenticates them.
    """
    def __init__(self,vertices_m,triangles,*,context,semantics="volume",orientation_observed=False,
                 memory_budget_bytes=256*1024*1024):
        vertices=np.asarray(vertices_m)
        faces=np.asarray(triangles)
        if (vertices.ndim!=3 or vertices.shape!=(len(context.frames),vertices.shape[1],3)
                or faces.ndim!=2 or faces.shape[1]!=3 or faces.dtype.kind not in "iu"
                or not np.isfinite(vertices).all()):
            raise MotionInputError("INCOMPLETE_CAPTURE","evaluated geometry has invalid frame/vertex/topology coverage")
        allocation=vertices.nbytes+faces.nbytes+vertices.size*8*2+faces.size*8
        if allocation>memory_budget_bytes:
            raise MotionInputError("RESOURCE_BUDGET_EXCEEDED","evaluated geometry conversion exceeds memory budget")
        self._vertices=np.array(vertices,dtype="<f8",copy=True)
        self._triangles=np.array(faces,dtype="<i8",copy=True)
        self._vertices.flags.writeable=self._triangles.flags.writeable=False
        self.context=context;self.frames=context.frames
        self.semantics=semantics;self.orientation_observed=orientation_observed
        def digest(array):
            view=memoryview(array).cast("B");hasher=hashlib.sha256()
            for start in range(0,len(view),1024*1024):hasher.update(view[start:start+1024*1024])
            return hasher.hexdigest()
        self.windows=[{"frames":list(map(int,self.frames)),"vertices_shape":list(self._vertices.shape),
                       "canonical_vertices_sha256":digest(self._vertices),
                       "triangles_shape":list(self._triangles.shape),"triangles_sha256":digest(self._triangles)}]

    def __getitem__(self,row):
        return TriangleSurface(self._vertices[row],self._triangles,semantics=self.semantics,
                               orientation_observed=self.orientation_observed)


class WindowedSurfaceTrack:
    """Revisit immutable geometry windows while retaining one global solver grid."""
    def __init__(self, windows, frames, *, context, semantics="volume", orientation_observed=False,
                 memory_budget_bytes=256*1024*1024):
        self.windows=list(windows); self.frames=np.asarray(frames)
        self.context=context; self.semantics=semantics; self.orientation_observed=orientation_observed
        self.budget=int(memory_budget_bytes); self._cached_index=None; self._cached=None
        if self.budget<=0:
            raise MotionInputError("INVALID_POLICY","positive window memory budget required")
        self.locations={}; self.overlaps={}
        for index,window in enumerate(self.windows):
            grid=window.get("frames",[])
            if (not grid or len(grid)>2000 or any(isinstance(f,bool) or not isinstance(f,int) for f in grid)
                    or any(a>=b for a,b in zip(grid,grid[1:]))):
                raise MotionInputError("INCOMPLETE_CAPTURE","window requires an exact unique ordered frame grid of at most 2000 rows")
            for row,frame in enumerate(grid):
                if frame in self.locations:
                    self.overlaps.setdefault(frame,[self.locations[frame]]).append((index,row))
                else:
                    self.locations[frame]=(index,row)
        if set(self.locations)!=set(map(int,self.frames)):
            raise MotionInputError("INCOMPLETE_CAPTURE","geometry windows do not exactly cover the global time grid")
        # A duplicated boundary is compared, never averaged or independently solved.
        for frame,locations in self.overlaps.items():
            reference=None
            for index,row in locations:
                positions,triangles=self._load(index)
                observed=(positions[row].tobytes(),triangles.tobytes())
                if reference is not None and observed!=reference:
                    raise MotionInputError("SOURCE_CHANGED","overlapping geometry windows disagree")
                reference=observed

    def _load(self,index):
        import hashlib
        import zipfile
        from pathlib import Path
        if self._cached_index==index:
            return self._cached
        window=self.windows[index]; path=Path(window["path"])
        if not path.is_absolute() or not path.is_file():
            raise MotionInputError("INCOMPLETE_CAPTURE","immutable mesh window path does not exist")
        with path.open("rb") as stream:
            digest=hashlib.file_digest(stream,"sha256").hexdigest()
        if digest!=window.get("sha256"):
            raise MotionInputError("SOURCE_CHANGED","immutable mesh window digest differs")
        with zipfile.ZipFile(path) as archive:
            if sum(info.file_size for info in archive.infolist())>self.budget:
                raise MotionInputError("RESOURCE_BUDGET_EXCEEDED","uncompressed mesh window exceeds memory budget")
        with np.load(path,allow_pickle=False) as capture:
            frames=np.asarray(capture["frames"])
            positions=np.asarray(capture[window.get("position_field","positions")],dtype=float)
            triangles=np.asarray(capture["triangles"])
            if (not np.array_equal(frames,window["frames"]) or positions.ndim!=3
                    or positions.shape[0]!=len(frames) or positions.shape[2]!=3 or not np.isfinite(positions).all()
                    or positions.nbytes+triangles.nbytes>self.budget):
                raise MotionInputError("INCOMPLETE_CAPTURE","mesh window payload does not match its manifest")
            if not window.get("canonical_metres",False):
                positions=self.context.positions_to_solver(positions)
            indices=window.get("triangle_indices")
            if indices is not None:
                indices=np.asarray(indices)
                if indices.dtype.kind not in "iu" or np.any(indices<0) or np.any(indices>=len(triangles)):
                    raise MotionInputError("INVALID_MESH","invalid obstacle triangle subset")
                triangles=triangles[indices]
            self._cached=(positions,triangles); self._cached_index=index
            return self._cached

    def __len__(self):
        return len(self.frames)

    def __getitem__(self,row):
        index,local=self.locations[int(self.frames[row])]
        positions,triangles=self._load(index)
        return TriangleSurface(positions[local],triangles,semantics=self.semantics,
                               orientation_observed=self.orientation_observed)


def closest_triangle(point, triangle):
    """Closest point with barycentric coordinates, including degenerate edges."""
    p = np.asarray(point, dtype=float)
    a, b, c = np.asarray(triangle, dtype=float)
    ab, ac = b - a, c - a
    normal = np.cross(ab, ac)
    length2 = normal @ normal
    candidates = []
    if length2 > 1e-24:
        projected = p - normal * ((p - a) @ normal) / length2
        d00, d01, d11 = ab @ ab, ab @ ac, ac @ ac
        v = projected - a
        denominator = d00 * d11 - d01 * d01
        y = (d11 * (v @ ab) - d01 * (v @ ac)) / denominator
        z = (d00 * (v @ ac) - d01 * (v @ ab)) / denominator
        bary = np.array([1 - y - z, y, z])
        if min(bary) >= -1e-12:
            candidates.append((float(np.sum((p - projected) ** 2)), projected, bary))
    for i, j in ((0, 1), (1, 2), (2, 0)):
        vertices = (a, b, c)
        start, end = vertices[i], vertices[j]
        edge = end - start
        ratio = float(np.clip((p - start) @ edge / max(edge @ edge, 1e-30), 0, 1))
        closest = start + ratio * edge
        bary = np.zeros(3)
        bary[i], bary[j] = 1 - ratio, ratio
        candidates.append((float(np.sum((p - closest) ** 2)), closest, bary))
    _, closest, bary = min(candidates, key=lambda x: x[0])
    return closest, bary


@dataclass(frozen=True)
class SurfaceQuery:
    triangle_id: int
    closest_point: np.ndarray
    barycentric: np.ndarray
    unsigned_distance_m: float
    oriented_normal: np.ndarray
    signed_distance_m: float | None
    classification: str


class TriangleSurface:
    def __init__(self, vertices, triangles, *, semantics="volume", patch_band_m=0.01,
                 orientation_observed=False):
        self.vertices = np.asarray(vertices, dtype=float)
        self.triangles = np.asarray(triangles)
        self.semantics, self.patch_band = semantics, patch_band_m
        self.orientation_observed = orientation_observed
        if (self.vertices.ndim != 2 or self.vertices.shape[1] != 3 or not np.isfinite(self.vertices).all()
                or self.triangles.ndim != 2 or self.triangles.shape[1] != 3
                or self.triangles.dtype.kind not in "iu" or not len(self.triangles)
                or np.any(self.triangles < 0) or np.any(self.triangles >= len(self.vertices))):
            raise MotionInputError("INVALID_MESH", "finite vertices and valid triangle indices required")
        if semantics not in ("volume", "oriented_patch", "unsigned_surface"):
            raise MotionInputError("INVALID_POLICY", "unknown collision semantics")
        self.triangles = self.triangles.astype(np.int64)
        self._geometry = self.vertices[self.triangles]
        normals = np.cross(self._geometry[:, 1] - self._geometry[:, 0],
                           self._geometry[:, 2] - self._geometry[:, 0])
        norm = np.linalg.norm(normals, axis=1)
        self.degenerate = norm < 1e-12
        self.normals = normals / np.maximum(norm[:, None], 1e-30)
        self.components, self.closed, self.neighbors = self._topology()
        self._outward = np.ones(len(self.triangles))
        for component, closed in zip(self.components, self.closed, strict=True):
            if closed:
                g = self._geometry[component]
                volume = np.einsum("ij,ij->i", g[:, 0], np.cross(g[:, 1], g[:, 2])).sum() / 6
                if abs(volume) < 1e-18:
                    self.closed[self.components.index(component)] = False
                else:
                    self._outward[component] = 1 if volume > 0 else -1
        self.normals *= self._outward[:, None]
        self.nodes = []
        self.root = self._build(np.arange(len(self.triangles)))

    def _topology(self):
        edges, neighbors = {}, [set() for _ in self.triangles]
        for i, face in enumerate(self.triangles):
            for a, b in zip(face, np.roll(face, -1), strict=True):
                edges.setdefault(tuple(sorted((int(a), int(b)))), []).append((i, int(a), int(b)))
        for entries in edges.values():
            for first, *_ in entries:
                neighbors[first].update(other[0] for other in entries if other[0] != first)
        remaining, components, closed = set(range(len(self.triangles))), [], []
        while remaining:
            pending, component = [min(remaining)], set()
            while pending:
                current = pending.pop()
                if current in component:
                    continue
                component.add(current)
                pending.extend(neighbors[current] - component)
            remaining -= component
            entries = [v for v in edges.values() if v[0][0] in component]
            valid = all(len(e) == 2 and e[0][1:] == e[1][1:][::-1] for e in entries)
            indices = sorted(component)
            valid = valid and not self.degenerate[indices].any()
            components.append(indices)
            closed.append(bool(valid))
        return components, closed, neighbors

    def _build(self, ids):
        geometry = self._geometry[ids]
        low, high = geometry.min(axis=(0, 1)), geometry.max(axis=(0, 1))
        index = len(self.nodes)
        self.nodes.append(None)
        if len(ids) <= 8:
            self.nodes[index] = (low, high, ids, None, None)
        else:
            centers = geometry.mean(axis=1)
            axis = int(np.argmax(np.ptp(centers, axis=0)))
            order = ids[np.argsort(centers[:, axis], kind="stable")]
            middle = len(ids) // 2
            left, right = self._build(order[:middle]), self._build(order[middle:])
            self.nodes[index] = (low, high, None, left, right)
        return index

    def _bound(self, point, node):
        low, high, *_ = self.nodes[node]
        return float(np.sum(np.maximum(np.maximum(low - point, point - high), 0) ** 2))

    def _inside(self, point):
        if not all(self.closed):
            return None
        for component in self.components:
            v = self._geometry[component] - point
            a, b, c = v[:, 0], v[:, 1], v[:, 2]
            la, lb, lc = (np.linalg.norm(x, axis=1) for x in (a, b, c))
            numerator = np.einsum("ij,ij->i", a, np.cross(b, c))
            denominator = (la * lb * lc + np.einsum("ij,ij->i", a, b) * lc
                           + np.einsum("ij,ij->i", b, c) * la + np.einsum("ij,ij->i", c, a) * lb)
            winding = float((2 * np.arctan2(numerator, denominator)).sum() / (4 * np.pi))
            if abs(winding) > 0.5:
                return True
        return False

    def closest(self, point):
        point = np.asarray(point, dtype=float)
        if point.shape != (3,) or not np.isfinite(point).all():
            raise MotionInputError("GEOMETRY_QUERY_FAILED", "invalid query point")
        pending, best, chosen = [(self._bound(point, self.root), self.root)], np.inf, None
        while pending:
            bound, index = heapq.heappop(pending)
            if bound > best:
                continue
            _, _, ids, left, right = self.nodes[index]
            if ids is None:
                for child in (left, right):
                    lower = self._bound(point, child)
                    if lower <= best:
                        heapq.heappush(pending, (lower, child))
                continue
            for triangle_id in ids:
                closest, barycentric = closest_triangle(point, self._geometry[triangle_id])
                distance = float(np.sum((point - closest) ** 2))
                if distance < best:
                    best, chosen = distance, (int(triangle_id), closest, barycentric)
        triangle_id, closest, bary = chosen
        distance = float(np.sqrt(best))
        normal = self.normals[triangle_id]
        signed, classification = None, "ambiguous"
        if self.semantics == "unsigned_surface":
            classification = "known"
        elif all(self.closed):
            inside = self._inside(point)
            signed, classification = (-distance if inside else distance), "known"
        elif (self.semantics == "oriented_patch" and self.orientation_observed
              and not self.degenerate[triangle_id] and min(bary) > 1e-6 and distance <= self.patch_band):
            neighbors = list(self.neighbors[triangle_id])
            if not neighbors or np.all(self.normals[neighbors] @ normal >= np.cos(np.radians(20))):
                signed = distance * (-1 if (point - closest) @ normal < 0 else 1)
                classification = "known"
        return SurfaceQuery(triangle_id, closest, bary, distance, normal, signed, classification)

    def query(self, points):
        return [self.closest(point) for point in points]


def segment_distance(a, b, c, d, *, return_points=False):
    """Exact constrained edge-edge distance, including parallel/zero edges."""
    a, b, c, d = (np.asarray(value, dtype=float) for value in (a,b,c,d))
    u, v, w = b - a, d - c, a - c
    aa, bb, cc, dd, ee = u @ u, u @ v, v @ v, u @ w, v @ w
    candidates = []
    denominator = aa * cc - bb * bb
    if denominator > 1e-24:
        s, t = (bb * ee - cc * dd) / denominator, (aa * ee - bb * dd) / denominator
        if 0 <= s <= 1 and 0 <= t <= 1:
            p, q = a+s*u, c+t*v
            candidates.append((float(np.linalg.norm(p-q)),p,q))
    for p, start, direction in ((a, c, v), (b, c, v), (c, a, u), (d, a, u)):
        t = np.clip((p - start) @ direction / max(direction @ direction, 1e-30), 0, 1)
        q=start+t*direction
        candidates.append((float(np.linalg.norm(p-q)),p,q) if start is c or start is d else (float(np.linalg.norm(p-q)),q,p))
    result=min(candidates,key=lambda value:value[0])
    return result if return_points else result[0]


def triangle_pair_distance(first, second):
    first, second = np.asarray(first), np.asarray(second)
    candidates = [np.linalg.norm(p - closest_triangle(p, second)[0]) for p in first]
    candidates += [np.linalg.norm(p - closest_triangle(p, first)[0]) for p in second]
    for i in range(3):
        for j in range(3):
            candidates.append(segment_distance(first[i], first[(i + 1) % 3], second[j], second[(j + 1) % 3]))
    # An edge can cross the interior of the opposite face without a vertex touching it.
    for edges, face in ((first, second), (second, first)):
        normal = np.cross(face[1] - face[0], face[2] - face[0])
        for i in range(3):
            a, b = edges[i], edges[(i + 1) % 3]
            denominator = (b - a) @ normal
            if abs(denominator) < 1e-18:
                continue
            t = (face[0] - a) @ normal / denominator
            if 0 <= t <= 1:
                point = a + t * (b - a)
                closest, _ = closest_triangle(point, face)
                if np.linalg.norm(point - closest) < 1e-10:
                    return 0.0
    return float(min(candidates))
