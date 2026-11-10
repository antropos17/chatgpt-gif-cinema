"""FORM / 01: an original, deterministic Blender kinetic sculpture.
Usage: blender -b --python form_study.py -- [--preview] [--frames 1,37,73,109]
All geometry, lights, materials, typography and motion are authored here.
No external assets, generative image models, paid APIs, or JavaScript.
"""
import bpy, math, os, sys, argparse
from mathutils import Vector
from math import sin, cos, pi
HERE=os.path.dirname(os.path.abspath(__file__))
p=argparse.ArgumentParser(); p.add_argument('--preview',action='store_true'); p.add_argument('--frames',default=''); p.add_argument('--render',action='store_true')
args=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
for datablocks in (bpy.data.materials,bpy.data.meshes,bpy.data.curves,bpy.data.cameras,bpy.data.lights):
    for block in list(datablocks):
        if block.users == 0: datablocks.remove(block)
sc=bpy.context.scene
sc.render.engine='BLENDER_EEVEE_NEXT'; sc.eevee.taa_render_samples=24; sc.eevee.shadow_ray_count=2; sc.cycles.device='CPU'; sc.cycles.samples=128
sc.cycles.use_denoising=False; sc.cycles.adaptive_threshold=.04
sc.cycles.max_bounces=8; sc.cycles.diffuse_bounces=3; sc.cycles.glossy_bounces=5
sc.render.threads_mode='FIXED'; sc.render.threads=8
sc.render.resolution_x=800; sc.render.resolution_y=800; sc.render.resolution_percentage=100
sc.render.fps=24; sc.frame_start=1; sc.frame_end=144
sc.render.image_settings.file_format='PNG'; sc.render.image_settings.color_mode='RGB'; sc.render.image_settings.color_depth='8'
sc.view_settings.view_transform='AgX'; sc.view_settings.look='AgX - Medium High Contrast'; sc.view_settings.exposure=.25
sc.world.color=(.22,.22,.22)
sc.world.use_nodes=True; sc.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.73,.78,.86,1); sc.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.22

def mat(name,color,metal=0,rough=.4):
    m=bpy.data.materials.new(name); m.use_nodes=True
    bs=m.node_tree.nodes.get('Principled BSDF'); bs.inputs['Base Color'].default_value=(*color,1); bs.inputs['Metallic'].default_value=metal; bs.inputs['Roughness'].default_value=rough
    return m
ceramic=mat('01 | Warm porcelain',(.78,.75,.68),.08,.23)
bs=ceramic.node_tree.nodes.get('Principled BSDF'); bs.inputs['Coat Weight'].default_value=.28; bs.inputs['Coat Roughness'].default_value=.19
chrome=mat('02 | Satin silver',(.7,.74,.77),1,.16)
black=mat('03 | Anodized graphite',(.026,.032,.034),.55,.43)
copper=mat('04 | Burnt copper',(.39,.075,.032),1,.21)
back=mat('05 | Warm limestone backdrop',(.49,.455,.39),0,.78)
ink=mat('06 | Editorial ink',(.026,.029,.027),0,.7)
# Subtle ceramic grain, fine enough to remain quiet rather than noisy.
nt=ceramic.node_tree; noise=nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value=175; noise.inputs['Detail'].default_value=2
bump=nt.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value=.08; bump.inputs['Distance'].default_value=.018
nt.links.new(noise.outputs['Fac'],bump.inputs['Height']); nt.links.new(bump.outputs['Normal'],bs.inputs['Normal'])

def smooth(obj, bevel=0):
    for f in obj.data.polygons: f.use_smooth=True
    if bevel:
        b=obj.modifiers.new('Precision edge radii','BEVEL'); b.width=bevel; b.segments=4
        b=obj.modifiers.new('Weighted face normals','WEIGHTED_NORMAL'); b.keep_sharp=True; b.weight=50
    return obj

def cylinder(name,radius,depth,z,material):
    bpy.ops.mesh.primitive_cylinder_add(vertices=192,radius=radius,depth=depth,location=(0,0,z)); o=bpy.context.object; o.name=name; o.data.materials.append(material); smooth(o,.035); return o

def torus(name,major,minor,z,material):
    bpy.ops.mesh.primitive_torus_add(major_segments=160,minor_segments=20,location=(0,0,z),major_radius=major,minor_radius=minor)
    o=bpy.context.object; o.name=name; o.data.materials.append(material); smooth(o); return o

# Low plinth, concentric inlays and a shallow central well.
cylinder('Plinth | dark machined aluminum',2.55,.20,.17,black)
torus('Plinth | copper edge inlay',2.49,.018,.263,copper)
cylinder('Central well | copper',1.13,.12,.30,copper)
cylinder('Central well | graphite inset',.99,.035,.374,black)
torus('Central well | polished rim',1.08,.027,.365,chrome)

# 10 continuous curved solid segments, independently beveled. Each is attached
# to a radially-oriented hinge; the controllers remain fully editable.
root=bpy.data.objects.new('KINETIC RING | rotate',None); sc.collection.objects.link(root)
segments=[]
N=10; R1=1.30; R2=2.30; HALF=(pi/N)-.027; MID=(R1+R2)/2
for i in range(N):
    th=2*pi*i/N
    ctrl=bpy.data.objects.new(f'Segment {i+1:02d} | radial hinge',None); sc.collection.objects.link(ctrl); ctrl.parent=root
    ctrl.rotation_euler.z=th
    steps=32; verts=[]
    for z in [-.205,.205]:
        for r in [R1,R2]:
            for j in range(steps+1):
                a=-HALF+2*HALF*j/steps; verts.append((r*cos(a)-MID,r*sin(a),z))
    L=steps+1; faces=[]
    for j in range(steps):
        faces += [(j,j+1,L+j+1,L+j), (2*L+j,3*L+j,3*L+j+1,2*L+j+1), (j,2*L+j,2*L+j+1,j+1), (L+j,L+j+1,3*L+j+1,3*L+j)]
    faces += [(0,L,3*L,2*L),(steps,2*L+steps,3*L+steps,L+steps)]
    mesh=bpy.data.meshes.new(f'Arc {i+1:02d} | solid mesh'); mesh.from_pydata(verts,[],faces); mesh.update()
    obj=bpy.data.objects.new(f'Porcelain arc {i+1:02d}',mesh); sc.collection.objects.link(obj); obj.parent=ctrl; obj.data.materials.append(ceramic); smooth(obj,.085)
    # Dark underside makes thickness readable and evokes crafted mechanical parts.
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=12,radius=.055)
    pin=bpy.context.object; pin.name=f'Flush silver detail {i+1:02d}'; pin.parent=ctrl; pin.location=(.23,0,.201); pin.scale=(1,1,.18); pin.data.materials.append(chrome); smooth(pin)
    segments.append((ctrl,th))

bpy.ops.mesh.primitive_uv_sphere_add(segments=96,ring_count=64,radius=.82,location=(0,0,1.18))
orb=bpy.context.object; orb.name='Core | copper mirror sphere'; orb.data.materials.append(copper); smooth(orb)
# Circular silver rim visually anchors the sphere, without an arbitrary particle field.
torus('Core | silver cradle',.73,.035,.63,chrome)

# Smooth periodic breathing cycle. Render only 1..144, frame 145 equals frame 1.
# The controlled wave passes around the ring; every controller returns exactly.
for frame in range(1,146):
    t=(frame-1)/144; u=sin(pi*t)**4
    root.rotation_euler.z=.13*sin(2*pi*t); root.keyframe_insert('rotation_euler',frame=frame)
    for ctrl,th in segments:
        wave=sin(pi*(t-.075*sin(th)))**4
        radius=MID+.72*wave
        ctrl.location=(radius*cos(th),radius*sin(th),.72+.23*wave)
        ctrl.rotation_euler=(0,-.24*wave,th)
        ctrl.keyframe_insert('location',frame=frame); ctrl.keyframe_insert('rotation_euler',frame=frame)
    orb.location.z=1.12+.99*sin(pi*(t-.045))**6; orb.keyframe_insert('location',frame=frame)
for obj in [root,orb]+[c for c,t in segments]:
    if obj.animation_data:
        for curve in obj.animation_data.action.fcurves:
            for k in curve.keyframe_points: k.interpolation='LINEAR'

# Seamless warm cyclorama.
bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,.025)); floor=bpy.context.object; floor.name='Infinite warm studio floor'; floor.data.materials.append(back)

def aim(obj,target): obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
def area(name,loc,power,color,size,target=(0,0,.5),size_y=None):
    bpy.ops.object.light_add(type='AREA',location=loc); o=bpy.context.object; o.name=name; o.data.energy=power; o.data.color=color; o.data.shape='DISK' if size_y is None else 'RECTANGLE'; o.data.size=size; o.data.use_shadow=name.startswith('Key')
    if size_y is not None:o.data.size_y=size_y
    aim(o,target); return o
area('Key | large warm softbox',(-4,-4,8),1050,(1,.91,.8),5,size_y=2.8)
area('Rim | cool vertical strip',(4,2,5),850,(.76,.86,1),1.7,size_y=5)
area('Fill | narrow silver reflection',(-4,4,3),220,(1,.94,.85),1.6,size_y=4)
area('Front | controlled gradient',(1,-6,3.5),65,(1,1,1),3,size_y=2)

bpy.ops.object.camera_add(location=(7,-10,9.3)); cam=bpy.context.object; cam.name='CAM | editorial three-quarter'; aim(cam,(0,0,.7)); cam.data.type='ORTHO'; cam.data.ortho_scale=8.8; sc.camera=cam
cam.data.lens=50; cam.data.clip_end=250

# Typography is rendered in Blender, anchored in camera space.
fontpath=os.path.join(HERE,'assets','DejaVuSans.ttf')
font=bpy.data.fonts.load(fontpath)
textmat=bpy.data.materials.new('Type | unlit charcoal'); textmat.use_nodes=True
n=textmat.node_tree.nodes; n.clear(); out=n.new('ShaderNodeOutputMaterial'); e=n.new('ShaderNodeEmission'); e.inputs[0].default_value=(.033,.039,.036,1); e.inputs[1].default_value=1; textmat.node_tree.links.new(e.outputs[0],out.inputs['Surface'])
def text(name,body,x,y,size,spacing=1):
    curve=bpy.data.curves.new(name,'FONT'); curve.body=body; curve.size=size; curve.space_character=spacing; curve.font=font
    o=bpy.data.objects.new(name,curve); sc.collection.objects.link(o); o.parent=cam; o.location=(x,y,-8); curve.materials.append(textmat)
    o.visible_shadow=False
    return o
text('Title','FORM / 01',-3.75,3.43,.40,1.1)
text('Subtitle','A STUDY OF BALANCE',-3.73,3.06,.145,1.15)
text('Footer left','CERAMIC  /  COPPER  /  MOTION',-3.73,-3.73,.125,1.08)
text('Footer right','BLENDER  /  EEVEE',2.12,-3.73,.125,1.08)
# Camera-facing graphics are excluded from glossy rays.
for o in sc.objects:
    if o.type=='FONT': o.visible_glossy=False; o.visible_diffuse=False; o.visible_transmission=False

sc.render.filepath='//renders/form_'
sc.frame_set(1)
# Pack the typeface so the project is self-contained.
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE,'form_01.blend'))
bpy.ops.file.make_paths_relative()
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE,'form_01.blend'))
if args.preview:
    sc.render.resolution_percentage=87; sc.eevee.taa_render_samples=24; sc.eevee.shadow_ray_count=2; sc.cycles.samples=48
if args.frames:
    for f in [int(v) for v in args.frames.split(',')]:
        sc.frame_set(f); sc.render.filepath=os.path.join(HERE,'previews',f'frame_{f:04d}.png'); bpy.ops.render.render(write_still=True)
elif args.render:
    sc.render.filepath=os.path.join(HERE,'renders','form_'); bpy.ops.render.render(animation=True)
