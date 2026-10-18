"""Validate exported meshes and draw an orthographic top view from STL triangles.

Requires numpy, trimesh and matplotlib. Run after exporting each SCAD with OpenSCAD.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent
LIMITS = {
    "hospital": (55, 45, 22), "shelter": (55, 45, 22),
    "food_shelter": (55, 45, 22), "bridge": (70, 40, 13),
    "person": (45, 45, 17), "disaster_start": (50, 50, 13),
}


def components(mesh):
    parents = list(range(len(mesh.faces)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for a, b in mesh.face_adjacency:
        parents[root(int(a))] = root(int(b))
    return len({root(i) for i in range(len(parents))})


fig, axes = plt.subplots(2, 3, figsize=(13, 8.8))
for ax, (name, limits) in zip(axes.flat, LIMITS.items()):
    mesh = trimesh.load_mesh(ROOT / name / f"{name}.stl", process=True)
    assert mesh.is_watertight, f"{name}: open or non-manifold edges"
    assert mesh.is_winding_consistent and mesh.is_volume, f"{name}: invalid solid"
    count = components(mesh)
    assert count == 1, f"{name}: {count} disconnected shells"
    assert np.all(mesh.extents <= np.array(limits) + 1e-4), f"{name}: oversize"
    assert abs(mesh.bounds[0, 2]) < 1e-5, f"{name}: not on bed"
    # Every downward-facing triangle must be on the print bed. These designs
    # have vertical walls or upward-facing roof slopes, not floating ledges.
    downward = mesh.triangles[mesh.face_normals[:, 2] < -1e-5]
    assert np.all(np.abs(downward[:, :, 2]) < 1e-5), f"{name}: unsupported underside"
    print(f"{name}: {mesh.extents.round(3).tolist()} mm; "
          f"{len(mesh.faces)} triangles; one watertight solid; "
          "consistent normals; bed-supported undersides")
    visible = mesh.face_normals[:, 2] > 1e-5
    triangles = mesh.triangles[visible]
    normals = mesh.face_normals[visible]
    order = np.argsort(triangles[:, :, 2].mean(axis=1))
    triangles, normals = triangles[order], normals[order]
    height = triangles[:, :, 2].max(axis=1) / limits[2]
    # One neutral material: recognition cues cannot depend on filament color.
    light = 0.56 + 0.25 * height + 0.10 * normals[:, 2] + 0.08 * normals[:, 0]
    colors = np.column_stack((light * .68, light * .82, light, np.ones(len(light))))
    ax.add_collection(PolyCollection(triangles[:, :, :2], facecolors=colors,
                                     edgecolors="none", antialiaseds=False))
    ax.set(xlim=(-39, 39), ylim=(-29, 29), aspect="equal")
    ax.set_title(name.replace("_", " ").upper(), fontsize=12, weight="bold")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_xticks([-30, 0, 30])
    ax.set_yticks([-20, 0, 20])
    ax.set_facecolor("#f5f7fa")
    ax.text(.5, -.29, " x ".join(f"{v:g}" for v in mesh.extents) + " mm",
            transform=ax.transAxes, ha="center", fontsize=10)
fig.suptitle("FLOODSHIFT / TAGLESS TOKENS", fontsize=20, weight="bold")
fig.text(.5, .92, "Orthographic top views from regenerated STL meshes / same scale / height shading",
         ha="center", fontsize=11)
fig.subplots_adjust(top=.85, bottom=.10, hspace=.65, wspace=.30)
fig.savefig(ROOT / "top_down_preview.png", dpi=180)
plt.close(fig)
