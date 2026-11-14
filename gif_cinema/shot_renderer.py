"""Local sprite performances, camera coverage and authored light effects.

All artwork, schedules, paths and event parameters come from a shot project.
There are no example imports, code plugins, downloads or inference backends.
"""
import array
import math
import random
import wave

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

    def actors(self, image, t):
        for actor in self.project['actors']:
            for track in actor['tracks']:
                if track['start'] <= t < track['end']:
                    phase = t - track['origin']
                    if track['loop']:
                        phase %= track['duration']
                    u = max(0, min(1, phase / track['duration']))
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
        p = self.project
        im = self.background.copy()
        shade = Image.new('RGBA', self.size); sd = ImageDraw.Draw(shade)
        for shadow in p['shadows']:
            x, y = shadow['xy']; rx, ry = shadow['radius']
            sd.ellipse((x-rx, y-ry, x+rx, y+ry), fill=tuple(shadow['color']))
        im = Image.alpha_composite(im.convert('RGBA'), shade.filter(ImageFilter.GaussianBlur(p['shadow_blur']))).convert('RGB')
        self.actors(im, t)
        front_core, front_glow = self.lights([e for e in p['effects'] if e['plane'] == 'front'], t)
        core, glow = self.lights([e for e in p['effects'] if e['plane'] == 'behind'], t)
        gain = scene['effects']['gain']
        if gain != 1:
            core = ImageEnhance.Brightness(core).enhance(gain)
            glow = ImageEnhance.Brightness(glow).enhance(gain)
        occlusion = ImageChops.difference(im, self.background).convert('L').point(
            lambda v: 255 if v > p['occlusion_threshold'] else 0).filter(ImageFilter.GaussianBlur(p['occlusion_blur']))
        glow = glow.filter(ImageFilter.GaussianBlur(p['glow_blur']))
        glow.paste((0, 0, 0), (0, 0, *self.size), occlusion)
        core.paste((0, 0, 0), (0, 0, *self.size), occlusion)
        im = ImageChops.add(ImageChops.add(im, glow), core)
        im = ImageChops.add(ImageChops.add(im, front_glow.filter(ImageFilter.GaussianBlur(p['glow_blur']))), front_core)
        overlay = Image.new('RGBA', self.size); draw = ImageDraw.Draw(overlay)
        for e in p['overlays']:
            for x, y, speed, phase in e['particles']:
                xx = (x+t*speed) % e['wrap']-e['offset']; yy = y+math.sin(t*e['speed']+phase)*e['amplitude']
                r = e['radius'][0]+speed/e['radius'][1]
                draw.ellipse((xx-r, yy-r*e['aspect'], xx+r, yy+r*e['aspect']), fill=tuple(e['color']))
        im = Image.alpha_composite(im.convert('RGBA'), overlay).convert('RGB')
        box = scene['camera']; push = p['camera_push']
        z = 1+push['amplitude']*math.sin(t*push['speed'])
        cx, cy = (box[0]+box[2])/2, (box[1]+box[3])/2
        bw, bh = (box[2]-box[0])/z, (box[3]-box[1])/z
        return im.crop((cx-bw/2, cy-bh/2, cx+bw/2, cy+bh/2)).resize(self.size, Image.Resampling.LANCZOS)

    def sound(self, path):
        p = self.project; audio = p['audio']; rate = audio['rate']
        duration = audio['duration']; n = round(duration*rate)
        left, right = [0.0]*n, [0.0]*n
        for event in audio['tones']:
            start, length, freq, gain, pan = event
            begin, count = round(start*rate), round(length*rate)
            for j in range(min(count, n-begin)):
                u = j/rate; envelope = (1-math.exp(-u*40))*math.exp(-u*3/max(.1, length))
                v = (math.sin(math.tau*freq*u)+.3*math.sin(math.tau*freq*2.003*u))*envelope*gain
                left[begin+j] += v*(1-pan)*.5; right[begin+j] += v*(1+pan)*.5
        for start, end, seed, gain in audio['noise']:
            rng = random.Random(seed); v = 0
            for i in range(round(start*rate), round(end*rate)):
                u = (i/rate-start)/(end-start); v = .88*v+.12*rng.uniform(-1, 1)
                val = v*math.sin(math.pi*u)**2*gain; pan = math.sin(u*math.pi-math.pi/2)
                left[i] += val*(1-pan); right[i] += val*(1+pan)
        out = array.array('h')
        lo = round(p['scenes'][0]['start_frame']/p['fps']*rate)
        hi = round(p['scenes'][-1]['end_frame']/p['fps']*rate)
        for i in range(lo, hi):
            fade = min(1, i/rate/audio['fade_in'], (duration-i/rate)/audio['fade_out'])
            out.extend([round(math.tanh(left[i])*fade*26000), round(math.tanh(right[i])*fade*26000)])
        if __import__('sys').byteorder != 'little':
            out.byteswap()
        with wave.open(str(path), 'wb') as stream:
            stream.setnchannels(2); stream.setsampwidth(2); stream.setframerate(rate); stream.writeframes(out.tobytes())
