"""Adversarial exact-palette tests; synthetic patterns are not new artwork."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import GifImagePlugin, Image

from gif_cinema import pixel_palette as pp


def rgba(colors, size=None):
    image = Image.new('RGBA', size or (len(colors), 1))
    image.putdata([tuple(c) if len(c) == 4 else (*c, 255) for c in colors])
    return image


def source_gif(frames, delays=None, loop=0, disposal=None):
    """Write full local-table frames to exercise independent source palettes."""
    out = io.BytesIO()
    for i, frame in enumerate(frames):
        options = {'optimize': False, 'duration': (delays or [20] * len(frames))[i],
                   'disposal': (disposal or [1] * len(frames))[i],
                   'include_color_table': i != 0}
        if 'transparency' in frame.info:
            options['transparency'] = frame.info['transparency']
            options['background'] = frame.info['transparency']
        if loop is not None:
            options['loop'] = loop
        if i == 0:
            for block in GifImagePlugin.getheader(frame, info=options)[0]:
                out.write(block)
        for block in GifImagePlugin.getdata(frame, **options):
            out.write(block)
    out.write(b';')
    return out.getvalue()


def indexed(colors, values, size=None, transparent=None):
    im = Image.frombytes('P', size or (len(values), 1), bytes(values))
    palette = [c for rgb in colors for c in rgb]
    im.putpalette(palette + [0] * (768 - len(palette)))
    if transparent is not None:
        im.info['transparency'] = transparent
    return im


class PixelPaletteTests(unittest.TestCase):
    def roundtrip(self, frames, delays=None, loop=0, requested=None, scale=1):
        delays = delays or [20] * len(frames)
        plan = pp.choose_palette(frames, requested)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'result.gif'
            report = pp.encode(frames, delays, loop, plan, path, scale=scale)
            raw = path.read_bytes()
        actual = pp.decode(raw)
        expected = [frame.resize((frame.width * scale, frame.height * scale),
                                 Image.Resampling.NEAREST) for frame in frames]
        self.assertEqual(pp.timeline(expected, delays), pp.timeline(actual['frames'], actual['delays_ms']))
        self.assertEqual(actual['loop'], loop)
        self.assertEqual(pp.inspect_tables(raw), {'global_palette': bytes(plan['palette']), 'local_count': 0})
        self.assertEqual(report['duration_ms'], sum(delays))
        return actual, plan

    def test_close_colors_and_one_pixel_rare_accent(self):
        colors = [(30, 40, 50)] * 99 + [(31, 40, 50)]
        frames = [rgba(colors), rgba(colors[::-1])]
        decoded, plan = self.roundtrip(frames, [20, 170])
        self.assertEqual(plan['colors'], [(30, 40, 50), (31, 40, 50)])
        self.assertEqual(decoded['frames'][0].getpixel((99, 0)), (31, 40, 50, 255))

    def test_all_256_opaque_colors(self):
        self.roundtrip([rgba([(v, 11, 19) for v in range(256)])])

    def test_255_colors_plus_transparency(self):
        self.roundtrip([rgba([(v, 11, 19) for v in range(255)] + [(99, 33, 77, 0)])])

    def test_256_colors_plus_transparency_rejected(self):
        with self.assertRaisesRegex(ValueError, '255'):
            pp.choose_palette([rgba([(v, 11, 19) for v in range(256)] + [(0, 0, 0, 0)])])

    def test_257_union_across_frames_rejected(self):
        frames = [rgba([(v, 0, 0) for v in range(256)]), rgba([(0, 1, 0)] * 256)]
        with self.assertRaisesRegex(ValueError, '257'):
            pp.choose_palette(frames)

    def test_requested_palette_preserves_order_and_unused_colors(self):
        colors = [(201, 20, 51), (8, 9, 10), (0, 0, 0)]
        _, plan = self.roundtrip([rgba([(8, 9, 10), (0, 0, 0)])], requested=colors)
        self.assertEqual(plan['colors'], colors)
        self.assertEqual(plan['palette'][:9], [201, 20, 51, 8, 9, 10, 0, 0, 0])
        for invalid, message in [([(0, 0, 0)], 'missing'),
                                 ([(8, 9, 10)] * 2, 'duplicate'), ([], 'missing'),
                                 ([(True, 2, 3)], 'integers')]:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, message):
                pp.choose_palette([rgba([(8, 9, 10)])], invalid)

    def test_unused_requested_colors_cannot_occupy_transparent_index(self):
        with self.assertRaisesRegex(ValueError, 'transparency'):
            pp.choose_palette([rgba([(0, 0, 0, 0)])], [(v, 0, 0) for v in range(256)])

    def test_transparent_and_opaque_black_all_transparent_frames(self):
        self.roundtrip([rgba([(0, 0, 0, 255), (55, 66, 77, 0)]),
                        rgba([(12, 13, 14, 0), (0, 0, 0, 0)]),
                        rgba([(0, 0, 0, 0), (0, 0, 0, 255)])])
        actual, plan = self.roundtrip([rgba([(44, 55, 66, 0)])])
        self.assertEqual(plan['colors'], [])
        self.assertEqual(pp.choose_palette([rgba([(1, 2, 3, 0)])], []), plan)
        self.roundtrip([rgba([(1, 2, 3, 0)])], requested=[])
        self.assertEqual(actual['frames'][0].getpixel((0, 0)), (0, 0, 0, 0))

    def test_independent_local_tables(self):
        first = indexed([(20, 30, 40), (21, 30, 40)], [0, 1, 0, 1])
        second = indexed([(170, 1, 2), (20, 30, 40)], [0, 1, 0, 1])
        raw = source_gif([first, second], [20, 90], loop=7)
        self.assertEqual(pp.inspect_tables(raw)['local_count'], 1)
        decoded = pp.decode(raw)
        self.assertEqual(decoded['frames'][1].getpixel((0, 0)), (170, 1, 2, 255))
        self.roundtrip(decoded['frames'], decoded['delays_ms'], decoded['loop'])

    def test_disposal_restore_background_and_previous(self):
        colors = [(0, 0, 0), (250, 50, 20), (20, 50, 250), (50, 250, 20)]
        # A red base, blue overlay, then green overlay. 0 is transparent.
        for disposal, expected in [(2, [(0, 0, 0, 0), (50, 250, 20, 255)]),
                                   (3, [(250, 50, 20, 255), (50, 250, 20, 255)])]:
            frames = [indexed(colors, [1, 1], transparent=0),
                      indexed(colors, [2, 0], transparent=0),
                      indexed(colors, [0, 3], transparent=0)]
            raw = source_gif(frames, disposal=[1, disposal, 1])
            decoded = pp.decode(raw)
            self.assertEqual(list(pp._pixels(decoded['frames'][1])),
                             [(20, 50, 250, 255), (250, 50, 20, 255)])
            self.assertEqual(list(pp._pixels(decoded['frames'][2])), expected)
            self.roundtrip(decoded['frames'], decoded['delays_ms'])

    def test_native_delays_long_coalesced_hold_and_loops(self):
        frames = [rgba([(1, 2, 3)]), rgba([(1, 2, 3)])]
        for loop in [None, 0, 1, 65535]:
            self.roundtrip(frames, [60000, 60000], loop)
        self.roundtrip([frames[0]], [120000], loop=None)
        self.assertEqual(pp.timeline(frames, [60000, 60000])[0]['duration_ms'], 120000)

    def test_nearest_neighbor_integer_clusters(self):
        frame = rgba([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 0, 0)], (2, 2))
        decoded, _ = self.roundtrip([frame], scale=3)
        self.assertEqual(decoded['size'], (6, 6))
        for y in range(6):
            for x in range(6):
                self.assertEqual(decoded['frames'][0].getpixel((x, y)), frame.getpixel((x // 3, y // 3)))

    def test_partial_alpha_scale_and_timing_rejected(self):
        with self.assertRaisesRegex(ValueError, 'binary alpha'):
            pp.choose_palette([rgba([(1, 2, 3, 254)])])
        raw = source_gif([indexed([(0, 0, 0)], [0])])
        for scale in [True, 0, 9, 1.0, '2']:
            with self.subTest(scale=scale), patch.object(pp.Image, 'open') as opening:
                with self.assertRaisesRegex(ValueError, 'scale'):
                    pp.decode(raw, scale)
                opening.assert_not_called()
        for delays in [[10], [21], [120010], [True]]:
            with self.assertRaises(ValueError):
                self.roundtrip([rgba([(0, 0, 0)])], delays)
        with self.assertRaisesRegex(ValueError, 'total duration'):
            self.roundtrip([rgba([(0, 0, 0)])] * 2, [60000, 60010])

    def test_scaled_budget_rejected_before_decoder(self):
        raw = bytearray(source_gif([indexed([(0, 0, 0)], [0])]))
        for size, scale in [((3000, 2000), 1), ((3000, 1), 3), ((1000, 1000), 3)]:
            altered = raw[:]
            altered[6:10] = size[0].to_bytes(2, 'little') + size[1].to_bytes(2, 'little')
            with self.subTest(size=size, scale=scale), patch.object(pp.Image, 'open') as opening:
                with self.assertRaises(ValueError):
                    pp.decode(bytes(altered), scale)
                opening.assert_not_called()
        # 5 full logical canvases consume 20M samples, even with tiny descriptors.
        raw = bytearray(source_gif([indexed([(0, 0, 0)], [0])] * 5))
        raw[6:10] = (2000).to_bytes(2, 'little') * 2
        with patch.object(pp.Image, 'open') as opening:
            with self.assertRaisesRegex(ValueError, 'pixel budget'):
                pp.decode(bytes(raw))
            opening.assert_not_called()

    def test_scaled_aggregate_preflight_and_fixed_canvas(self):
        raw = bytearray(source_gif([indexed([(0, 0, 0)], [0])] * 5))
        raw[6:10] = (1000).to_bytes(2, 'little') * 2
        with patch.object(pp.Image, 'open') as opening:
            with self.assertRaisesRegex(ValueError, 'aggregate pixel budget'):
                pp.decode(bytes(raw), scale=2)
            opening.assert_not_called()
        raw = bytearray(source_gif([indexed([(0, 0, 0)], [0, 0], (2, 1))]))
        raw[6:8] = (1).to_bytes(2, 'little')
        with patch.object(pp.Image, 'open') as opening:
            with self.assertRaisesRegex(ValueError, 'fixed logical canvas'):
                pp.decode(bytes(raw))
            opening.assert_not_called()

    def test_invalid_plan_and_loop_do_not_write(self):
        frames = [rgba([(1, 2, 3)])]
        plan = pp.choose_palette(frames)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'bad.gif'
            for loop in [-1, 65536, True, 1.0]:
                with self.subTest(loop=loop), self.assertRaisesRegex(ValueError, 'loop'):
                    pp.encode(frames, [20], loop, plan, target)
                self.assertFalse(target.exists())
            plan['palette'][0] = 44
            with self.assertRaisesRegex(ValueError, 'palette plan'):
                pp.encode(frames, [20], 0, plan, target)
            self.assertFalse(target.exists())

    def assert_unsupported_before_decode(self, raw, message):
        # Fixtures must pass structural validity/resource checks, rather than
        # accidentally failing on malformed bytes before the semantic check.
        self.assertEqual(pp.cli.check_gif_limits(raw, fixed_canvas=True)['frames'], 1)
        with patch.object(pp.Image, 'open') as opening:
            with self.assertRaisesRegex(ValueError, message):
                pp.decode(raw)
            opening.assert_not_called()
        with self.assertRaisesRegex(ValueError, message):
            pp.inspect_tables(raw)

    def test_plain_text_graphics_rejected_before_decode(self):
        raw = source_gif([indexed([(0, 0, 0), (255, 255, 255)], [1])])
        table_end = 13 + (3 << ((raw[10] & 7) + 1))
        # Text grid (0,0,1,1), 1x1 character cells, white on black,
        # one ASCII character, and the required data-block terminator.
        text = (b'\x21\x01\x0c' + b'\x00\x00' * 2 + b'\x01\x00' * 2
                + b'\x01\x01\x01\x00' + b'\x01A\x00')
        self.assert_unsupported_before_decode(raw[:table_end] + text + raw[table_end:], 'plain-text')

    def test_gce_user_input_and_reserved_disposal_rejected_before_decode(self):
        raw = source_gif([indexed([(0, 0, 0)], [0])])
        packed_offset = raw.index(b'\x21\xf9\x04') + 3
        for flag, message in [(2, 'user-input')] + [(d << 2, 'reserved disposal') for d in range(4, 8)]:
            altered = bytearray(raw)
            altered[packed_offset] = flag
            with self.subTest(flag=flag):
                self.assert_unsupported_before_decode(bytes(altered), message)

    def test_pixel_aspect_metadata_rejected_before_decode(self):
        raw = bytearray(source_gif([indexed([(0, 0, 0)], [0])]))
        for value in [1, 49, 255]:
            raw[12] = value
            with self.subTest(value=value):
                self.assert_unsupported_before_decode(bytes(raw), 'pixel-aspect')

    def test_extension_signatures_inside_comment_are_not_graphics(self):
        raw = source_gif([indexed([(0, 0, 0)], [0])])
        # A comment legitimately contains the same bytes as forbidden markers.
        payload = b'\x21\x01\x0c\x21\xf9\x04\x1e'
        comment = b'\x21\xfe' + bytes([len(payload)]) + payload + b'\x00'
        altered = raw[:-1] + comment + raw[-1:]
        self.assertEqual(pp.timeline(pp.decode(altered)['frames'], [20]),
                         pp.timeline(pp.decode(raw)['frames'], [20]))

    def test_malformed_and_frame_count_predecode(self):
        valid = source_gif([indexed([(0, 0, 0)], [0])])
        for raw in [b'not gif', b'GIF89a', valid[:-1], valid[:20]]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                pp.decode(raw)
        raw = source_gif([indexed([(0, 0, 0)], [0])] * 257)
        with patch.object(pp.Image, 'open') as opening:
            with self.assertRaisesRegex(ValueError, '256 frame'):
                pp.decode(raw)
            opening.assert_not_called()


if __name__ == '__main__':
    unittest.main()
