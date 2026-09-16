"""Render a quick preview PNG of a generated structure.blend.

Runs inside Blender headless. Frames a camera around every mesh object in
the scene, adds a sun light, and renders with Workbench (fast, no GPU/HDRI
setup needed) so you can eyeball a result without opening the full GUI.

Usage:
  blender --background path/to/structure.blend --python scripts/render_preview.py -- output.png
"""

from __future__ import annotations

import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
output_path = os.path.abspath(argv[0] if argv else "preview.png")

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    print("No mesh objects found in scene.")
    sys.exit(1)

mins = Vector((min(o.matrix_world.translation.x - o.dimensions.x for o in meshes),
               min(o.matrix_world.translation.y - o.dimensions.y for o in meshes),
               min(o.matrix_world.translation.z - o.dimensions.z for o in meshes)))
maxs = Vector((max(o.matrix_world.translation.x + o.dimensions.x for o in meshes),
               max(o.matrix_world.translation.y + o.dimensions.y for o in meshes),
               max(o.matrix_world.translation.z + o.dimensions.z for o in meshes)))
center = (mins + maxs) / 2
size = max((maxs - mins).x, (maxs - mins).y, (maxs - mins).z, 1.0)

for obj in list(bpy.data.objects):
    if obj.type in ("CAMERA", "LIGHT"):
        bpy.data.objects.remove(obj, do_unlink=True)

cam_data = bpy.data.cameras.new("PreviewCam")
cam = bpy.data.objects.new("PreviewCam", cam_data)
bpy.context.scene.collection.objects.link(cam)
dist = size * 1.8
cam.location = center + Vector((dist, -dist, dist * 0.75))
direction = center - cam.location
cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.camera = cam

sun_data = bpy.data.lights.new("PreviewSun", type="SUN")
sun_data.energy = 3.0
sun = bpy.data.objects.new("PreviewSun", sun_data)
sun.rotation_euler = (0.7, 0.3, 0.9)
bpy.context.scene.collection.objects.link(sun)

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 800
scene.render.resolution_y = 600
scene.render.filepath = output_path
bpy.ops.render.render(write_still=True)
print(f"Rendered {len(meshes)} members to {output_path}")
