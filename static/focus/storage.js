const KEY = 'bonsai_focus_data';

function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) return JSON.parse(raw);
  } catch (_) {}
  return { trees: [], stats: { totalSessions: 0, totalMinutes: 0, streak: 0, lastSession: null, history: [] } };
}

function save(data) {
  localStorage.setItem(KEY, JSON.stringify(data));
}

export function getData() { return load(); }

export function saveTree(tree) {
  const d = load();
  const idx = d.trees.findIndex(t => t.id === tree.id);
  if (idx >= 0) d.trees[idx] = tree;
  else d.trees.unshift(tree);
  save(d);
}

export function deleteTree(id) {
  const d = load();
  d.trees = d.trees.filter(t => t.id !== id);
  save(d);
}

export function recordSession(minutes) {
  const d = load();
  const today = new Date().toISOString().slice(0, 10);
  d.stats.totalSessions = (d.stats.totalSessions || 0) + 1;
  d.stats.totalMinutes = (d.stats.totalMinutes || 0) + minutes;
  d.stats.history = d.stats.history || [];
  const todayEntry = d.stats.history.find(h => h.date === today);
  if (todayEntry) todayEntry.minutes = (todayEntry.minutes || 0) + minutes;
  else d.stats.history.push({ date: today, minutes });

  const last = d.stats.lastSession;
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (last === yesterday || last === today) {
    if (last !== today) d.stats.streak = (d.stats.streak || 0) + 1;
  } else {
    d.stats.streak = 1;
  }
  d.stats.lastSession = today;
  save(d);
  return d.stats;
}

export function getStats() { return load().stats; }
export function getTrees() { return load().trees; }

export function getTree(id) { return load().trees.find(t => t.id === id) || null; }

export function updateTreeMods(id, mods) {
  const d = load();
  const t = d.trees.find(t => t.id === id);
  if (!t) return;
  Object.assign(t, mods);
  save(d);
}
