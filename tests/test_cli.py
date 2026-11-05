import unittest
from gif_cinema.cli import make_payload, build_parser

class APIPayloadTests(unittest.TestCase):
    def test_gif_payload(self):
        p=make_payload("A waving astronaut")
        self.assertEqual(p["output_format"],"gif")
        self.assertEqual(p["frame_count"],9)

    def test_frames_range(self):
        with self.assertRaises(ValueError):
            make_payload("x",frames=1)
        with self.assertRaises(ValueError):
            make_payload("x",frames=65)

    def test_model(self):
        with self.assertRaises(ValueError):
            make_payload("x",model="invalid")

    def test_size(self):
        with self.assertRaises(ValueError):
            make_payload("x",size="123x70")

    def test_cli(self):
        args=build_parser().parse_args(["generate","A moving leaf","-o","output/a.gif"])
        self.assertEqual(args.output,"output/a.gif")

if __name__=="__main__":
    unittest.main()
