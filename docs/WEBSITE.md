# GIF Cinema screening room

`docs/index.html`, `docs/site.css` and `docs/site.js` are the source of the new
static, English-language website. It has no backend, account system, analytics,
external fonts, generator, or paid API calls. The Python filmmaking runtime is
unchanged. The user's newer request for a website supersedes the older no-website
milestone text in `AGENTS.md` for this presentation-only work.

## Build

Run `python tools/build_website.py` from the checkout. This copies the exact
20-file site into `dist/website/`; serve that directory with any static host.
No Node dependencies or build framework are required. The host must support
normal byte-range requests for seeking video. This branch does not enable
GitHub Pages or change repository access/settings.

## What is interactive

- Three animated character posters open full films/comparisons in a keyboard-
  dismissible, focus-restoring dialog.
- A global motion toggle pauses the decorative ticker, rotating marks and
  poster loops. Reduced-motion preference starts them paused. Explicitly played
  films remain user-controlled.
- Offscreen/background-tab poster videos pause to avoid unnecessary playback.
- Three storyboard buttons seek the public 7.68-second film to 0, 2.56 and 5.12s.
- Cat, astronaut and dog tabs switch the comparison video, explanatory note
  and actual frame-pair link together.
- The demo command is copyable, with a visible success or fallback message.

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
Original artwork may contain green objects; the site's design palette is cream,
ink, vermillion, lavender and gold. No original footage is recolored.

GIF Factory's gallery-first structure, bold poster typography and independent
character palettes informed the presentation. No GIF Factory artwork, fonts or
code are copied. The existing source-available evaluation license is unchanged.
