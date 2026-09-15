"""Example agent for the local DreamHouse dev sandbox.

Generates a simple but complete timber-frame structure covering all four
member categories (foundation, floor, walls, roof) so it passes the
`completeness` check implemented by scripts/dev_validation.py. The other 9
tests in that stub always pass — the real structural-engineering rules are
proprietary (see README "Running the server locally").

Matches the agent signature dreamhouse expects:
    generate(prompt: str, images: list[str], feedback: list[dict]) -> str
"""

from __future__ import annotations

import re


def _parse_footprint(prompt: str) -> tuple[float, float]:
    match = re.search(r"Footprint:\s*([\d.]+)m x ([\d.]+)m", prompt)
    if match:
        return float(match.group(1)), float(match.group(2))
    return 6.0, 8.0


def generate(prompt: str, images: list[str], feedback: list[dict]) -> str:
    width, depth = _parse_footprint(prompt)

    return f'''
import bpy

collection_name = "COLLECTION_NAME"
if collection_name not in bpy.data.collections:
    col = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(col)
else:
    col = bpy.data.collections[collection_name]


def add_member(name, location, scale):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(scale=True)
    for c in obj.users_collection:
        c.objects.unlink(obj)
    col.objects.link(obj)
    return obj


W, D = {width}, {depth}
SILL_H, SILL_T = 0.038, 0.14
JOIST_H, JOIST_T = 0.038, 0.235
STUD_T = 0.09
WALL_HEIGHT = 2.4
ROOF_RISE = 1.2

# Foundation: perimeter sill plates
add_member("Sill_01", (W / 2, 0, SILL_H / 2), (W, SILL_T, SILL_H))
add_member("Sill_02", (W / 2, D, SILL_H / 2), (W, SILL_T, SILL_H))
add_member("Sill_03", (0, D / 2, SILL_H / 2), (SILL_T, D, SILL_H))
add_member("Sill_04", (W, D / 2, SILL_H / 2), (SILL_T, D, SILL_H))

# Floor: joists spanning the short axis
z_floor = SILL_H
n_joists = 5
for i in range(n_joists):
    y = D * (i + 0.5) / n_joists
    add_member(f"Joist_{{i + 1:02d}}", (W / 2, y, z_floor + JOIST_H / 2), (W, JOIST_T, JOIST_H))

# Walls: corner studs + top plates on both long walls
z_wall = z_floor + JOIST_H
for i, (x, y) in enumerate([(0, 0), (W, 0), (0, D), (W, D)]):
    add_member(f"Stud_{{i + 1:02d}}", (x, y, z_wall + WALL_HEIGHT / 2), (STUD_T, STUD_T, WALL_HEIGHT))
add_member("Plate_01", (W / 2, 0, z_wall + WALL_HEIGHT + SILL_H / 2), (W, SILL_T, SILL_H))
add_member("Plate_02", (W / 2, D, z_wall + WALL_HEIGHT + SILL_H / 2), (W, SILL_T, SILL_H))

# Roof: ridge beam + rafters
z_plate = z_wall + WALL_HEIGHT + SILL_H
ridge_z = z_plate + ROOF_RISE
add_member("Ridge_01", (W / 2, D / 2, ridge_z), (0.09, D, 0.24))
n_rafters = 4
for i in range(n_rafters):
    y = D * (i + 0.5) / n_rafters
    add_member(f"Rafter_{{i + 1:02d}}", (W / 2, y, (z_plate + ridge_z) / 2), (W, 0.038, 0.14))
'''
