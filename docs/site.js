'use strict';
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let motionPaused = reduceMotion.matches;
const loops = [...document.querySelectorAll('[data-loop]')];
const toggle = document.getElementById('motion-toggle');
function setMotion(paused) {
  motionPaused = paused;
  document.body.classList.toggle('motion-paused', paused);
  toggle.setAttribute('aria-pressed', String(paused));
  toggle.innerHTML = paused ? '<span class="play-icon" aria-hidden="true"></span> Play motion' : '<span class="pause-icon" aria-hidden="true"></span> Pause motion';
  loops.forEach(video => { if (paused || document.hidden) video.pause(); else if (video.dataset.visible === 'true') video.play().catch(() => {}); });
}
const loopObserver = new IntersectionObserver(entries => entries.forEach(({target, isIntersecting}) => {
  target.dataset.visible = String(isIntersecting);
  if (isIntersecting && !motionPaused && !document.hidden) target.play().catch(() => {}); else target.pause();
}), { threshold: .15 });
loops.forEach(video => loopObserver.observe(video));
setMotion(motionPaused);
toggle.addEventListener('click', () => setMotion(!motionPaused));
reduceMotion.addEventListener('change', event => setMotion(event.matches));
document.addEventListener('visibilitychange', () => setMotion(motionPaused));
const films = {
  astronaut: { title: 'A Signal in Space', type: 'PUBLIC CLI FILM / 7.68 SECONDS / SILENT', src: 'assets/showcase/astronaut-native-film.mp4', note: 'Three existing 2.56-second GIF shots assembled by the public CLI. 512 × 512, 25 fps export; 16 source drawings per shot held for 160 ms. No interpolation or new provider calls.' },
  cat: { title: 'The Art of Doing Nothing', type: 'LOCALLY FINISHED FILM / 57.2 SECONDS / SILENT', src: 'assets/showcase/cat-film.mp4', note: 'The existing full cat film: short generated takes assembled and finished locally. Compositing, framing cleanup and selective interpolation use additional tools outside the public CLI. This is not a single 57-second model generation.' },
  dog: { title: 'Eyes on the Ball', type: 'NATIVE / FINISHED COMPARISON / 10.24 SECONDS / SILENT', src: 'assets/showcase/dog-comparison.mp4', note: 'Four existing takes, shown side by side. Left: original native GIF timing. Right: local interpolation. The 50 fps comparison is not native 50 fps generation, and additional frames do not repair prop or pose errors.' }
};
const dialog = document.getElementById('film-dialog');
const dialogVideo = document.getElementById('dialog-video');
let lastTrigger = null;
document.querySelectorAll('[data-film]').forEach(button => button.addEventListener('click', () => {
  const film = films[button.dataset.film];
  lastTrigger = button;
  document.getElementById('dialog-title').textContent = film.title;
  document.getElementById('dialog-type').textContent = film.type;
  document.getElementById('dialog-note').textContent = film.note;
  document.getElementById('dialog-source').href = film.src;
  dialogVideo.src = film.src;
  loops.forEach(video => video.pause());
  document.getElementById('story-video').pause();
  document.getElementById('compare-video').pause();
  dialog.showModal();
  document.body.classList.add('dialog-open');
  dialogVideo.play().catch(() => {});
}));
document.getElementById('close-dialog').addEventListener('click', () => dialog.close());
dialog.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } });
dialog.addEventListener('close', () => { dialogVideo.pause(); dialogVideo.removeAttribute('src'); dialogVideo.load(); document.body.classList.remove('dialog-open'); setMotion(motionPaused); lastTrigger?.focus(); });
const story = document.getElementById('story-video');
const beats = [...document.querySelectorAll('[data-seek]')];
beats.forEach(button => button.addEventListener('click', () => { story.currentTime = Number(button.dataset.seek); story.play().catch(() => {}); }));
story.addEventListener('timeupdate', () => beats.forEach((button, index) => { const active = Math.min(2, Math.floor(story.currentTime / 2.56)) === index; button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active)); }));
const comparison = document.getElementById('compare-video');
const comparisonNotes = { cat: "The cat's finished panel adds compositing, framing cleanup and selective interpolation.", astronaut: "The astronaut's finished panel adds local in-between frames to the same first two source shots.", dog: "The dog's finished panel adds local interpolation to the same four selected source takes." };
document.querySelectorAll('[data-compare]').forEach(button => button.addEventListener('click', () => { const name = button.dataset.compare; comparison.pause(); comparison.poster = `assets/showcase/${name}-poster.png`; comparison.src = `assets/showcase/${name}-comparison.mp4`; comparison.setAttribute('aria-label', `${name} native versus locally finished comparison`); comparison.load(); document.getElementById('comparison-note').textContent = comparisonNotes[name]; document.getElementById('frame-link').href = `assets/showcase/${name}-frames.png`; document.querySelectorAll('[data-compare]').forEach(item => { const active = item === button; item.classList.toggle('selected', active); item.setAttribute('aria-pressed', String(active)); }); }));
document.getElementById('copy-command').addEventListener('click', async () => { const status = document.getElementById('copy-status'); try { await navigator.clipboard.writeText(document.getElementById('demo-command').textContent); status.textContent = 'Commands copied. Activate your virtual environment before installing.'; document.getElementById('copy-command').textContent = 'Copied ✓'; } catch { status.textContent = 'Copy is unavailable here. Select the commands above to copy them.'; } });
