import { generateTree, renderTree, getSeason, getBranchAtPoint, getPrunedDescendants } from './tree.js';
import { getData, saveTree, deleteTree, recordSession, getTrees, getTree, updateTreeMods } from './storage.js';
import { initAudio, playSessionEnd, playAbandon, playPrune, playLeafGrow, playBranchGrow } from './audio.js';

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
  screen: 'forest',
  session: null,      // { treeId, durationMs, startedAt, growth }
  activeTree: null,   // tree data object (in-memory)
  workshop: null,     // { treeId, prunedIds, ligatures }
  animFrame: null,
  pruneMode: false,
};

// ─── DOM ─────────────────────────────────────────────────────────────────────
const screens = {
  forest:   document.getElementById('screen-forest'),
  session:  document.getElementById('screen-session'),
  end:      document.getElementById('screen-end'),
  workshop: document.getElementById('screen-workshop'),
  stats:    document.getElementById('screen-stats'),
};
const canvases = {
  session:  document.getElementById('canvas-session'),
  end:      document.getElementById('canvas-end'),
  workshop: document.getElementById('canvas-workshop'),
};

// ─── Navigation ──────────────────────────────────────────────────────────────
function showScreen(name) {
  Object.values(screens).forEach(s => s.classList.remove('active'));
  screens[name].classList.add('active');
  state.screen = name;
}

// ─── Forest screen ───────────────────────────────────────────────────────────
function renderForest() {
  const trees = getTrees();
  const grid = document.getElementById('forest-grid');
  const empty = document.getElementById('forest-empty');

  if (trees.length === 0) {
    grid.innerHTML = '';
    empty.style.display = 'flex';
    return;
  }
  empty.style.display = 'none';

  grid.innerHTML = trees.map(t => {
    const date = new Date(t.createdAt).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
    const styleLabel = { moyogi: 'Moyogi', shakan: 'Shakan', fukinagashi: 'Fukinagashi', chokkan: 'Chokkan' }[t.style] || t.style;
    const grown = Math.round((t.growth || 0) * 100);
    return `
      <div class="tree-card" data-id="${t.id}">
        <canvas class="tree-thumb" data-seed="${t.seed}" data-style="${t.style}"
                data-growth="${t.growth || 1}" data-pruned='${JSON.stringify(t.prunedIds || [])}'></canvas>
        <div class="tree-card-info">
          <span class="tree-style">${styleLabel}</span>
          <span class="tree-date">${date}</span>
          <span class="tree-grown">${grown}%</span>
        </div>
        <div class="tree-card-actions">
          <button class="btn-workshop" data-id="${t.id}" title="Atelier">✂</button>
          <button class="btn-delete" data-id="${t.id}" title="Supprimer">🗑</button>
        </div>
      </div>`;
  }).join('');

  // Render thumbnails
  grid.querySelectorAll('.tree-thumb').forEach(c => {
    const td = generateTree(Number(c.dataset.seed), c.dataset.style);
    td.potStyle = getTree(c.closest('.tree-card').dataset.id)?.pot || 'classic';
    renderTree(c, td, Number(c.dataset.growth), JSON.parse(c.dataset.pruned));
  });

  grid.querySelectorAll('.btn-workshop').forEach(b =>
    b.addEventListener('click', e => { e.stopPropagation(); openWorkshop(b.dataset.id); }));
  grid.querySelectorAll('.btn-delete').forEach(b =>
    b.addEventListener('click', e => { e.stopPropagation(); confirmDelete(b.dataset.id); }));
  grid.querySelectorAll('.tree-card').forEach(c =>
    c.addEventListener('click', () => openWorkshop(c.dataset.id)));
}

function confirmDelete(id) {
  const t = getTree(id);
  if (!t) return;
  const ok = confirm('Supprimer cet arbre ? Cette action est irreversible.');
  if (ok) { deleteTree(id); renderForest(); }
}

// ─── Start session ────────────────────────────────────────────────────────────
function startSession(durationMin) {
  initAudio();
  const styles = ['moyogi', 'moyogi', 'moyogi', 'shakan', 'fukinagashi', 'chokkan'];
  const style = styles[Math.floor(Math.random() * styles.length)];
  const seed = Math.floor(Math.random() * 0xFFFFFF);
  const id = `tree_${Date.now()}_${seed}`;

  const treeRecord = {
    id, seed, style,
    growth: 0,
    createdAt: new Date().toISOString(),
    sessionDuration: durationMin,
    prunedIds: [],
    ligatures: [],
    pot: 'classic',
  };
  saveTree(treeRecord);

  state.session = {
    treeId: id,
    durationMs: durationMin * 60 * 1000,
    startedAt: Date.now(),
    growth: 0,
    lastGrowthSound: 0,
  };
  state.activeTree = generateTree(seed, style);
  state.activeTree.potStyle = 'classic';

  // Update session UI
  document.getElementById('session-duration-label').textContent = `${durationMin} min`;
  showScreen('session');
  startSessionLoop();
}

function startSessionLoop() {
  const timerEl = document.getElementById('session-timer');
  const waveEl  = document.getElementById('session-wave');

  function tick() {
    if (state.screen !== 'session') return;
    const elapsed = Date.now() - state.session.startedAt;
    const remaining = Math.max(0, state.session.durationMs - elapsed);
    const progress = Math.min(1, elapsed / state.session.durationMs);

    state.session.growth = progress;

    // Update timer
    const mins = Math.floor(remaining / 60000);
    const secs = Math.floor((remaining % 60000) / 1000);
    timerEl.textContent = `${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;

    // Pulse wave
    const pulse = 0.5 + 0.5 * Math.sin(Date.now() / 2000);
    waveEl.style.transform = `scaleX(${0.8 + pulse * 0.4})`;

    // Growth sounds
    const now = Date.now();
    if (now - state.session.lastGrowthSound > 8000 && progress > 0.05) {
      if (progress < 0.5) playBranchGrow();
      else playLeafGrow();
      state.session.lastGrowthSound = now;
    }

    renderTree(canvases.session, state.activeTree, progress, []);

    // Persist growth
    updateTreeMods(state.session.treeId, { growth: progress });

    if (remaining <= 0) {
      endSession(true);
      return;
    }
    state.animFrame = requestAnimationFrame(tick);
  }

  state.animFrame = requestAnimationFrame(tick);
}

function endSession(completed) {
  cancelAnimationFrame(state.animFrame);
  const elapsed = Date.now() - state.session.startedAt;
  const minutesCompleted = Math.floor(elapsed / 60000);
  const growth = completed ? 1 : Math.min(0.85, elapsed / state.session.durationMs);

  updateTreeMods(state.session.treeId, { growth, completed });

  if (completed) {
    playSessionEnd();
    recordSession(minutesCompleted || 1);
    showEndScreen(growth);
  } else {
    playAbandon();
    // Wither: mark as partial
    updateTreeMods(state.session.treeId, { withered: true });
    showScreen('forest');
    renderForest();
  }
}

function showEndScreen(growth) {
  showScreen('end');
  const t = getTree(state.session.treeId);
  renderTree(canvases.end, state.activeTree, growth, t?.prunedIds || []);
  const stats = getData().stats;
  document.getElementById('end-streak').textContent = stats.streak || 1;
  document.getElementById('end-total').textContent = stats.totalSessions || 1;
}

// ─── Workshop ────────────────────────────────────────────────────────────────
function openWorkshop(id) {
  const t = getTree(id);
  if (!t) return;

  state.workshop = {
    treeId: id,
    prunedIds: [...(t.prunedIds || [])],
    ligatures: [...(t.ligatures || [])],
    pot: t.pot || 'classic',
  };
  state.pruneMode = false;
  state.activeTree = generateTree(t.seed, t.style);
  state.activeTree.potStyle = state.workshop.pot;

  document.getElementById('workshop-style-label').textContent =
    { moyogi: 'Moyogi', shakan: 'Shakan', fukinagashi: 'Fukinagashi', chokkan: 'Chokkan' }[t.style] || t.style;

  // Pot buttons
  document.querySelectorAll('.pot-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.pot === state.workshop.pot);
  });
  document.getElementById('prune-mode-btn').classList.remove('active');

  showScreen('workshop');
  renderWorkshop();
}

function renderWorkshop() {
  renderTree(canvases.workshop, state.activeTree, 1, state.workshop.prunedIds, state.workshop.ligatures);
}

// ─── Stats ───────────────────────────────────────────────────────────────────
function renderStats() {
  const stats = getData().stats;
  document.getElementById('stats-sessions').textContent = stats.totalSessions || 0;
  document.getElementById('stats-minutes').textContent = stats.totalMinutes || 0;
  document.getElementById('stats-streak').textContent = stats.streak || 0;

  const cal = document.getElementById('stats-calendar');
  const history = stats.history || [];
  const histMap = {};
  history.forEach(h => { histMap[h.date] = h.minutes; });

  // Last 12 weeks (84 days)
  const days = [];
  const today = new Date();
  for (let i = 83; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }

  const maxMin = Math.max(...days.map(d => histMap[d] || 0), 1);
  cal.innerHTML = days.map(d => {
    const min = histMap[d] || 0;
    const intensity = min / maxMin;
    const level = intensity === 0 ? 0 : intensity < 0.3 ? 1 : intensity < 0.6 ? 2 : intensity < 0.9 ? 3 : 4;
    return `<div class="cal-day level-${level}" title="${d}: ${min} min"></div>`;
  }).join('');
}

// ─── Event wiring ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Service Worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/focus/sw.js', { scope: '/focus/' }).catch(() => {});
  }

  // Forest
  showScreen('forest');
  renderForest();

  document.getElementById('btn-new-session').addEventListener('click', () => {
    document.getElementById('modal-duration').classList.add('show');
  });

  document.getElementById('btn-stats').addEventListener('click', () => {
    renderStats();
    showScreen('stats');
  });

  document.querySelectorAll('.duration-btn').forEach(b => {
    b.addEventListener('click', () => {
      document.getElementById('modal-duration').classList.remove('show');
      startSession(Number(b.dataset.min));
    });
  });
  document.getElementById('modal-close').addEventListener('click', () => {
    document.getElementById('modal-duration').classList.remove('show');
  });

  // Session
  document.getElementById('btn-abandon').addEventListener('click', () => {
    if (confirm('Abandonner la session ? L\'arbre depérira.')) {
      endSession(false);
    }
  });

  // End screen
  document.getElementById('btn-goto-forest').addEventListener('click', () => {
    showScreen('forest');
    renderForest();
  });
  document.getElementById('btn-goto-workshop-end').addEventListener('click', () => {
    openWorkshop(state.session.treeId);
  });

  // Workshop
  document.getElementById('btn-workshop-back').addEventListener('click', () => {
    // Save mods
    updateTreeMods(state.workshop.treeId, {
      prunedIds: state.workshop.prunedIds,
      ligatures: state.workshop.ligatures,
      pot: state.workshop.pot,
    });
    showScreen('forest');
    renderForest();
  });

  document.getElementById('prune-mode-btn').addEventListener('click', () => {
    state.pruneMode = !state.pruneMode;
    document.getElementById('prune-mode-btn').classList.toggle('active', state.pruneMode);
    canvases.workshop.style.cursor = state.pruneMode ? 'crosshair' : 'default';
  });

  canvases.workshop.addEventListener('click', e => {
    if (!state.pruneMode || !state.activeTree) return;
    const branch = getBranchAtPoint(canvases.workshop, state.activeTree, e.clientX, e.clientY);
    if (!branch) return;
    const descendants = getPrunedDescendants(state.activeTree, branch.id);
    descendants.forEach(id => {
      if (!state.workshop.prunedIds.includes(id)) state.workshop.prunedIds.push(id);
    });
    playPrune();
    renderWorkshop();
  });

  document.querySelectorAll('.pot-btn').forEach(b => {
    b.addEventListener('click', () => {
      state.workshop.pot = b.dataset.pot;
      state.activeTree.potStyle = b.dataset.pot;
      document.querySelectorAll('.pot-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderWorkshop();
    });
  });

  // Stats back
  document.getElementById('btn-stats-back').addEventListener('click', () => {
    showScreen('forest');
    renderForest();
  });

  // Resize → re-render current canvas
  window.addEventListener('resize', () => {
    if (state.screen === 'workshop' && state.activeTree) renderWorkshop();
    if (state.screen === 'end' && state.activeTree) {
      const t = getTree(state.session?.treeId);
      renderTree(canvases.end, state.activeTree, t?.growth || 1, t?.prunedIds || []);
    }
  });
});
