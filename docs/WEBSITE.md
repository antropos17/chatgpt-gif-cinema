# GIF Cinema screening room

`docs/index.html`, `docs/site.css` and `docs/site.js` are the source of the new
static, English-language website. It has no backend, account system, analytics,
external font requests, generator, or paid API calls. The Python filmmaking runtime is
unchanged.

## Build

Run `python tools/build_website.py` from the checkout. This copies the exact
26-file site into `dist/website/`; serve that directory with any static host.
No Node dependencies or build framework are required. The host must support
normal byte-range requests for seeking video. This branch does not enable
GitHub Pages or change repository access/settings.

## Design and interaction

The warm paper, charcoal and restrained brown interface follows the existing
footage's palette. Full 1:1 previews are displayed without masks, rotation,
recoloring or text over the characters. Playback controls sit below the images.
The earlier saturated poster panels, marquee, spinning marks, repeated film
section and decorative shapes have been removed rather than hidden.

- The complete preview card is a keyboard-accessible film/comparison button.
- The film dialog closes with Escape, its close button or an outside click, then
  restores focus. Story-beat buttons in the astronaut dialog seek to 0, 2.56 and 5.12s.
- The global preview toggle and reduced-motion preference control automatic
  previews. There are no other decorative animations.
- Offscreen previews pause. Opening a dialog or playing a comparison pauses
  previews, including after tab switching. Media pauses when the document is hidden.
- Comparison tabs switch the video, description, heading and frame-pair link together.
- Mobile navigation stays visible. Metadata is larger and controls stay outside footage.
- macOS/Linux and Windows tabs provide usable no-key demo commands. Windows calls
  the virtual-environment executable directly, without changing execution policy.
- Copying has a visible success or fallback message. Paid-generation caveats live
  in a compact disclosure beside the starter, not a repeated marketing section.


## Typography

Open Sans is self-hosted in regular, semibold and bold. The Latin-and-punctuation
WOFF subsets have no external font dependency. Their copyright, modification notice
and Apache 2.0 license are in `assets/site/fonts/LICENSE.txt`. The interface uses one
family with upright headings and a 12px minimum for compact metadata. Supporting
copy is 14–16px. Monospace is reserved for terminal commands.

## Media truth and provenance

The website presents **existing footage**, not six new model-generated GIFs.
All source files already exist on main. Original full films are not changed.
The three public comparison files retain their embedded labels and frame rates.

- Astronaut: exact `astronaut-native-film.mp4`, 7.68 seconds, three shots, 48 source
  drawings at 160ms holds, 25fps presentation, silent. Public CLI output.
- Cat: full `cat-film.mp4`, 57.2 seconds, silent. Local compositing/framing and
  selective interpolation are outside the public CLI. Poster teaser is the
  five-second excerpt from source time 3 to 8 seconds, re-encoded for the web.
- Dog: full 10.24-second native-vs-local-interpolation comparison. Poster teaser
  shows the native left panel only for the first 5.12 seconds. It is not a newly
  generated standalone take. Cropping removes the comparison heading only from
  this explicitly labeled teaser; the full comparison remains unmodified.

`assets/site/provenance.json` records source/output hashes, media facts and the
exact teaser extraction operations. The JPEG posters are single decoded frames
from those source or teaser videos. Web titles are editorial names, not new films.
Original artwork may contain green objects; the interface uses warm paper, charcoal
and brown. No original footage is recolored.

GIF Factory's gallery-first structure informed the presentation. The current
film-first design gives the original footage room instead of overlaying poster art. No GIF Factory artwork, fonts or
code are copied. The existing source-available evaluation license is unchanged.

## Archival 3D reference

The separate Chrome Knot section presents one existing 3.2-second procedural
Blender EEVEE loop, 512 × 512, 80 unique frames. It is not native API output,
not six variations, and not part of the public CLI. The source asset and provenance
are in `assets/motion-elements/`; the site copies only its MP4 and original poster.
Its automatic preview uses the same global pause, visibility and reduced-motion
controller as the character studies. Opening it pauses the background previews.
