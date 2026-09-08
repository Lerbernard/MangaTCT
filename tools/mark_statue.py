#!/usr/bin/env python3
"""The mark as a real 3D monument: build it, render it, export it.

    pip install bpy==4.2.0
    python tools/mark_statue.py                       # a 3/4 view, toon shaded
    python tools/mark_statue.py --turn 35 --tilt 8
    python tools/mark_statue.py --preview             # fast, ugly, for framing
    python tools/mark_statue.py --glb out/mark.glb    # keep the model itself

## Why this is a model and not a drawing

A drawn statue is one angle for ever. This one is built from `favicon.svg` -
the same path the favicon and the chest patch use - extruded, stood on a
plinth and lit, so the geometry is exact by construction and any view of it is
one number away. It renders with a transparent ground, so it drops onto a
banner, onto white, or behind a character with no cutting out.

## Why it is toon shaded and not photoreal

It stands next to flat cel anime art. A photoreal marble render beside a flat
drawing looks like a mistake in both directions: the render looks pasted on,
the drawing looks unfinished. Cycles' Toon BSDF bands the shading into two or
three steps and Freestyle draws the outline, which is the same language the
character is drawn in.
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = os.path.join(HERE, "static", "favicon.svg")

STONE = (0.78, 0.80, 0.84, 1.0)
STONE_DARK = (0.60, 0.63, 0.70, 1.0)
GOLD = (1.00, 0.62, 0.00, 1.0)
LETTER_H = 2.0                  # metres, and everything else is measured off it


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _bounds(objs):
    """The box round these objects AS THEY WILL BE DRAWN.

    Off the evaluated object, not the one in the file. A curve's own
    `bound_box` is the box round its control points before anything has been
    generated from them - before the extrude, before the bevel, and stale
    besides until the dependency graph has caught up. Measuring that put the
    statue at forty times the size it asked for and the camera inside it.
    """
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        ev = o.evaluated_get(dg)
        try:
            me = ev.to_mesh()
        except Exception:
            me = None
        pts = ([v.co for v in me.vertices] if me and len(me.vertices)
               else [Vector(c) for c in o.bound_box])
        for p in pts:
            w = o.matrix_world @ p
            lo = Vector((min(lo[i], w[i]) for i in range(3)))
            hi = Vector((max(hi[i], w[i]) for i in range(3)))
        if me:
            ev.to_mesh_clear()
    return lo, hi


def letter(depth=0.34, bevel=0.012):
    """The mark, imported from the SVG and given a thickness."""
    before = set(bpy.data.objects)
    bpy.ops.import_curve.svg(filepath=MARK)
    curves = [o for o in bpy.data.objects if o not in before]
    if not curves:
        raise SystemExit("the SVG imported as nothing - is %s there?" % MARK)

    for o in curves:
        # LEFT 2D ON PURPOSE, and this is the trap in the middle of this
        # function. A 2D curve refuses to be rotated out of its own plane -
        # "Rotation/Location can't apply to a 2D curve" - and the obvious
        # answer, `dimensions = "3D"`, is wrong: only a 2D curve FILLS. Set it
        # and the letter converts to a wire outline with no faces in it, which
        # renders as nothing at all and looks exactly like a scaling bug.
        #
        # So it stays 2D, is converted to a mesh while it still fills, and is
        # stood upright afterwards - when it is a mesh and may be rotated.
        o.data.extrude = 0.0
        o.data.bevel_depth = 0.0

    bpy.ops.object.select_all(action="DESELECT")
    for o in curves:
        o.select_set(True)
    bpy.context.view_layer.objects.active = curves[0]
    if len(curves) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = "mark"

    # MEASURE IT AS A MESH, not as a curve. A curve's size is a question about
    # what will be generated from it, and the answer moves under you: the first
    # version of this scaled the curve to a height it had already been told,
    # measured seven times too small, and put a fourteen-metre letter in front
    # of a camera standing seven metres back. Flat mesh, real numbers, then
    # stand it up, then scale, then thicken.
    obj.data.resolution_u = 8
    bpy.ops.object.convert(target="MESH")
    obj.rotation_euler = (math.pi / 2, 0, 0)
    bpy.ops.object.transform_apply(rotation=True)
    bpy.context.view_layer.update()
    lo, hi = _bounds([obj])
    k = LETTER_H / max(1e-6, hi.z - lo.z)
    obj.scale = (k, k, k)
    bpy.ops.object.transform_apply(scale=True)

    # Thickness, in metres, because it is a mesh now: solidify across the face
    # and take the sharp arris off the edges.
    sol = obj.modifiers.new("thick", "SOLIDIFY")
    sol.thickness = depth
    sol.offset = 0.0
    bev = obj.modifiers.new("edge", "BEVEL")
    bev.width = bevel
    bev.segments = 3
    bev.limit_method = "ANGLE"
    bev.angle_limit = math.radians(35)
    bpy.ops.object.modifier_apply(modifier="thick")
    bpy.ops.object.modifier_apply(modifier="edge")
    bpy.context.view_layer.update()

    lo, hi = _bounds([obj])
    obj.location.x -= (lo.x + hi.x) / 2.0        # centred on the plinth
    obj.location.z -= lo.z                       # standing ON the ground
    bpy.ops.object.transform_apply(location=True)
    return obj


def plinth(top_z, width, depth):
    """A tapered block for it to stand on, with a plate on the front."""
    h = LETTER_H * 0.30
    bpy.ops.mesh.primitive_cube_add(size=1)
    base = bpy.context.object
    base.name = "plinth"
    # A size-1 cube spans -0.5..0.5, so the scale IS the dimension - not half
    # of it. Halving them built a plinth at half the size of the one asked for,
    # which read on screen as the letter hovering over a footstool.
    base.scale = (width, depth, h)
    base.location = (0, 0, -h / 2.0 + top_z)
    bpy.ops.object.transform_apply(scale=True, location=True)

    # taper: the top face pulled in a little
    me = base.data
    for v in me.vertices:
        if v.co.z > top_z - h * 0.5:
            v.co.x *= 0.86
            v.co.y *= 0.86

    bpy.ops.mesh.primitive_cube_add(size=1)
    plate = bpy.context.object
    plate.name = "plate"
    plate.scale = (width * 0.40, depth * 1.02, h * 0.16)
    plate.location = (0, 0, top_z - h * 0.46)
    bpy.ops.object.transform_apply(scale=True, location=True)
    return base, plate


def toon(name, colour, size=0.35, smooth=0.0):
    """A material that steps rather than graduates, which is what cel is."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    sh = nt.nodes.new("ShaderNodeBsdfToon")
    sh.inputs["Color"].default_value = colour
    sh.inputs["Size"].default_value = size
    sh.inputs["Smooth"].default_value = smooth
    nt.links.new(sh.outputs[0], out.inputs["Surface"])
    return m


def light():
    """Key, fill and a rim, so the block reads as a block."""
    for name, loc, energy, size in (
            ("key", (4.2, -5.0, 6.0), 2400, 1.2),
            ("fill", (-5.0, -3.0, 2.4), 260, 6.0),
            ("rim", (-2.0, 5.2, 4.4), 900, 2.0)):
        bpy.ops.object.light_add(type="AREA", location=loc)
        lamp = bpy.context.object
        lamp.name = name
        lamp.data.energy = energy
        lamp.data.size = size
        d = Vector((0, 0, LETTER_H * 0.6)) - Vector(loc)
        lamp.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def camera(turn, tilt, height, dist, fit=None):
    """A three-quarter view, far enough back to hold the whole thing.

    `dist` of 0 means "work it out": the distance at which the statue's own
    height fills the frame with a margin, so changing how tall the plinth is
    does not also mean re-finding the camera.
    """
    if fit is not None and dist <= 0:
        lo, hi = fit
        span = max(hi.z - lo.z, (hi.x - lo.x) * 1.25)
        dist = span * 1.9
    at = Vector((0, 0, (fit[0].z + fit[1].z) / 2.0 if fit else LETTER_H * 0.62))
    a, t = math.radians(turn), math.radians(tilt)
    loc = Vector((math.sin(a) * dist, -math.cos(a) * dist,
                  at.z + math.tan(t) * dist + height))
    bpy.ops.object.camera_add(location=loc)
    cam = bpy.context.object
    cam.data.lens = 62
    cam.rotation_euler = (at - loc).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def build(depth):
    obj = letter(depth=depth)
    lo, hi = _bounds([obj])
    # Sunk in, not balanced on top. The mark's right leg ends in a point, so a
    # plinth that only touches that point reads as a letter hovering over a
    # box; buried a little, it reads as one thing standing in the ground.
    sink = LETTER_H * 0.06
    obj.location.z -= sink
    bpy.ops.object.transform_apply(location=True)
    base, plate = plinth(top_z=LETTER_H * 0.03, width=(hi.x - lo.x) * 1.06,
                         depth=depth * 3.2)
    obj.data.materials.append(toon("stone", STONE))
    base.data.materials.append(toon("stone_d", STONE_DARK))
    plate.data.materials.append(toon("gold", GOLD, size=0.7))
    for o in (obj, base, plate):
        for p in o.data.polygons:
            p.use_smooth = False
    return obj, base, plate


def render(path, w, h, samples, preview):
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.film_transparent = True            # drops onto any ground
    sc.render.filepath = path
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    if preview:
        sc.render.engine = "BLENDER_WORKBENCH"
    else:
        sc.render.engine = "CYCLES"
        sc.cycles.device = "CPU"
        sc.cycles.samples = samples
        sc.cycles.use_denoising = True
        # Freestyle is the outline. Without it a toon material is just flat
        # colour; the line is half of what makes a drawing a drawing.
        sc.render.use_freestyle = True
        vl = bpy.context.view_layer
        # BOTH switches. The scene one turns the renderer on, the view layer
        # one decides whether this layer draws any. Set only the first and the
        # render comes back with no outline and no complaint.
        vl.use_freestyle = True
        vl.freestyle_settings.as_render_pass = False
        fs = vl.freestyle_settings.linesets.new("outline")
        fs.select_silhouette = True
        fs.select_border = True
        fs.select_crease = True
        fs.linestyle.color = (0.06, 0.07, 0.10)
        fs.linestyle.thickness = 2.6
        vl.freestyle_settings.crease_angle = math.radians(105)
    bpy.ops.render.render(write_still=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join("out", "statue.png"))
    ap.add_argument("--glb", default="", help="also write the model here")
    ap.add_argument("--turn", type=float, default=28.0, help="degrees around")
    ap.add_argument("--tilt", type=float, default=-6.0, help="+ looks down")
    ap.add_argument("--height", type=float, default=0.0)
    ap.add_argument("--dist", type=float, default=0.0,
                    help="0 frames it automatically")
    ap.add_argument("--depth", type=float, default=0.34, help="how thick")
    ap.add_argument("--size", default="1000x1200")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:]
                      if "--" in sys.argv else None)

    w, h = (int(v) for v in a.size.lower().split("x"))
    clear()
    made = build(a.depth)
    light()
    camera(a.turn, a.tilt, a.height, a.dist, fit=_bounds(made))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    render(a.out, w, h, a.samples, a.preview)
    print("wrote", a.out)
    if a.glb:
        os.makedirs(os.path.dirname(os.path.abspath(a.glb)), exist_ok=True)
        bpy.ops.object.select_all(action="DESELECT")
        for o in bpy.data.objects:
            if o.type == "MESH":
                o.select_set(True)
        bpy.ops.export_scene.gltf(filepath=a.glb, use_selection=True)
        print("wrote", a.glb)


if __name__ == "__main__":
    main()
