"""Original Blender 4.3+ motion elements. No model calls. New output directories only.
blender -b -t 8 --python tools/motion_elements/render_studio.py -- --out NEW_DIR
"""
import argparse,json,math,sys
from pathlib import Path
import bpy


def aim(ob): ob.rotation_euler=(-ob.location).to_track_quat('-Z','Y').to_euler()
def area(name,loc,color,power,width,height):
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.color=color;data.shape='RECTANGLE';data.size=width;data.size_y=height
    ob=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(ob);ob.location=loc;aim(ob)
def material(name,color,metal=1,rough=.2):
    m=bpy.data.materials.new(name);m.use_nodes=True
    b=m.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(*color,1);b.inputs['Metallic'].default_value=metal;b.inputs['Roughness'].default_value=rough;b.inputs['Coat Weight'].default_value=.25
    return m
def curve(name,points,radius,mat):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D';data.bevel_depth=radius;data.bevel_resolution=5
    sp=data.splines.new('POLY');sp.points.add(len(points)-1)
    for p,v in zip(sp.points,points):p.co=(*v,1)
    sp.use_cyclic_u=True
    ob=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(ob);ob.data.materials.append(mat);return ob

def setup(a):
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    sc=bpy.context.scene;sc.render.engine='BLENDER_EEVEE_NEXT';sc.eevee.taa_render_samples=a.samples;sc.cycles.device='CPU';sc.cycles.samples=a.samples;sc.cycles.use_denoising=False;sc.cycles.seed=17;sc.cycles.use_animated_seed=False;sc.cycles.max_bounces=6
    sc.render.resolution_x=sc.render.resolution_y=a.size;sc.render.resolution_percentage=100;sc.render.image_settings.file_format='PNG';sc.render.image_settings.color_mode='RGB';sc.render.fps=25
    sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast';sc.view_settings.exposure=.3
    sc.world.use_nodes=True;sc.world.node_tree.nodes['Background'].inputs[0].default_value=(.025,.025,.04,1);sc.world.node_tree.nodes['Background'].inputs[1].default_value=.25
    bpy.ops.object.camera_add(location=(0,-7.8,3.2));cam=bpy.context.object;cam.data.type='ORTHO';cam.data.ortho_scale=5.3;aim(cam);sc.camera=cam
    area('Key softbox',(-3,-4,5),(1,.97,.93),1100,5,2)
    area('Cyan rim',(4,0,2),(.26,.76,1),1250,4,.7)
    area('Violet strip',(-3,1,.8),(.63,.27,1),1500,4,.5)
    area('Top white',(0,2,5),(1,1,1),1600,4,1)
    area('Front fill',(0,-5,0),(.55,.7,1),150,2,4)
    bpy.ops.mesh.primitive_plane_add(size=200,location=(0,0,-2));bpy.context.object.data.materials.append(material('Graphite',(.009,.011,.017),0,.5))
    return sc

def chrome():
    pts=[]
    for i in range(640):
        t=math.tau*i/640;r=1.15+.36*math.cos(3*t);pts.append((r*math.cos(2*t),r*math.sin(2*t),.52*math.sin(3*t)))
    ob=curve('Continuous trefoil',pts,.24,material('Polished titanium',(.7,.74,.79),1,.19));ob.rotation_euler=(1.17,0,0)
    rig=bpy.data.objects.new('Turntable',None);bpy.context.collection.objects.link(rig);ob.parent=rig
    def step(p):rig.rotation_euler=(.16*math.sin(math.tau*p),.2*math.cos(math.tau*p),math.tau*p)
    return step

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True,type=Path);p.add_argument('--study',choices=('chrome',),default='chrome');p.add_argument('--frames',type=int,default=80);p.add_argument('--size',type=int,default=512);p.add_argument('--samples',type=int,default=24);p.add_argument('--preview',action='store_true')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);out=a.out.absolute()
    if out.exists() or any(x.is_symlink() for x in (out,*out.parents)):raise ValueError('Use a NEW directory without symlinks')
    if not 1<=a.frames<=250 or not 128<=a.size<=1080 or not 4<=a.samples<=256:raise ValueError('Render bounds exceeded')
    out.mkdir(parents=True);sc=setup(a);step=chrome();count=1 if a.preview else a.frames
    for i in range(count):step(i/a.frames);sc.render.filepath=str(out/f'{i:04d}.png');bpy.ops.render.render(write_still=True)
    (out/'render.json').write_text(json.dumps({'study':a.study,'frames':count,'dimensions':[a.size,a.size],'fps':25,'samples':a.samples,'renderer':'Blender EEVEE','api_calls':0,'loop':'phase=index/frame_count, excluding duplicated endpoint'},indent=2)+'\n')
