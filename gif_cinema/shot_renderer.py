"""Local sprite performances, camera coverage and authored light effects.

All artwork, schedules, paths and event parameters come from a shot project.
There are no example imports, code plugins, downloads or inference backends.
"""
import array
from fractions import Fraction
import math
import random
import wave

import PIL
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter


def ease(u):
    u = max(0, min(1, u))
    return u * u * (3 - 2 * u)


def mix(a, b, u):
    return tuple(x + (y - x) * u for x, y in zip(a, b))


def bez(a, b, c, u):
    return tuple((1-u)**2*x + 2*(1-u)*u*y + u*u*z for x, y, z in zip(a, b, c))


def path_at(segments, t):
    for segment in segments:
        if t < segment['end']:
            # An explicit authored duration preserves its floating-point clock;
            # subtracting two absolute endpoints can alter raster rounding.
            u = (t - segment['start']) / segment.get('duration', segment['end'] - segment['start'])
            if segment.get('ease', False):
                u = ease(u)
            points = segment['points']
            if segment['kind'] == 'orbit':
                a = u * math.tau
                return (points[0][0] + segment['radius'][0]*math.sin(a),
                        points[0][1] - segment['radius'][1]*math.sin(a/2))
            return bez(*points, u) if len(points) == 3 else mix(*points, u)
    return tuple(segments[-1]['points'][-1])


def _bounded_blur(image, radius, bounds=None):
    """Use the unchanged finite Pillow filter on an exact zero-padded region.

    Only tested implementations/modes qualify. Three extended box passes reach
    at most ceil(radius)+1 pixels each; extra zero padding keeps the crop's
    artificial edges from influencing nonzero output. Actual canvas edges stay.
    Unknown Pillow versions retain the full-image path, never an approximation.
    """
    if (PIL.__version__ not in ('10.1.0', '13.0.0') or image.mode not in ('RGB', 'L')
            or type(radius) not in (int, float) or not math.isfinite(radius) or not 0 <= radius <= 64):
        return image.filter(ImageFilter.GaussianBlur(radius))
    if bounds is None:
        bounds = image.getbbox()
    if bounds is None:
        return image.copy()
    padding = 3*(math.ceil(radius)+1)
    left, top, right, bottom = bounds
    region = (max(0,left-padding), max(0,top-padding),
              min(image.width,right+padding), min(image.height,bottom+padding))
    if (region[2]-region[0])*(region[3]-region[1])*4 >= image.width*image.height*3:
        return image.filter(ImageFilter.GaussianBlur(radius))
    blurred = image.crop(region).filter(ImageFilter.GaussianBlur(radius))
    result = Image.new(image.mode, image.size)
    result.paste(blurred, region)
    result.info = image.info.copy()
    return result


def _composite_overlay(image, overlay):
    """Blend onto an owned opaque RGB frame without an RGBA round-trip.

    With destination alpha 255, masked paste gives the same rounded RGB samples
    as source-over. The RGBA overlay is also its alpha mask, not a premultiplied
    source. Mutate only this frame, never the retained stage or decoded sprites.
    Keep the old path for different modes/sizes rather than applying opaque math
    to a future transparent canvas.
    """
    if (image.mode == 'RGB' and 'transparency' not in image.info
            and overlay.mode == 'RGBA' and image.size == overlay.size):
        image.paste(overlay, (0, 0), overlay)
        return image
    return Image.alpha_composite(image.convert('RGBA'), overlay).convert('RGB')


class Renderer:
    def __init__(self, project, paths):
        self.project = project
        self.size = (project['width'], project['height'])
        with Image.open(paths[project['background']]) as image:
            self.background = image.convert('RGB')
        self.clips = {}
        for name, clip in project['clips'].items():
            frames = []
            x, y = clip['xy']
            w, h = clip['tile_size']
            back = self.background.crop((x, y, x+w, y+h))
            with Image.open(paths[clip['source']]) as sheet:
                for i in range(clip['frames']):
                    col, row = i % clip['columns'], i // clip['columns']
                    tile = sheet.crop((col*w, row*h, (col+1)*w, (row+1)*h)).convert('RGB')
                    if clip['mask'] == 'background-difference':
                        mask = ImageChops.difference(tile, back).convert('L').point(
                            lambda v: 255 if v > clip['threshold'] else 0).filter(ImageFilter.GaussianBlur(clip['blur']))
                    else:
                        mask = sheet.crop((col*w, row*h, (col+1)*w, (row+1)*h)).convert('RGBA').getchannel('A')
                    frames.append((tile, mask))
            self.clips[name] = frames
        self._shadow_key = None
        self._shadowed_background = None
        self._background_with_shadows()

    def _background_with_shadows(self):
        """Cache only the static stage; retain the original for masks/occlusion.

        Shadow recipe edits invalidate the cache. Dynamic actors, lights, camera
        and overlays are still evaluated for every requested source timestamp.
        The loaded background image is renderer-owned, like the decoded clips.
        """
        p = self.project
        key = (p['shadow_blur'], tuple((tuple(s['xy']), tuple(s['radius']), tuple(s['color']))
                                      for s in p['shadows']))
        if key != self._shadow_key:
            shade = Image.new('RGBA', self.size)
            draw = ImageDraw.Draw(shade)
            for shadow in p['shadows']:
                x, y = shadow['xy']; rx, ry = shadow['radius']
                draw.ellipse((x-rx, y-ry, x+rx, y+ry), fill=tuple(shadow['color']))
            self._shadowed_background = Image.alpha_composite(self.background.convert('RGBA'),
                shade.filter(ImageFilter.GaussianBlur(p['shadow_blur']))).convert('RGB')
            self._shadow_key = key
        return self._shadowed_background

    def actors(self, image, t):
        # Pose selection is discrete: float modulo can turn an exact cycle start
        # into its final pose (e.g. .6 % .2). Interpret authored decimal seconds
        # exactly and retain the native encoder's rational frame/fps clock. No
        # epsilon snapping: a genuine sample just before a cut remains before it.
        clock = t if isinstance(t, Fraction) else Fraction(str(t))
        for actor in self.project['actors']:
            for track in actor['tracks']:
                if Fraction(str(track['start'])) <= clock < Fraction(str(track['end'])):
                    phase = clock - Fraction(str(track['origin']))
                    duration = Fraction(str(track['duration']))
                    if track['loop']:
                        phase %= duration
                    u = max(0, min(1, phase / duration))
                    index = round(track['first'] + u * (track['last'] - track['first']))
                    tile, mask = self.clips[track['clip']][index]
                    image.paste(tile, tuple(self.project['clips'][track['clip']]['xy']), mask)
                    break

    def lights(self, effects, t):
        core, glow = Image.new('RGB', self.size), Image.new('RGB', self.size)
        d, g = ImageDraw.Draw(core), ImageDraw.Draw(glow)

        def light(x, y, r=2, c=(125, 238, 245), p=1):
            p = max(0, min(1, p))
            c = tuple(int(v*p) for v in c)
            g.ellipse((x-r*4, y-r*4, x+r*4, y+r*4), fill=tuple(int(v*.65) for v in c))
            d.ellipse((x-r, y-r, x+r, y+r), fill=c)
            if r > 3:
                d.ellipse((x-r*.35, y-r*.35, x+r*.35, y+r*.35), fill=tuple(int(v*p) for v in (245, 255, 248)))

        for e in effects:
            kind = e['type']
            if kind == 'ambient':
                for x, y, r, a in e['particles']:
                    light(x+e['drift']*math.sin(t*e['speed'][0]+a), y+e['drift']*math.cos(t*e['speed'][1]+a),
                          r, e['color'], e['strength'][0]+e['strength'][1]*math.sin(t*e['flicker']+a)**2)
            elif kind == 'path-light' and e['start'] < t < e['end']:
                x, y = path_at(e['path'], t)
                power = ease((t-e['start'])/e['fade_in'])*(1-ease((t-e['fade_out'])/(e['end']-e['fade_out'])))
                if e['trail_start'] < t < e['trail_end']:
                    pts = [path_at(e['path'], max(e['trail_start'], t-i*e['trail_step'])) for i in range(e['trail_samples'])]
                    for i in range(len(pts)-1):
                        v = int(210*(1-i/len(pts))*power)
                        g.line([pts[i], pts[i+1]], fill=(v//3, v*3//4, v), width=max(1, 15-i//4))
                        d.line([pts[i], pts[i+1]], fill=(v//2, v, v), width=max(1, 5-i//10))
                light(x, y, e['radius']+math.sin(t*e['pulse']), e['color'], power)
                for k in range(e['satellites']):
                    a = t*e['orbit_speed']+k*math.tau/e['satellites']
                    r = e['orbit_radius']+e['orbit_wobble']*math.sin(t*e['orbit_speed'])
                    light(x+math.cos(a)*r, y+math.sin(a)*r*e['orbit_aspect'], e['satellite_radius'], e['color'], power)
            elif kind == 'burst':
                u = t-e['start']
                if 0 <= u < e['duration']:
                    x, y = e['xy']; rr = e['radius']+u*e['speed']; v = 1-u/e['duration']
                    col = tuple(int(c*v) for c in e['color'])
                    g.ellipse((x-rr, y-rr*e['aspect'], x+rr, y+rr*e['aspect']), outline=col, width=e['width'])
                    for k in range(e['count']):
                        a = k*math.tau/e['count']+e['angle']
                        light(x+math.cos(a)*u*e['scatter'][0], y+math.sin(a)*u*e['scatter'][1], e['particle_radius'], e['color'], v)
            elif kind == 'ribbons' and t >= e['start']:
                u = t-e['start']
                for band in range(e['bands']):
                    pts = []
                    for i in range(e['samples']):
                        q = i/(e['samples']-1); arrival = ease(u/e['travel'])
                        x = e['origin'][0]+(q*2-1)*e['spread']*arrival
                        y = e['origin'][1]-e['rise']*arrival+math.sin(q*math.tau*e['waves']-u*e['speed']+band*e['phase'])*e['amplitude']*arrival
                        pts.append((x, y+band*e['spacing']))
                    strength = ease(u/e['fade_in'])*(1-ease((u-e['fade_out'])/e['fade_duration']))
                    col = tuple(int(v*strength) for v in e['color'])
                    if strength > 0:
                        g.line(pts, fill=col, width=e['glow_width'])
                        d.line(pts, fill=tuple(int(v*.8) for v in col), width=e['width'])
            elif kind == 'swarm' and t >= e['start']:
                u = t-e['start']
                for i, (a, s, q, phase) in enumerate(e['particles']):
                    target = e['targets'][i]; travel = ease((u-q*e['delay'])/e['travel'])
                    x, y = bez(e['origin'], (e['control'][0]+math.cos(a)*e['spread'], e['control'][1]), target, travel)
                    x += math.sin(u*phase+a)*e['wobble'][0]*travel
                    y += math.cos(u*e['speed']+a)*e['wobble'][1]*travel
                    strength = ease((u-q*e['delay'])/e['fade_in']); col = e['colors'][bool(i % e['color_every'])]
                    light(x, y, e['radius'][0]+s*e['radius'][1], col, strength*(e['strength'][0]+e['strength'][1]*math.sin(u*e['flicker']+a)**2))
                    if i % e['star_every'] == 0 and travel > e['star_after']:
                        v = int(e['star_strength']*strength); r = e['star_radius']
                        d.line((x-r, y, x+r, y), fill=(v, v, v//2))
                        d.line((x, y-r, x, y+r), fill=(v, v, v//2))
            elif kind == 'arrival':
                x, y = e['xy']; u = t-e['start']
                if -e['travel'] < u < 0:
                    px, py = bez(*e['path'], (u+e['travel'])/e['travel'])
                    light(px, py, e['flight_radius'], e['flight_color'])
                if u >= 0:
                    light(x, y, e['radius'], e['color'], ease(u/e['fade_in'])*e['strength'])
                    if u < e['ring_duration']:
                        rr = e['ring_radius']+u*e['ring_speed']; v = int((1-u/e['ring_duration'])*e['ring_strength'])
                        g.ellipse((x-rr, y-rr, x+rr, y+rr), outline=(v, int(v*.65), v//3), width=e['ring_width'])
        return core, glow

    def frame(self, t, scene):
        actor_time = t
        # Preserve the established float raster/effects/camera clock. Only the
        # authored actor pose lookup needs exact rational boundaries.
        if isinstance(t, Fraction):
            t = float(t)
        p = self.project
        im = self._background_with_shadows().copy()
        self.actors(im, actor_time)
        front_core, front_glow = self.lights([e for e in p['effects'] if e['plane'] == 'front'], t)
        core, glow = self.lights([e for e in p['effects'] if e['plane'] == 'behind'], t)
        gain = scene['effects']['gain']
        if gain != 1:
            core = ImageEnhance.Brightness(core).enhance(gain)
            glow = ImageEnhance.Brightness(glow).enhance(gain)
        # Check actual RGB pixels after gain, not effect schedules or grayscale
        # brightness. Even a one-valued blue pixel must take the original path.
        core_bounds, glow_bounds = core.getbbox(), glow.getbbox()
        has_core, has_glow = core_bounds is not None, glow_bounds is not None
        if has_core or has_glow:
            occlusion = ImageChops.difference(im, self.background).convert('L').point(
                lambda v: 255 if v > p['occlusion_threshold'] else 0)
            occlusion = _bounded_blur(occlusion, p['occlusion_blur'])
            if has_glow:
                glow = _bounded_blur(glow, p['glow_blur'], glow_bounds)
                glow.paste((0, 0, 0), (0, 0, *self.size), occlusion)
                im = ImageChops.add(im, glow)
            if has_core:
                core.paste((0, 0, 0), (0, 0, *self.size), occlusion)
                im = ImageChops.add(im, core)
        front_glow_bounds = front_glow.getbbox()
        if front_glow_bounds is not None:
            im = ImageChops.add(im, _bounded_blur(front_glow, p['glow_blur'], front_glow_bounds))
        if front_core.getbbox() is not None:
            im = ImageChops.add(im, front_core)
        # No overlay plane exists in this recipe; keep the owned frame as-is.
        if p['overlays']:
            overlay = Image.new('RGBA', self.size); draw = ImageDraw.Draw(overlay)
            for e in p['overlays']:
                for x, y, speed, phase in e['particles']:
                    xx = (x+t*speed) % e['wrap']-e['offset']; yy = y+math.sin(t*e['speed']+phase)*e['amplitude']
                    r = e['radius'][0]+speed/e['radius'][1]
                    draw.ellipse((xx-r, yy-r*e['aspect'], xx+r, yy+r*e['aspect']), fill=tuple(e['color']))
            im = _composite_overlay(im, overlay)
        box = scene['camera']; push = p['camera_push']
        z = 1+push['amplitude']*math.sin(t*push['speed'])
        cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
        bw, bh = (box[2]-box[0])/z, (box[3]-box[1])/z
        return im.crop((cx-bw/2, cy-bh/2, cx+bw/2, cy+bh/2)).resize(self.size, Image.Resampling.LANCZOS)

    def sound(self, path):
        """Write this renderer's project audio without changing the source clock."""
        write_sound(self.project, path)


def write_reused_sound(project, paths, path):
    """Keep source decode validation without preparing unused visual caches.

    The previous Renderer decoded even unused clips before writing audio.
    Headers, hashes or PNG CRC verification alone do not validate compressed
    pixels. Load each unique original source, but retain no atlas/tile/mask cache.
    A one-pixel sample preserves the required mode-conversion checks as well.
    """
    sources = dict.fromkeys([project['background'],
                             *(clip['source'] for clip in project['clips'].values())])
    for name in sources:
        with Image.open(paths[name]) as image:
            image.load()
            sample = image.crop((0, 0, 1, 1))
            sample.convert('RGB')
            if any(clip['source'] == name and clip['mask'] == 'alpha'
                   for clip in project['clips'].values()):
                sample.convert('RGBA')
        del image, sample
    write_sound(project, path)


def write_sound(project, path):
    """Write bounded PCM blocks with the original absolute sample clock.

    Each sample retains tone order, then noise order, then fade/saturation.
    Noise generators and recurrence state span blocks; no event is reseeded.
    The caller writes into a private build attempt before verification.
    """
    p = project; audio = p['audio']; rate = audio['rate']
    duration = audio['duration']; n = round(duration*rate)
    lo = round(p['scenes'][0]['start_frame']/p['fps']*rate)
    hi = round(p['scenes'][-1]['end_frame']/p['fps']*rate)
    noises = [(start, end, random.Random(seed), gain, 0.0)
              for start, end, seed, gain in audio['noise']]
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(rate)
        stream.setnframes(hi-lo)
        # Synthesize the prefix too: a cropped performance must retain the
        # seeded noise recurrence that began before its selected first frame.
        for block_start in range(0, hi, 4096):
            block_end = min(block_start+4096, hi)
            left, right = [0.0]*(block_end-block_start), [0.0]*(block_end-block_start)
            for start, length, freq, gain, pan in audio['tones']:
                begin, count = round(start*rate), round(length*rate)
                for i in range(max(begin, block_start), min(begin+count, n, block_end)):
                    j = i-begin
                    u = j/rate; envelope = (1-math.exp(-u*40))*math.exp(-u*3/max(.1, length))
                    v = (math.sin(math.tau*freq*u)+.3*math.sin(math.tau*freq*2.003*u))*envelope*gain
                    left[i-block_start] += v*(1-pan)*.5
                    right[i-block_start] += v*(1+pan)*.5
            for index, (start, end, rng, gain, v) in enumerate(noises):
                for i in range(max(round(start*rate), block_start), min(round(end*rate), block_end)):
                    u = (i/rate-start)/(end-start); v = .88*v+.12*rng.uniform(-1, 1)
                    val = v*math.sin(math.pi*u)**2*gain; pan = math.sin(u*math.pi-math.pi/2)
                    left[i-block_start] += val*(1-pan)
                    right[i-block_start] += val*(1+pan)
                noises[index] = (start, end, rng, gain, v)
            out = array.array('h')
            for i in range(max(lo, block_start), block_end):
                fade = min(1, i/rate/audio['fade_in'], (duration-i/rate)/audio['fade_out'])
                out.extend([round(math.tanh(left[i-block_start])*fade*26000),
                            round(math.tanh(right[i-block_start])*fade*26000)])
            if __import__('sys').byteorder != 'little':
                out.byteswap()
            stream.writeframesraw(out.tobytes())
