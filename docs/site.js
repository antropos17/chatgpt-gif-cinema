'use strict';
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const loops = [...document.querySelectorAll('[data-loop]')];
const toggle = document.getElementById('motion-toggle');
const dialog = document.getElementById('film-dialog');
const dialogVideo = document.getElementById('dialog-video');
const comparison = document.getElementById('compare-video');
const storyBeats = document.getElementById('story-beats');
let motionPaused = reduceMotion.matches;
let lastTrigger = null;
function syncPreviews() {
  loops.forEach(video => {
    const shouldPlay = !motionPaused && !document.hidden && !dialog.open && comparison.paused && video.dataset.visible === 'true';
    if (shouldPlay) video.play().catch(() => {});
    else video.pause();
  });
}
function setMotion(paused) {
  motionPaused = paused;
  toggle.setAttribute('aria-pressed', String(paused));
  toggle.innerHTML = paused
    ? '<span class="play-icon" aria-hidden="true"></span><span>Play previews</span>'
    : '<span class="pause-icon" aria-hidden="true"></span><span>Pause previews</span>';
  syncPreviews();
}
const loopObserver = new IntersectionObserver(entries => {
  entries.forEach(({target, isIntersecting}) => { target.dataset.visible = String(isIntersecting); });
  syncPreviews();
}, {threshold: .25});
loops.forEach(video => loopObserver.observe(video));
setMotion(motionPaused);
toggle.addEventListener('click', () => setMotion(!motionPaused));
reduceMotion.addEventListener('change', event => setMotion(event.matches));
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { comparison.pause(); dialogVideo.pause(); }
  syncPreviews();
});
comparison.addEventListener('play', syncPreviews);
comparison.addEventListener('pause', syncPreviews);
comparison.addEventListener('ended', syncPreviews);
const films = {
  chrome: {
    title: 'Chrome Knot',
    type: 'BLENDER EEVEE REFERENCE · 3.2 SECONDS · SILENT',
    src: 'assets/motion-elements/chrome.mp4',
    note: 'One archival procedural 3D loop, rendered in Blender EEVEE and encoded locally. Not native model output or a feature of the public CLI. 80 unique frames, 512 × 512, no API calls.'
  },
  astronaut: {
    title: 'A Signal in Space',
    type: 'PUBLIC CLI FILM · 7.68 SECONDS · SILENT',
    src: 'assets/showcase/astronaut-native-film.mp4',
    note: 'Three existing 2.56-second GIF shots assembled by the public CLI. 512 × 512, 25 fps export; 16 source drawings per shot held for 160 ms. No interpolation or new provider calls.'
  },
  cat: {
    title: 'The Art of Doing Nothing',
    type: 'LOCALLY FINISHED FILM · 57.2 SECONDS · SILENT',
    src: 'assets/showcase/cat-film.mp4',
    note: 'The existing full cat film: short generated takes assembled and finished locally. Compositing, framing cleanup and selective interpolation use additional tools outside the public CLI. This is not a single 57-second model generation.'
  },
  dog: {
    title: 'Eyes on the Ball',
    type: 'NATIVE / FINISHED COMPARISON · 10.24 SECONDS · SILENT',
    src: 'assets/showcase/dog-comparison.mp4',
    note: 'Four existing takes, shown side by side. Left: original native GIF timing. Right: local interpolation. The 50 fps comparison is not native 50 fps generation, and additional frames do not repair prop or pose errors.'
  }
};
document.querySelectorAll('[data-film]').forEach(button => button.addEventListener('click', () => {
  const name = button.dataset.film;
  const film = films[name];
  lastTrigger = button;
  document.getElementById('dialog-title').textContent = film.title;
  document.getElementById('dialog-type').textContent = film.type;
  document.getElementById('dialog-note').textContent = film.note;
  document.getElementById('dialog-source').href = film.src;
  dialogVideo.setAttribute('aria-label', film.title);
  dialogVideo.src = film.src;
  storyBeats.hidden = name !== 'astronaut';
  comparison.pause();
  dialog.showModal();
  document.body.classList.add('dialog-open');
  syncPreviews();
  dialogVideo.play().catch(() => {});
}));
document.getElementById('close-dialog').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => {
  if (event.target !== dialog) return;
  const rect = dialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
});
dialog.addEventListener('close', () => {
  dialogVideo.pause();
  dialogVideo.removeAttribute('src');
  dialogVideo.load();
  document.body.classList.remove('dialog-open');
  syncPreviews();
  lastTrigger?.focus();
});
const beats = [...document.querySelectorAll('[data-seek]')];
beats.forEach(button => button.addEventListener('click', () => {
  dialogVideo.currentTime = Number(button.dataset.seek);
  dialogVideo.play().catch(() => {});
}));
dialogVideo.addEventListener('timeupdate', () => {
  if (storyBeats.hidden) return;
  beats.forEach((button, index) => button.setAttribute('aria-pressed', String(Math.min(2, Math.floor(dialogVideo.currentTime / 2.56)) === index)));
});
const comparisonDetails = {
  astronaut: { heading: 'A gesture, before and after.', note: 'The same first two astronaut shots. The finished panel adds local in-between frames; the original drawings are unchanged.' },
  cat: { heading: 'One cat. Two treatments.', note: 'The same walk, jump and curl-up takes. The finished panel adds compositing, framing cleanup and selective interpolation.' },
  dog: { heading: 'Follow the ball. And the paws.', note: 'The same four selected dog takes. The finished panel adds local interpolation. Watch the contact points and prop consistency.' }
};
document.querySelectorAll('[data-compare]').forEach(button => button.addEventListener('click', () => {
  const name = button.dataset.compare;
  comparison.pause();
  comparison.poster = `assets/showcase/${name}-poster.png`;
  comparison.src = `assets/showcase/${name}-comparison.mp4`;
  comparison.setAttribute('aria-label', `${name} native versus locally finished comparison`);
  comparison.load();
  document.getElementById('comparison-heading').textContent = comparisonDetails[name].heading;
  document.getElementById('comparison-note').textContent = comparisonDetails[name].note;
  document.getElementById('frame-link').href = `assets/showcase/${name}-frames.png`;
  document.querySelectorAll('[data-compare]').forEach(item => {
    const active = item === button;
    item.classList.toggle('selected', active);
    item.setAttribute('aria-pressed', String(active));
  });
}));
const commands = {
  unix: 'git clone https://github.com/antropos17/chatgpt-gif-cinema.git\ncd chatgpt-gif-cinema\npython -m venv .venv\nsource .venv/bin/activate\npython -m pip install .\npython -m gif_cinema render examples/film.json --execute --max-api-calls 0 --out output/my-first-film',
  windows: 'git clone https://github.com/antropos17/chatgpt-gif-cinema.git\ncd chatgpt-gif-cinema\npython -m venv .venv\n.\\.venv\\Scripts\\python.exe -m pip install .\n.\\.venv\\Scripts\\python.exe -m gif_cinema render examples/film.json --execute --max-api-calls 0 --out output/my-first-film'
};
document.querySelectorAll('[data-platform]').forEach(button => button.addEventListener('click', () => {
  document.getElementById('demo-command').textContent = commands[button.dataset.platform];
  document.getElementById('copy-status').textContent = '';
  document.getElementById('copy-command').textContent = 'Copy';
  document.querySelectorAll('[data-platform]').forEach(item => {
    item.classList.toggle('selected', item === button);
    item.setAttribute('aria-pressed', String(item === button));
  });
}));
document.getElementById('copy-command').addEventListener('click', async () => {
  const status = document.getElementById('copy-status');
  try {
    await navigator.clipboard.writeText(document.getElementById('demo-command').textContent);
    status.textContent = 'Commands copied.';
    document.getElementById('copy-command').textContent = 'Copied';
  } catch {
    status.textContent = 'Select the commands above to copy them. Clipboard access is unavailable here.';
  }
});
