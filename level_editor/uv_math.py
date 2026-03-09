"""
Pure-Python UV math: Quake/Valve axis selection, world-space projection,
texture continuation recovery, and UV decomposition.
"""

import math


def vec_sub(a: tuple, b: tuple) -> tuple:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_add(a: tuple, b: tuple) -> tuple:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vec_scale(v: tuple, s: float) -> tuple:
    return (v[0] * s, v[1] * s, v[2] * s)


def vec_dot(a: tuple, b: tuple) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_cross(a: tuple, b: tuple) -> tuple:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vec_length(v: tuple) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def vec_normalize(v: tuple) -> tuple:
    length = vec_length(v)
    if length < 1e-10:
        return (0.0, 0.0, 0.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def quake_axes(normal: tuple) -> tuple:
    """Pick the two world axes most perpendicular to the face normal.
    V direction is positive to match 3ds Max's V-up UV convention."""
    ax = abs(normal[0])
    ay = abs(normal[1])
    az = abs(normal[2])
    if az >= ax and az >= ay:
        return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    if ay >= ax:
        return (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    return (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)


def compute_face_axes(normal: tuple,
                      up_hint: tuple = (0.0, 0.0, 1.0)) -> tuple:
    n = vec_normalize(normal)
    if abs(vec_dot(n, vec_normalize(up_hint))) > 0.99:
        up_hint = (0.0, 1.0, 0.0)

    u_axis = vec_normalize(vec_cross(up_hint, n))
    v_axis = vec_normalize(vec_cross(n, u_axis))
    return u_axis, v_axis


def project_point_to_uv(point: tuple, origin: tuple,
                         u_axis: tuple, v_axis: tuple,
                         scale_u: float, scale_v: float,
                         offset_u: float, offset_v: float,
                         rotation_rad: float) -> tuple:
    delta = vec_sub(point, origin)
    raw_u = vec_dot(delta, u_axis) * scale_u
    raw_v = vec_dot(delta, v_axis) * scale_v

    cos_r = math.cos(rotation_rad)
    sin_r = math.sin(rotation_rad)
    rot_u = raw_u * cos_r - raw_v * sin_r
    rot_v = raw_u * sin_r + raw_v * cos_r

    return (rot_u + offset_u, rot_v + offset_v)


def recover_projection(p0: tuple, p1: tuple, p2: tuple,
                       uv0: tuple, uv1: tuple, uv2: tuple):
    """Solve for world-space projection axes from three verts and their UVs.
    Returns (u_axis, v_axis, offset_u, offset_v) or None if degenerate."""
    e1 = vec_sub(p1, p0)
    e2 = vec_sub(p2, p0)

    du1 = uv1[0] - uv0[0]
    dv1 = uv1[1] - uv0[1]
    du2 = uv2[0] - uv0[0]
    dv2 = uv2[1] - uv0[1]

    d11 = vec_dot(e1, e1)
    d12 = vec_dot(e1, e2)
    d22 = vec_dot(e2, e2)

    det = d11 * d22 - d12 * d12
    if abs(det) < 1e-10:
        return None

    inv = 1.0 / det

    a1_u = (d22 * du1 - d12 * du2) * inv
    a2_u = (d11 * du2 - d12 * du1) * inv

    a1_v = (d22 * dv1 - d12 * dv2) * inv
    a2_v = (d11 * dv2 - d12 * dv1) * inv

    u_axis = vec_add(vec_scale(e1, a1_u), vec_scale(e2, a2_u))
    v_axis = vec_add(vec_scale(e1, a1_v), vec_scale(e2, a2_v))

    offset_u = uv0[0] - vec_dot(p0, u_axis)
    offset_v = uv0[1] - vec_dot(p0, v_axis)

    return u_axis, v_axis, offset_u, offset_v


def apply_projection(target_verts: list[tuple],
                     u_axis: tuple, v_axis: tuple,
                     offset_u: float, offset_v: float) -> list[tuple]:
    uvs = []
    for vert in target_verts:
        u = vec_dot(vert, u_axis) + offset_u
        v = vec_dot(vert, v_axis) + offset_v
        uvs.append((u, v))
    return uvs


def decompose_from_recovered_axes(u_eff: tuple, v_eff: tuple,
                                  off_u: float, off_v: float,
                                  q_u: tuple, q_v: tuple,
                                  world_tile_size: float) -> dict:
    """Convert free-form projection vectors (from recover_projection) back
    into the quake-axis parameterisation (tile_u, tile_v, rotation, offset).

    The forward formula is:
        raw_u = dot(vert, q_u) / T * tile_u
        raw_v = dot(vert, q_v) / T * tile_v
        u = raw_u * cos(r) - raw_v * sin(r) + off_u
        v = raw_u * sin(r) + raw_v * cos(r) + off_v

    The effective (recovered) axes encode this combined transform:
        u_eff[i] = q_u[i]/T * tile_u * cos(r) + q_v[i]/T * tile_v * (-sin(r))
        v_eff[i] = q_u[i]/T * tile_u * sin(r) + q_v[i]/T * tile_v * cos(r)

    Projecting u_eff / v_eff onto each quake axis isolates the components:
        a = dot(u_eff, q_u) = tile_u / T * cos(r)
        b = dot(v_eff, q_u) = tile_u / T * sin(r)
        c = dot(u_eff, q_v) = -tile_v / T * sin(r)
        d = dot(v_eff, q_v) = tile_v / T * cos(r)
    """
    T = world_tile_size
    a = vec_dot(u_eff, q_u)
    b = vec_dot(v_eff, q_u)
    c = vec_dot(u_eff, q_v)
    d = vec_dot(v_eff, q_v)

    rotation = math.degrees(math.atan2(b, a))

    tile_u = math.sqrt(a * a + b * b) * T
    tile_v = math.sqrt(c * c + d * d) * T

    if tile_u < 0.001:
        tile_u = 1.0
    if tile_v < 0.001:
        tile_v = 1.0

    return {
        "tile_u": round(tile_u, 4),
        "tile_v": round(tile_v, 4),
        "rotation": round(rotation, 4),
        "offset_u": round(off_u, 4),
        "offset_v": round(off_v, 4),
    }


def decompose_uv_properties(face_verts_world: list[tuple],
                             face_uvs: list[tuple],
                             world_tile_size: float = 1.0) -> dict:
    """Approximate tiling/rotation/offset from existing face UVs."""
    if len(face_verts_world) < 2 or len(face_uvs) < 2:
        return {"tile_u": 1.0, "tile_v": 1.0, "rotation": 0.0,
                "offset_u": 0.0, "offset_v": 0.0}

    e_world = vec_sub(face_verts_world[1], face_verts_world[0])
    e_uv = (face_uvs[1][0] - face_uvs[0][0],
            face_uvs[1][1] - face_uvs[0][1])

    world_len = vec_length(e_world)
    uv_len = math.sqrt(e_uv[0] ** 2 + e_uv[1] ** 2)

    if world_len < 1e-10 or uv_len < 1e-10:
        return {"tile_u": 1.0, "tile_v": 1.0, "rotation": 0.0,
                "offset_u": 0.0, "offset_v": 0.0}

    scale = uv_len / world_len * world_tile_size
    rotation = math.degrees(math.atan2(e_uv[1], e_uv[0]))

    return {
        "tile_u": round(scale, 4),
        "tile_v": round(scale, 4),
        "rotation": round(rotation, 2),
        "offset_u": round(face_uvs[0][0], 4),
        "offset_v": round(face_uvs[0][1], 4),
    }

def compute_polygon_normal(verts: list[tuple]) -> tuple:
    nx, ny, nz = 0.0, 0.0, 0.0
    num = len(verts)
    if num < 3:
        return (0.0, 0.0, 1.0)
    for i in range(num):
        v_curr = verts[i]
        v_next = verts[(i + 1) % num]
        nx += (v_curr[1] - v_next[1]) * (v_curr[2] + v_next[2])
        ny += (v_curr[2] - v_next[2]) * (v_curr[0] + v_next[0])
        nz += (v_curr[0] - v_next[0]) * (v_curr[1] + v_next[1])
    return vec_normalize((nx, ny, nz))