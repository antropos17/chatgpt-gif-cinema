import bpy, json, os, math
from mathutils import Vector
sc=bpy.context.scene
frames=[1,19,37,55,73,91,109,127,144,145]
poses={}
for f in frames:
 sc.frame_set(f)
 poses[f]={o.name:[float(v) for row in o.matrix_world for v in row] for o in sc.objects if o.animation_data}
seam=max(abs(a-b) for name in poses[1] for a,b in zip(poses[1][name],poses[145][name]))
report={
 'blender_version':bpy.app.version_string,
 'renderer':sc.render.engine,
 'resolution':[sc.render.resolution_x,sc.render.resolution_y],
 'fps':sc.render.fps,
 'frame_range':[sc.frame_start,sc.frame_end],
 'duration_seconds':(sc.frame_end-sc.frame_start+1)/sc.render.fps,
 'geometry_loop_max_transform_error':seam,
 'geometry_loop_closed':seam<1e-6,
 'animated_controllers':len(poses[1]),
 'camera':'Locked orthographic three-quarter camera',
 'asset_sources':'Authored Blender meshes; bundled DejaVu typeface; no external textures',
 'materials':[m.name for m in bpy.data.materials],
 'lighting':'Four studio area lights; the key casts soft shadows',
 'denoising':'No generative or neural denoising; conventional FFmpeg hqdn3d only',
}
assert report['geometry_loop_closed'],report
out=os.path.join(os.path.dirname(bpy.data.filepath),'scene-check.json')
open(out,'w').write(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
# Make the delivered .blend portable. Rerender jobs use their own output override.
sc.render.filepath='//renders/form_';sc.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
