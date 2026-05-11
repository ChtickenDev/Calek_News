/* darts.js — Physara Darts Counter — vanilla JS */

// ─────────────────────────────────────────────────────────────────
// CHECKOUT TABLE (scores 2-170, standard routes)
// ─────────────────────────────────────────────────────────────────
const CHECKOUTS = {
  170:"T20 T20 Bull",169:"T20 T19 Bull",168:"T20 T20 D20",167:"T20 T19 D20",
  166:"T20 T18 D20",165:"T20 T19 D18",164:"T20 T18 D18",163:"T20 T19 D16",
  162:"T20 T18 D16",161:"T20 T17 D20",160:"T20 T20 D10",158:"T20 T20 D9",
  157:"T20 T19 D10",156:"T20 T20 D8",155:"T20 T19 D9",154:"T20 T18 D10",
  153:"T20 T19 D8",152:"T20 T20 D4",151:"T20 T17 D10",150:"T20 T18 D8",
  149:"T20 T19 D4",148:"T20 T20 D2",147:"T20 T17 D8",146:"T20 T18 D4",
  145:"T20 T15 D10",144:"T20 T20 D0",143:"T20 T17 D4",142:"T20 T14 D10",
  141:"T20 T15 D8",140:"T20 T20 D0",139:"T20 T13 D10",138:"T20 T14 D8",
  137:"T20 T15 D4",136:"T20 T20 D0",135:"T20 T13 D8",134:"T20 T14 D4",
  133:"T20 T13 D4",132:"T20 Bull D1",131:"T20 T13 D2",130:"T20 T18 D2",
  129:"T19 T16 D6",128:"T18 T14 D10",127:"T20 T17 D0",126:"T19 Bull D1",
  125:"Bull Bull D5",124:"T20 T16 D0",123:"T19 T16 D0",122:"T18 T18 D0",
  121:"T20 T11 D4",120:"T20 S20 D20",119:"T19 T12 D4",118:"T20 S18 D20",
  117:"T20 S17 D20",116:"T20 S16 D20",115:"T20 S15 D20",114:"T20 S14 D20",
  113:"T20 S13 D20",112:"T20 S12 D20",111:"T20 S11 D20",110:"T20 S10 D20",
  109:"T20 S9 D20",108:"T20 S8 D20",107:"T20 S7 D20",106:"T20 S6 D20",
  105:"T20 S5 D20",104:"T20 S4 D20",103:"T20 S3 D20",102:"T20 S2 D20",
  101:"T20 S1 D20",100:"T20 D20",99:"T19 S10 D16",98:"T20 D19",
  97:"T19 D20",96:"T20 D18",95:"T19 D19",94:"T18 D20",93:"T19 D18",
  92:"T20 D16",91:"T17 D20",90:"T18 D18",89:"T19 D16",88:"T20 D14",
  87:"T17 D18",86:"T18 D16",85:"T15 D20",84:"T20 D12",83:"T17 D16",
  82:"T14 D20",81:"T19 D12",80:"T20 D10",79:"T13 D20",78:"T18 D12",
  77:"T19 D10",76:"T20 D8",75:"T13 D18",74:"T14 D16",73:"T19 D8",
  72:"T16 D12",71:"T13 D16",70:"T10 D20",69:"T15 D12",68:"T20 D4",
  67:"T17 D8",66:"T10 D18",65:"T15 D10",64:"T16 D8",63:"T13 D12",
  62:"T10 D16",61:"T15 D8",60:"S20 D20",59:"S19 D20",58:"S18 D20",
  57:"S17 D20",56:"S16 D20",55:"S15 D20",54:"S14 D20",53:"S13 D20",
  52:"S12 D20",51:"S11 D20",50:"Bull",49:"S17 D16",48:"S16 D16",
  47:"S15 D16",46:"S6 D20",45:"S13 D16",44:"S12 D16",43:"S3 D20",
  42:"S10 D16",41:"S9 D16",40:"D20",39:"S7 D16",38:"D19",
  37:"S5 D16",36:"D18",35:"S3 D16",34:"D17",33:"S1 D16",
  32:"D16",31:"S15 D8",30:"D15",29:"S13 D8",28:"D14",
  27:"S11 D8",26:"D13",25:"S17 D4",24:"D12",23:"S7 D8",
  22:"D11",21:"S5 D8",20:"D10",19:"S3 D8",18:"D9",
  17:"S1 D8",16:"D8",15:"S7 D4",14:"D7",13:"S5 D4",
  12:"D6",11:"S3 D4",10:"D5",9:"S1 D4",8:"D4",
  7:"S3 D2",6:"D3",5:"S1 D2",4:"D2",3:"S1 D1",2:"D1"
};

// ─────────────────────────────────────────────────────────────────
// ADJACENCY MAP (for robot scatter)
// weight: how often the robot hits neighbors instead of target
// ─────────────────────────────────────────────────────────────────
const NEIGHBORS = {
  20:[1,5],19:[7,3],18:[4,1],17:[3,2],16:[8,7],
  15:[10,2],14:[9,11],13:[6,4],12:[9,5],11:[14,8],
  10:[15,6],9:[12,14],8:[16,11],7:[19,16],6:[10,13],
  5:[20,12],4:[13,18],3:[17,19],2:[15,17],1:[18,20],
  25:[20,3,19,7,16,8,11,14,9,12,5,15,10,6,13,4,18,1,17,2],
  50:[25]
};

// ─────────────────────────────────────────────────────────────────
// GAME STATE
// ─────────────────────────────────────────────────────────────────
let G = null; // active game object

function defaultGame() {
  return {
    mode: '501',
    doubleIn: false,
    finishRule: 'double',
    players: [],
    current: 0,
    history: [],   // [{playerIdx, darts:[{val,mult,score}], scoresBefore, clockTargetBefore}]
    started: false,
    startTime: null,
    winner: null,
    // Cricket state
    cricket: null,
    // ATC state
    clockTargets: null,
    // mid-game darts in current turn
    turnDarts: [],
    doubleInAchieved: [],
  };
}

// ─────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────
function isCricket()  { return G.mode === 'cricket'; }
function isATC()      { return G.mode === 'atc'; }
function isNumeric()  { return !isCricket() && !isATC(); }
function startScore() { return parseInt(G.mode) || 501; }

function playerScore(idx) { return G.players[idx].score; }

function dartLabel(val, mult) {
  if (val === 0)  return 'Miss';
  if (val === 50) return 'Bull';
  if (val === 25) return mult === 2 ? 'Bull' : 'Bull/2';
  const prefix = mult === 3 ? 'T' : mult === 2 ? 'D' : 'S';
  return `${prefix}${val}`;
}
function dartPoints(val, mult) {
  if (val === 0) return 0;
  if (val === 50) return 50;
  return val * mult;
}

// ─────────────────────────────────────────────────────────────────
// ROBOT AI
// ─────────────────────────────────────────────────────────────────
function robotThrow(player) {
  const diff = player.difficulty; // 20-120, avg pts/turn
  // accuracy: at diff=120, ~90% hit rate; at diff=20, ~20%
  const accuracy = 0.15 + (diff - 20) / 100 * 0.78;

  const target = robotTarget(player);
  const hit = Math.random() < accuracy;

  if (hit) {
    return { val: target.val, mult: target.mult };
  }
  // miss → neighbor or random
  const neighbors = NEIGHBORS[target.val] || [target.val];
  const scattered = neighbors[Math.floor(Math.random() * neighbors.length)];
  const scMult = Math.random() < 0.7 ? 1 : (Math.random() < 0.5 ? 2 : 3);
  const safeMult = (scattered === 25 || scattered === 50) ? Math.min(scMult, 2) : scMult;
  return { val: scattered, mult: safeMult };
}

function robotTarget(player) {
  if (isCricket()) {
    const open = [20,19,18,17,16,15,25].find(n => {
      const marks = G.cricket[player.idx][n] || 0;
      return marks < 3;
    });
    return open ? { val: open, mult: 3 } : { val: 20, mult: 3 };
  }
  if (isATC()) {
    const t = G.clockTargets[player.idx];
    return { val: t <= 20 ? t : 25, mult: 1 };
  }
  const sc = player.score;
  if (sc <= 170 && CHECKOUTS[sc]) {
    const parts = CHECKOUTS[sc].split(' ');
    const p = parts[0];
    const mult = p[0] === 'T' ? 3 : p[0] === 'D' ? 2 : 1;
    const valStr = p.replace(/^[TDS]/, '');
    const val = valStr === 'Bull' ? 50 : parseInt(valStr);
    return { val, mult };
  }
  // aim for 20, treble
  return { val: 20, mult: 3 };
}

// ─────────────────────────────────────────────────────────────────
// SETUP UI
// ─────────────────────────────────────────────────────────────────
const MODES = [
  {id:'101',label:'101'},{id:'201',label:'201'},{id:'301',label:'301'},
  {id:'401',label:'401'},{id:'501',label:'501'},{id:'601',label:'601'},
  {id:'701',label:'701'},{id:'801',label:'801'},{id:'901',label:'901'},
  {id:'1001',label:'1001'},{id:'cricket',label:'Cricket'},
  {id:'atc',label:'Clock'},{id:'custom',label:'Custom'},
];
const FINISH_RULES = [
  {id:'double',label:'Double Out'},
  {id:'single',label:'Single Out'},
  {id:'bull',label:'Bull Out'},
];

let setupMode = '501';
let setupFinish = 'double';
let setupDoubleIn = false;
let setupPlayers = [];
let localPlayers = []; // from server
let loggedInUser = null;

function initSetup() {
  renderModeButtons();
  renderFinishButtons();
  renderDoubleIn();
  renderPlayerList();
  updateAddMeButton();
  loadLocalPlayersFromServer();
  loadResumeGame();
}

function renderModeButtons() {
  const el = document.getElementById('mode-pills');
  el.innerHTML = '';
  MODES.forEach(m => {
    const b = document.createElement('button');
    b.className = 'pill-btn' + (m.id === setupMode ? ' active' : '');
    b.textContent = m.label;
    b.onclick = () => {
      setupMode = m.id;
      if (m.id === 'custom') showCustomInput();
      else hideCustomInput();
      renderModeButtons();
      renderFinishArea();
    };
    el.appendChild(b);
  });
}

function showCustomInput() {
  document.getElementById('custom-score-wrap').style.display = 'flex';
}
function hideCustomInput() {
  document.getElementById('custom-score-wrap').style.display = 'none';
}

function renderFinishArea() {
  const wrap = document.getElementById('finish-wrap');
  wrap.style.display = (isModeNumeric() || setupMode === 'custom') ? 'flex' : 'none';
}
function isModeNumeric() {
  return !['cricket','atc'].includes(setupMode);
}

function renderFinishButtons() {
  const el = document.getElementById('finish-pills');
  el.innerHTML = '';
  FINISH_RULES.forEach(r => {
    const b = document.createElement('button');
    b.className = 'pill-btn' + (r.id === setupFinish ? ' active' : '');
    b.textContent = r.label;
    b.onclick = () => { setupFinish = r.id; renderFinishButtons(); };
    el.appendChild(b);
  });
  renderFinishArea();
}

function renderDoubleIn() {
  const chk = document.getElementById('double-in-chk');
  if (chk) chk.checked = setupDoubleIn;
}

function renderPlayerList() {
  const el = document.getElementById('player-list');
  el.innerHTML = '';
  setupPlayers.forEach((p, i) => {
    const row = document.createElement('div');
    row.className = 'player-row';
    let avClass = 'player-avatar';
    let avText = p.name ? p.name[0].toUpperCase() : '?';
    if (p.type === 'robot') { avClass += ' robot-av'; avText = '🤖'; }
    else if (p.type === 'guest') { avClass += ' guest-av'; }

    let extra = '';
    if (p.type === 'robot') {
      extra = `<div style="display:flex;align-items:center;gap:6px;margin-top:4px">
        <span style="font-size:11px;color:var(--text-muted)">Niv.</span>
        <input type="range" min="20" max="120" value="${p.difficulty||60}" class="diff-slider" style="flex:1"
          oninput="setupPlayers[${i}].difficulty=parseInt(this.value);this.nextElementSibling.textContent=this.value"
        ><span style="font-size:12px;min-width:28px">${p.difficulty||60}</span>
      </div>`;
    }
    row.innerHTML = `
      <div class="${avClass}">${avText}</div>
      <div class="player-info">
        <div class="player-name">${p.name}</div>
        <div class="player-type">${p.type === 'user' ? 'Compte Physara' : p.type === 'robot' ? 'Robot' : 'Invité local'}</div>
        ${extra}
      </div>
      <button class="player-remove" onclick="removePlayer(${i})">×</button>
    `;
    el.appendChild(row);
  });
}

function removePlayer(i) {
  setupPlayers.splice(i, 1);
  renderPlayerList();
  updateAddMeButton();
  renderLocalPlayersList();
}

function showAddPlayerType(type) {
  const panel = document.getElementById(`add-form-${type}`);
  const isVisible = panel.classList.contains('visible');
  document.querySelectorAll('.add-player-form').forEach(f => f.classList.remove('visible'));
  if (!isVisible) {
    panel.classList.add('visible');
    if (type === 'guest') renderLocalPlayersList();
  }
}

function renderLocalPlayersList() {
  const el = document.getElementById('local-players-list');
  if (!el) return;
  if (localPlayers.length === 0) {
    el.innerHTML = '<div style="font-size:13px;color:var(--text-muted);padding:4px 0 8px">Aucun joueur enregistre — creez-en un ci-dessous.</div>';
    return;
  }
  el.innerHTML = '';
  localPlayers.forEach(lp => {
    const alreadyIn = setupPlayers.some(p => p.localPlayerId === lp.id);
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;background:var(--felt-light);margin-bottom:6px;border:1px solid var(--border)';
    const av = document.createElement('div');
    av.className = 'player-avatar guest-av';
    av.style.cssText = 'width:28px;height:28px;font-size:12px;flex-shrink:0';
    av.textContent = lp.name[0].toUpperCase();
    const name = document.createElement('span');
    name.style.cssText = 'flex:1;font-size:14px';
    name.textContent = lp.name;
    const btn = document.createElement('button');
    btn.style.cssText = 'width:28px;height:28px;border-radius:50%;border:none;font-size:16px;line-height:1;cursor:pointer;flex-shrink:0;display:flex;align-items:center;justify-content:center';
    if (alreadyIn) {
      btn.textContent = '✓';
      btn.style.background = 'var(--green)';
      btn.style.color = '#fff';
      btn.disabled = true;
    } else {
      btn.textContent = '+';
      btn.style.background = 'var(--amber)';
      btn.style.color = '#111';
      btn.onclick = () => addGuestFromList(lp.id);
    }
    row.append(av, name, btn);
    el.appendChild(row);
  });
}

function addPhysaraPlayer() {
  if (!loggedInUser) return;
  if (setupPlayers.find(p => p.type === 'user')) return;
  if (setupPlayers.length >= 8) return;
  setupPlayers.push({ type: 'user', name: loggedInUser.name, userId: loggedInUser.id });
  renderPlayerList();
  updateAddMeButton();
}

function updateAddMeButton() {
  const btn = document.getElementById('btn-add-me');
  if (!btn) return;
  const alreadyIn = setupPlayers.some(p => p.type === 'user');
  btn.disabled = alreadyIn;
  btn.style.opacity = alreadyIn ? '0.4' : '1';
}

function addGuestFromList(localPlayerId) {
  if (setupPlayers.length >= 8) return;
  const lp = localPlayers.find(l => l.id === localPlayerId);
  if (!lp) return;
  if (setupPlayers.some(p => p.localPlayerId === localPlayerId)) return;
  setupPlayers.push({ type: 'guest', name: lp.name, localPlayerId: lp.id });
  renderPlayerList();
  renderLocalPlayersList();
}

function addNewGuestPlayer() {
  const nameInput = document.getElementById('guest-name-input');
  const name = nameInput ? nameInput.value.trim() : '';
  if (!name) return;
  if (setupPlayers.length >= 8) return;

  // check if already exists in localPlayers
  const existing = localPlayers.find(l => l.name.toLowerCase() === name.toLowerCase());
  if (existing) {
    addGuestFromList(existing.id);
    if (nameInput) nameInput.value = '';
    return;
  }

  // create + add immediately (optimistic)
  const tempId = 'tmp_' + Date.now();
  setupPlayers.push({ type: 'guest', name, localPlayerId: null, _tempId: tempId });
  renderPlayerList();
  if (nameInput) nameInput.value = '';

  saveNewLocalPlayer(name, tempId);
}

function addRobotPlayer() {
  if (setupPlayers.length >= 8) return;
  const n = setupPlayers.filter(p => p.type === 'robot').length + 1;
  setupPlayers.push({ type: 'robot', name: `Robot ${n}`, difficulty: 60 });
  renderPlayerList();
  document.getElementById('add-form-robot').classList.remove('visible');
}

function saveNewLocalPlayer(name, tempId) {
  fetch('/darts/local_players', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  })
  .then(r => r.json())
  .then(d => {
    if (d.id) {
      if (!localPlayers.find(l => l.id === d.id)) {
        localPlayers.push({ id: d.id, name: d.name });
      }
      // patch tempId in setupPlayers
      if (tempId) {
        const p = setupPlayers.find(x => x._tempId === tempId);
        if (p) { p.localPlayerId = d.id; delete p._tempId; }
      }
    }
  }).catch(() => {});
}

function loadLocalPlayersFromServer() {
  fetch('/darts/local_players')
    .then(r => r.json())
    .then(d => { localPlayers = d.players || []; })
    .catch(() => {});
}

function loadResumeGame() {
  fetch('/darts/resume')
    .then(r => r.json())
    .then(d => {
      if (d.state) showResumeBanner(d.state);
    }).catch(() => {});
}

function showResumeBanner(state) {
  const banner = document.getElementById('resume-banner');
  if (!banner) return;
  const info = banner.querySelector('.resume-banner-info');
  if (info) info.innerHTML = `<div class="resume-banner-title">Partie en cours</div>
    <div>${state.mode.toUpperCase()} · ${state.players.map(p=>p.name).join(', ')}</div>`;
  banner.style.display = 'flex';
  banner.querySelector('.resume-btn').onclick = () => resumeGame(state);
}

function resumeGame(state) {
  G = state;
  G.startTime = G.startTime || Date.now();
  G.turnDarts = G.turnDarts || [];
  showPage('game-page');
  renderGame();
}

function startGame() {
  if (setupPlayers.length < 1) {
    alert('Ajoutez au moins un joueur.');
    return;
  }
  let mode = setupMode;
  if (mode === 'custom') {
    const v = parseInt(document.getElementById('custom-score-val').value);
    if (!v || v < 2) { alert('Score invalide.'); return; }
    mode = String(v);
  }

  G = defaultGame();
  G.mode = mode;
  G.doubleIn = mode === 'cricket' || mode === 'atc' ? false : setupDoubleIn;
  G.finishRule = setupFinish;
  G.started = true;
  G.startTime = Date.now();

  G.players = setupPlayers.map((p, i) => ({
    ...p,
    idx: i,
    score: isNumericMode(mode) ? (parseInt(mode) || 501) : 0,
    legs: 0,
    gamesWon: 0,
    dartsThrown: 0,
    turnScores: [],
    bestTurn: 0,
    count180: 0,
    count140: 0,
    count100: 0,
    count60: 0,
    hitMap: {},
    totalDartScore: 0,
    checkouts: [],
    doubles: 0, triples: 0, singles: 0, misses: 0,
    doubleInDone: false,
  }));

  G.doubleInAchieved = G.players.map(p => !G.doubleIn || p.type === 'robot');

  if (isCricket()) initCricket();
  if (isATC()) initATC();

  showPage('game-page');
  renderGame();
  if (G.players[G.current].type === 'robot') scheduleRobotTurn();
}

function isNumericMode(mode) {
  return !['cricket','atc'].includes(mode);
}

// ─────────────────────────────────────────────────────────────────
// CRICKET
// ─────────────────────────────────────────────────────────────────
const CRICKET_NUMS = [20,19,18,17,16,15,25];

function initCricket() {
  G.cricket = {};
  G.players.forEach(p => {
    G.cricket[p.idx] = {};
    CRICKET_NUMS.forEach(n => G.cricket[p.idx][n] = 0);
  });
  G.cricketPoints = G.players.map(() => 0);
}

function cricketRegisterHit(playerIdx, val, mult) {
  if (!CRICKET_NUMS.includes(val)) return 0;
  const prev = G.cricket[playerIdx][val] || 0;
  const newMarks = Math.min(prev + mult, 3);
  const overflow = (prev + mult) - 3;
  G.cricket[playerIdx][val] = newMarks;

  let points = 0;
  if (overflow > 0) {
    const allClosed = G.players.every(p =>
      p.idx === playerIdx || (G.cricket[p.idx][val] || 0) >= 3
    );
    if (!allClosed) {
      points = val * overflow;
      G.cricketPoints[playerIdx] = (G.cricketPoints[playerIdx] || 0) + points;
    }
  }
  return points;
}

function cricketMarksStr(playerIdx, num) {
  const m = G.cricket[playerIdx][num] || 0;
  if (m === 0) return '';
  if (m === 1) return '/';
  if (m === 2) return 'X';
  return '⦻';
}

function checkCricketWin() {
  return G.players.find(p => {
    const allClosed = CRICKET_NUMS.every(n => (G.cricket[p.idx][n] || 0) >= 3);
    if (!allClosed) return false;
    const myPts = G.cricketPoints[p.idx] || 0;
    return G.players.every(q => (G.cricketPoints[q.idx] || 0) <= myPts);
  });
}

// ─────────────────────────────────────────────────────────────────
// AROUND THE CLOCK
// ─────────────────────────────────────────────────────────────────
function initATC() {
  G.clockTargets = G.players.map(() => 1);
}

function atcRegisterHit(playerIdx, val) {
  const target = G.clockTargets[playerIdx];
  if (target <= 20 && val === target) {
    G.clockTargets[playerIdx]++;
    return true;
  }
  if (target === 21 && (val === 25 || val === 50)) {
    G.clockTargets[playerIdx]++;
    return true;
  }
  return false;
}

function checkATCWin() {
  return G.players.find(p => G.clockTargets[p.idx] > 21);
}

// ─────────────────────────────────────────────────────────────────
// GAME RENDERING
// ─────────────────────────────────────────────────────────────────
function renderGame() {
  renderScoreboard();
  renderTurnHeader();
  renderDartSlots();
  renderCheckoutHint();
  renderActionBar();
  if (isCricket()) renderCricketBoard();
  if (isATC()) renderATCBoard();
}

function renderScoreboard() {
  if (isCricket()) { document.getElementById('numeric-scoreboard').style.display = 'none'; return; }
  if (isATC()) { document.getElementById('numeric-scoreboard').style.display = 'none'; return; }
  document.getElementById('numeric-scoreboard').style.display = 'flex';
  document.getElementById('cricket-scoreboard').style.display = 'none';
  document.getElementById('atc-scoreboard').style.display = 'none';

  const el = document.getElementById('numeric-scoreboard');
  el.innerHTML = '';
  G.players.forEach((p, i) => {
    const cell = document.createElement('div');
    cell.className = 'score-cell' + (i === G.current ? ' active' : '');
    cell.innerHTML = `
      <div class="s-name">${p.name}</div>
      <div class="s-score" id="score-val-${i}">${p.score}</div>
      <div class="s-legs">${p.legs||0} legs</div>
    `;
    el.appendChild(cell);
  });
}

function renderCricketBoard() {
  document.getElementById('numeric-scoreboard').style.display = 'none';
  document.getElementById('atc-scoreboard').style.display = 'none';
  const el = document.getElementById('cricket-scoreboard');
  el.style.display = 'block';
  const numPlayers = G.players.length;
  let thead = `<tr><th>N°</th>`;
  G.players.forEach(p => { thead += `<th>${p.name}</th>`; });
  thead += `<th>Pts</th></tr>`;

  let tbody = '';
  CRICKET_NUMS.forEach(n => {
    tbody += `<tr>`;
    tbody += `<td class="cricket-num">${n === 25 ? 'Bull' : n}</td>`;
    G.players.forEach(p => {
      const active = p.idx === G.current ? ' active-player' : '';
      tbody += `<td class="cricket-cell${active}"><span class="cricket-mark">${cricketMarksStr(p.idx, n)}</span></td>`;
    });
    tbody += `</tr>`;
  });

  // points row
  tbody += `<tr><td style="color:var(--amber);font-weight:600">Pts</td>`;
  G.players.forEach(p => {
    tbody += `<td style="color:var(--amber);font-family:'Oswald',sans-serif;font-size:16px">${G.cricketPoints[p.idx]||0}</td>`;
  });
  tbody += `</tr>`;

  el.innerHTML = `<table class="cricket-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

function renderATCBoard() {
  document.getElementById('numeric-scoreboard').style.display = 'none';
  document.getElementById('cricket-scoreboard').style.display = 'none';
  const el = document.getElementById('atc-scoreboard');
  el.style.display = 'block';

  let rows = G.players.map(p => {
    const tgt = G.clockTargets[p.idx];
    const label = tgt > 21 ? 'Fini!' : tgt === 21 ? 'Bull' : String(tgt);
    const active = p.idx === G.current;
    return `<tr class="${active ? 'active-player' : ''}">
      <td style="text-align:left">${p.name}</td>
      <td style="color:var(--amber);font-family:'Oswald',sans-serif;font-size:18px">${label}</td>
      <td>${tgt - 1} / 21</td>
    </tr>`;
  }).join('');

  el.innerHTML = `<table class="atc-table">
    <thead><tr><th style="text-align:left">Joueur</th><th>Cible</th><th>Progression</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderTurnHeader() {
  const p = G.players[G.current];
  document.getElementById('turn-player').textContent = p.name;
  const total = G.turnDarts.reduce((s, d) => s + dartPoints(d.val, d.mult), 0);
  document.getElementById('turn-total').textContent = total > 0 ? `+${total}` : '';
}

function renderDartSlots() {
  for (let i = 0; i < 3; i++) {
    const slot = document.getElementById(`dart-slot-${i}`);
    if (!slot) continue;
    const d = G.turnDarts[i];
    if (d) {
      slot.className = 'dart-slot filled' + (d.val === 0 ? ' miss' : '');
      slot.querySelector('.dart-val').textContent = dartLabel(d.val, d.mult);
      const pts = dartPoints(d.val, d.mult);
      slot.querySelector('.dart-pts').textContent = pts > 0 ? `+${pts}` : '';
    } else {
      slot.className = 'dart-slot';
      slot.querySelector('.dart-val').textContent = '—';
      slot.querySelector('.dart-pts').textContent = '';
    }
  }
}

function renderCheckoutHint() {
  const hint = document.getElementById('checkout-hint');
  if (!isNumeric() || !hint) return;
  const sc = G.players[G.current].score;
  if (sc <= 170 && sc >= 2 && CHECKOUTS[sc]) {
    hint.textContent = `Checkout: ${CHECKOUTS[sc]}`;
    hint.classList.add('visible');
  } else {
    hint.classList.remove('visible');
  }
}

function renderActionBar() {
  const btn = document.getElementById('validate-btn');
  if (!btn) return;
  const dartsIn = G.turnDarts.length;
  btn.disabled = dartsIn === 0;
  if (dartsIn === 3) {
    btn.textContent = 'Valider le tour';
    btn.style.background = 'var(--green)';
  } else if (dartsIn > 0) {
    btn.textContent = `Valider (${dartsIn} fléchette${dartsIn > 1 ? 's' : ''})`;
    btn.style.background = 'var(--teal)';
  }
}

// ─────────────────────────────────────────────────────────────────
// DART REGISTRATION
// ─────────────────────────────────────────────────────────────────
let selectedMult = 1;

function setMult(m) {
  selectedMult = m;
  document.querySelectorAll('.mult-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.mult) === m);
  });
}

function registerDart(val, mult) {
  if (G.turnDarts.length >= 3) return;
  if (val === 50) mult = 1;
  if (val === 25) mult = Math.min(mult, 2);
  // clamp triple: only for 1-20
  if (val < 1 || val > 20) mult = Math.min(mult, 2);

  G.turnDarts.push({ val, mult });
  renderDartSlots();
  renderTurnHeader();
  renderCheckoutHint();
  renderActionBar();

  if (G.turnDarts.length === 3) {
    // auto-validate after brief delay for UX
    setTimeout(() => {
      // show validate button highlighted — user taps to confirm
    }, 100);
  }
}

function undoDart() {
  if (G.turnDarts.length > 0) {
    G.turnDarts.pop();
    renderDartSlots();
    renderTurnHeader();
    renderCheckoutHint();
    renderActionBar();
    return;
  }
  // undo last committed turn
  if (G.history.length === 0) return;
  const last = G.history.pop();
  G.current = last.playerIdx;
  const p = G.players[G.current];

  if (isNumeric()) {
    p.score = last.scoresBefore[G.current];
  } else if (isCricket()) {
    G.cricket = JSON.parse(JSON.stringify(last.cricketBefore));
    G.cricketPoints = [...last.cricketPointsBefore];
  } else if (isATC()) {
    G.clockTargets = [...last.clockTargetsBefore];
  }

  // restore stats
  p.dartsThrown -= last.darts.length;
  last.darts.forEach(d => {
    const key = `${d.mult === 3 ? 't' : d.mult === 2 ? 'd' : 's'}${d.val}`;
    if (p.hitMap[key] > 0) p.hitMap[key]--;
  });

  // if robot turn: discard — will re-roll when its turn comes again
  G.turnDarts = [];
  renderGame();
}

function validateTurn() {
  if (G.turnDarts.length === 0) return;
  const p = G.players[G.current];
  const histEntry = {
    playerIdx: G.current,
    darts: [...G.turnDarts],
    scoresBefore: G.players.map(q => q.score),
    cricketBefore: isCricket() ? JSON.parse(JSON.stringify(G.cricket)) : null,
    cricketPointsBefore: isCricket() ? [...G.cricketPoints] : null,
    clockTargetsBefore: isATC() ? [...G.clockTargets] : null,
  };

  let turnPts = 0;
  let bust = false;

  G.turnDarts.forEach(d => {
    p.dartsThrown++;
    const key = `${d.mult === 3 ? 't' : d.mult === 2 ? 'd' : 's'}${d.val === 0 ? 'miss' : d.val}`;
    p.hitMap[key] = (p.hitMap[key] || 0) + 1;
    if (d.mult === 3) p.triples++;
    else if (d.mult === 2) p.doubles++;
    else if (d.val === 0) p.misses++;
    else p.singles++;
  });

  if (isNumeric()) {
    // Double In check
    if (G.doubleIn && !p.doubleInDone) {
      const firstDouble = G.turnDarts.find(d => d.mult === 2 && d.val > 0);
      if (!firstDouble) {
        // no double this turn → no score
        G.history.push(histEntry);
        advanceTurn();
        return;
      }
      p.doubleInDone = true;
      // only count from first double onwards
      const idx = G.turnDarts.indexOf(firstDouble);
      turnPts = G.turnDarts.slice(idx).reduce((s, d) => s + dartPoints(d.val, d.mult), 0);
    } else {
      turnPts = G.turnDarts.reduce((s, d) => s + dartPoints(d.val, d.mult), 0);
    }

    const newScore = p.score - turnPts;

    // Bust detection
    if (newScore < 0) { bust = true; }
    else if (newScore === 1 && G.finishRule === 'double') { bust = true; }
    else if (newScore === 0) {
      // check finish condition
      const lastDart = G.turnDarts[G.turnDarts.length - 1];
      const lastNonMiss = [...G.turnDarts].reverse().find(d => d.val > 0);
      if (G.finishRule === 'double') {
        if (!lastNonMiss || lastNonMiss.mult !== 2) bust = true;
      } else if (G.finishRule === 'bull') {
        if (!lastNonMiss || lastNonMiss.val !== 50) bust = true;
      }
    }

    if (bust) {
      flashBust();
      G.history.push(histEntry);
      G.turnDarts = [];
      renderGame();
      advanceTurn();
      return;
    }

    p.score = newScore;
    p.totalDartScore += turnPts;
    p.turnScores.push(turnPts);
    if (turnPts > p.bestTurn) p.bestTurn = turnPts;
    if (turnPts >= 180) p.count180++;
    else if (turnPts >= 140) p.count140++;
    else if (turnPts >= 100) p.count100++;
    else if (turnPts >= 60) p.count60++;

    // Checkout
    if (newScore === 0) {
      p.checkouts.push({ score: histEntry.scoresBefore[G.current], darts: p.dartsThrown });
      p.legs++;
      G.history.push(histEntry);
      G.turnDarts = [];
      updateScoreDisplay(G.current, p.score);
      setTimeout(() => endGame(p), 300);
      return;
    }

    updateScoreDisplay(G.current, p.score);
  } else if (isCricket()) {
    G.turnDarts.forEach(d => {
      if (d.val > 0) cricketRegisterHit(p.idx, d.val, d.mult);
    });
    turnPts = G.cricketPoints[p.idx];
    renderCricketBoard();
    const winner = checkCricketWin();
    if (winner) {
      G.history.push(histEntry);
      G.turnDarts = [];
      setTimeout(() => endGame(winner), 300);
      return;
    }
  } else if (isATC()) {
    G.turnDarts.forEach(d => {
      if (d.val > 0) atcRegisterHit(p.idx, d.val);
    });
    renderATCBoard();
    const winner = checkATCWin();
    if (winner) {
      G.history.push(histEntry);
      G.turnDarts = [];
      setTimeout(() => endGame(winner), 300);
      return;
    }
  }

  G.history.push(histEntry);
  G.turnDarts = [];
  advanceTurn();
}

function advanceTurn() {
  G.current = (G.current + 1) % G.players.length;
  renderGame();
  saveResume();
  if (G.players[G.current].type === 'robot') scheduleRobotTurn();
}

function updateScoreDisplay(idx, score) {
  const el = document.getElementById(`score-val-${idx}`);
  if (!el) return;
  el.textContent = score;
  el.classList.remove('score-updated');
  void el.offsetWidth;
  el.classList.add('score-updated');
}

function flashBust() {
  document.getElementById('game-page').classList.remove('bust-flash');
  void document.getElementById('game-page').offsetWidth;
  document.getElementById('game-page').classList.add('bust-flash');
}

// ─────────────────────────────────────────────────────────────────
// ROBOT TURN
// ─────────────────────────────────────────────────────────────────
function scheduleRobotTurn() {
  const p = G.players[G.current];
  if (!p || p.type !== 'robot') return;
  showRobotOverlay(p);

  const darts = [];
  let delay = 0;

  function throwNext() {
    if (darts.length >= 3 || G.winner) {
      setTimeout(() => {
        hideRobotOverlay();
        G.turnDarts = darts;
        validateTurn();
      }, 600);
      return;
    }
    const result = robotThrow(p);
    darts.push({ val: result.val, mult: result.mult });
    animateRobotDart(darts.length, dartLabel(result.val, result.mult));

    // stop early if checkout achieved (numeric)
    if (isNumeric()) {
      const pts = darts.reduce((s, d) => s + dartPoints(d.val, d.mult), 0);
      const remaining = p.score - pts;
      if (remaining === 0) {
        setTimeout(() => {
          hideRobotOverlay();
          G.turnDarts = darts;
          validateTurn();
        }, 700);
        return;
      }
    }
    setTimeout(throwNext, 700);
  }

  setTimeout(throwNext, 800);
}

function showRobotOverlay(p) {
  const ov = document.getElementById('robot-overlay');
  ov.querySelector('.robot-name').textContent = p.name;
  ov.querySelector('.robot-thinking').textContent = 'Calcul en cours...';
  [1,2,3].forEach(i => {
    const el = document.getElementById(`rpip-${i}`);
    if (el) { el.textContent = '—'; el.classList.remove('hit'); }
  });
  ov.classList.add('visible');
}

function hideRobotOverlay() {
  document.getElementById('robot-overlay').classList.remove('visible');
}

function animateRobotDart(n, label) {
  const el = document.getElementById(`rpip-${n}`);
  if (!el) return;
  el.textContent = label;
  el.classList.add('hit');
}

// ─────────────────────────────────────────────────────────────────
// END GAME
// ─────────────────────────────────────────────────────────────────
function endGame(winner) {
  G.winner = winner;
  G.endTime = Date.now();
  const duration = Math.round((G.endTime - G.startTime) / 1000);

  showPage('winner-page');
  renderWinner(winner, duration);
  launchConfetti();
  saveGame(winner, duration);
  clearResume();
}

function renderWinner(winner, duration) {
  document.getElementById('winner-name').textContent = winner.name;
  const mins = Math.floor(duration / 60);
  const secs = duration % 60;
  document.getElementById('winner-duration').textContent = `${mins}:${String(secs).padStart(2,'0')}`;
  document.getElementById('winner-darts').textContent = winner.dartsThrown || '—';
  const avg = winner.turnScores && winner.turnScores.length
    ? Math.round(winner.turnScores.reduce((a,b)=>a+b,0)/winner.turnScores.length)
    : '—';
  document.getElementById('winner-avg').textContent = avg;
  document.getElementById('winner-best').textContent = winner.bestTurn || '—';
  document.getElementById('winner-180').textContent = winner.count180 || 0;
}

// ─────────────────────────────────────────────────────────────────
// CONFETTI
// ─────────────────────────────────────────────────────────────────
function launchConfetti() {
  const canvas = document.getElementById('confetti-canvas');
  const ctx = canvas.getContext('2d');
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;

  const particles = Array.from({ length: 120 }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * -canvas.height,
    w: 8 + Math.random() * 8,
    h: 4 + Math.random() * 6,
    color: ['#f59e0b','#14b8a6','#f5f0e8','#22c55e','#ef4444'][Math.floor(Math.random()*5)],
    vy: 2 + Math.random() * 4,
    vx: (Math.random() - 0.5) * 3,
    angle: Math.random() * Math.PI * 2,
    av: (Math.random() - 0.5) * 0.2,
  }));

  let frame;
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    particles.forEach(p => {
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.angle);
      ctx.fillStyle = p.color;
      ctx.fillRect(-p.w/2, -p.h/2, p.w, p.h);
      ctx.restore();
      p.x += p.vx; p.y += p.vy; p.angle += p.av;
    });
    const alive = particles.some(p => p.y < canvas.height);
    if (alive) frame = requestAnimationFrame(draw);
    else ctx.clearRect(0, 0, canvas.width, canvas.height);
  }
  draw();
  setTimeout(() => { cancelAnimationFrame(frame); ctx.clearRect(0,0,canvas.width,canvas.height); }, 5000);
}

// ─────────────────────────────────────────────────────────────────
// SAVE / RESUME
// ─────────────────────────────────────────────────────────────────
function saveResume() {
  const payload = {
    mode: G.mode, doubleIn: G.doubleIn, finishRule: G.finishRule,
    players: G.players, current: G.current, history: G.history,
    cricket: G.cricket, cricketPoints: G.cricketPoints,
    clockTargets: G.clockTargets, startTime: G.startTime,
    turnDarts: G.turnDarts, doubleInAchieved: G.doubleInAchieved,
  };
  fetch('/darts/save_resume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state: payload })
  }).catch(() => {
    // fallback to localStorage for non-logged-in
    try { localStorage.setItem('darts_resume', JSON.stringify(payload)); } catch(e) {}
  });
}

function clearResume() {
  fetch('/darts/save_resume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ state: null })
  }).catch(() => {
    try { localStorage.removeItem('darts_resume'); } catch(e) {}
  });
}

function saveGame(winner, duration) {
  const payload = {
    mode: G.mode,
    duration,
    players: G.players.map(p => ({
      name: p.name,
      type: p.type,
      userId: p.userId || null,
      localPlayerId: p.localPlayerId || null,
      games_played: 1,
      games_won: p.idx === winner.idx ? 1 : 0,
      avg_score_per_turn: p.turnScores && p.turnScores.length
        ? p.turnScores.reduce((a,b)=>a+b,0)/p.turnScores.length : 0,
      best_turn: p.bestTurn || 0,
      count_180: p.count180 || 0,
      count_140: p.count140 || 0,
      count_100: p.count100 || 0,
      count_60: p.count60 || 0,
      max_checkout: p.checkouts.length ? Math.max(...p.checkouts.map(c=>c.score)) : 0,
      min_darts_to_finish: p.checkouts.length ? Math.min(...p.checkouts.map(c=>c.darts)) : 0,
      pct_single: p.dartsThrown ? p.singles/p.dartsThrown : 0,
      pct_double: p.dartsThrown ? p.doubles/p.dartsThrown : 0,
      pct_triple: p.dartsThrown ? p.triples/p.dartsThrown : 0,
      pct_miss: p.dartsThrown ? p.misses/p.dartsThrown : 0,
      hit_map: p.hitMap,
    })),
  };
  fetch('/darts/save_game', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }).catch(() => {});
}

// ─────────────────────────────────────────────────────────────────
// SVG DARTBOARD
// ─────────────────────────────────────────────────────────────────
const SEGMENT_ORDER = [20,1,18,4,13,6,10,15,2,17,3,19,7,16,8,11,14,9,12,5];

function buildDartboard() {
  const svg = document.getElementById('dartboard-svg');
  if (!svg) return;
  const cx = 200, cy = 200, R = 196;

  // radii (outer to inner): double wire, treble wire, small bull, bullseye
  const rOuter = R;         // outer edge
  const rDouble = R;        // double ring outer
  const rDoubleI = R*0.86;  // double ring inner
  const rTreble = R*0.567;  // treble ring outer
  const rTrebleI = R*0.472; // treble ring inner
  const rSmall = R*0.121;   // 25 ring
  const rBull = R*0.060;    // bullseye

  const n = 20;
  const sliceAngle = (2 * Math.PI) / n;

  function polarToXY(r, angle) {
    return [cx + r * Math.sin(angle), cy - r * Math.cos(angle)];
  }

  function segPath(r1, r2, startAngle, endAngle) {
    const [x1,y1] = polarToXY(r1, startAngle);
    const [x2,y2] = polarToXY(r2, startAngle);
    const [x3,y3] = polarToXY(r2, endAngle);
    const [x4,y4] = polarToXY(r1, endAngle);
    const laf = 0;
    return `M ${x1} ${y1} A ${r1} ${r1} 0 ${laf} 1 ${x4} ${y4}
            L ${x3} ${y3} A ${r2} ${r2} 0 ${laf} 0 ${x2} ${y2} Z`;
  }

  let markup = '';

  // outer black ring
  markup += `<circle cx="${cx}" cy="${cy}" r="${R}" fill="#1a1a1a"/>`;

  SEGMENT_ORDER.forEach((num, i) => {
    const startAngle = -Math.PI/n + i * sliceAngle;
    const endAngle = startAngle + sliceAngle;
    const isEven = i % 2 === 0;
    const baseColor = isEven ? '#1a6b2a' : '#c41e1e'; // green or red for scoring ring
    const blackColor = isEven ? '#2a2a2a' : '#1a1a1a';

    // single outer (between double and treble outer)
    markup += `<path d="${segPath(rDoubleI, rTreble, startAngle, endAngle)}"
      fill="${blackColor}" stroke="#333" stroke-width="0.5"
      data-val="${num}" data-mult="1" class="board-seg"/>`;

    // treble ring
    markup += `<path d="${segPath(rTreble, rTrebleI, startAngle, endAngle)}"
      fill="${baseColor}" stroke="#444" stroke-width="0.5"
      data-val="${num}" data-mult="3" class="board-seg"/>`;

    // single inner (between treble inner and small bull)
    markup += `<path d="${segPath(rTrebleI, rSmall, startAngle, endAngle)}"
      fill="${blackColor}" stroke="#333" stroke-width="0.5"
      data-val="${num}" data-mult="1" class="board-seg"/>`;

    // double ring
    markup += `<path d="${segPath(rOuter, rDoubleI, startAngle, endAngle)}"
      fill="${baseColor}" stroke="#444" stroke-width="0.5"
      data-val="${num}" data-mult="2" class="board-seg"/>`;

    // number label
    const labelR = R * 0.945;
    const midAngle = startAngle + sliceAngle / 2;
    const [lx, ly] = polarToXY(labelR, midAngle);
    markup += `<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="middle"
      fill="#f5f0e8" font-family="Oswald,sans-serif" font-size="11" font-weight="600">${num}</text>`;
  });

  // 25 ring
  markup += `<circle cx="${cx}" cy="${cy}" r="${rSmall}"
    fill="#22863a" stroke="#444" stroke-width="1"
    data-val="25" data-mult="1" class="board-seg"/>`;
  // bullseye
  markup += `<circle cx="${cx}" cy="${cy}" r="${rBull}"
    fill="#dc2626" stroke="#444" stroke-width="1"
    data-val="50" data-mult="1" class="board-seg"/>`;

  svg.innerHTML = markup;

  // click handler
  svg.addEventListener('click', function(e) {
    const seg = e.target.closest('.board-seg');
    if (!seg) return;
    const val = parseInt(seg.dataset.val);
    const mult = parseInt(seg.dataset.mult);
    registerDart(val, mult);
    showHitMarker(e, svg);
  });
}

function showHitMarker(e, svg) {
  const rect = svg.getBoundingClientRect();
  const wrap = document.querySelector('.board-wrap');
  const wRect = wrap.getBoundingClientRect();
  const x = e.clientX - wRect.left;
  const y = e.clientY - wRect.top;

  const existing = wrap.querySelectorAll('.hit-marker');
  existing.forEach(m => m.remove());

  const marker = document.createElement('div');
  marker.className = 'hit-marker';
  marker.style.left = x + 'px';
  marker.style.top = y + 'px';
  wrap.appendChild(marker);
  setTimeout(() => marker.remove(), 700);
}

// ─────────────────────────────────────────────────────────────────
// STATS
// ─────────────────────────────────────────────────────────────────
let statsData = null;
let statsMode = 'all';

function loadStats() {
  fetch('/darts/stats')
    .then(r => r.json())
    .then(d => {
      statsData = d;
      renderStats();
    }).catch(() => {});
}

function renderStats() {
  if (!statsData) return;
  const sel = document.getElementById('stats-player-sel');
  if (!sel) return;

  // populate selector
  if (sel.options.length === 0) {
    statsData.players.forEach(p => {
      const o = document.createElement('option');
      o.value = p.id;
      o.textContent = p.name;
      sel.appendChild(o);
    });
  }

  const playerId = sel.value;
  const playerStats = statsData.stats.filter(s =>
    s.player_id == playerId && (statsMode === 'all' || s.mode === statsMode)
  );

  // aggregate
  const agg = playerStats.reduce((acc, s) => ({
    games: acc.games + (s.games_played||0),
    wins: acc.wins + (s.games_won||0),
    totalAvg: acc.totalAvg + (s.avg_score_per_turn||0),
    count: acc.count + 1,
    best: Math.max(acc.best, s.best_turn||0),
    count180: acc.count180 + (s.count_180||0),
    maxCheckout: Math.max(acc.maxCheckout, s.max_checkout||0),
  }), {games:0,wins:0,totalAvg:0,count:0,best:0,count180:0,maxCheckout:0});

  document.getElementById('stat-games').textContent = agg.games;
  document.getElementById('stat-winrate').textContent = agg.games ? Math.round(agg.wins/agg.games*100)+'%' : '—';
  document.getElementById('stat-avg').textContent = agg.count ? Math.round(agg.totalAvg/agg.count) : '—';
  document.getElementById('stat-best').textContent = agg.best || '—';
  document.getElementById('stat-180').textContent = agg.count180;
  document.getElementById('stat-checkout').textContent = agg.maxCheckout || '—';

  renderHitChart(playerStats);
}

function renderHitChart(stats) {
  const canvas = document.getElementById('hit-chart');
  if (!canvas) return;

  const hitMap = {};
  stats.forEach(s => {
    const m = s.hit_map || {};
    Object.entries(m).forEach(([k, v]) => {
      hitMap[k] = (hitMap[k] || 0) + v;
    });
  });

  const labels = Array.from({length:20},(_,i)=>`${i+1}`).concat(['25','Bull','Miss']);
  const singles = labels.map(l => l === 'Miss' ? (hitMap['smiss']||0) : hitMap[`s${l}`]||0);
  const doubles = labels.map(l => l === 'Miss' || l === 'Bull' ? 0 : hitMap[`d${l}`]||0);
  const trebles = labels.map(l => ['25','Bull','Miss'].includes(l) ? 0 : hitMap[`t${l}`]||0);

  if (window._hitChart) window._hitChart.destroy();
  window._hitChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Single', data: singles, backgroundColor: 'rgba(245,158,11,.7)' },
        { label: 'Double', data: doubles, backgroundColor: 'rgba(20,184,166,.7)' },
        { label: 'Triple', data: trebles, backgroundColor: 'rgba(34,197,94,.7)' },
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#f5f0e8', font: { family: 'Inter' } } } },
      scales: {
        x: { stacked: true, ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,.05)' } },
        y: { stacked: true, ticks: { color: '#9ca3af' }, grid: { color: 'rgba(255,255,255,.05)' } },
      }
    }
  });
}

// ─────────────────────────────────────────────────────────────────
// PAGE NAV
// ─────────────────────────────────────────────────────────────────
function showPage(id) {
  document.querySelectorAll('.darts-page').forEach(p => p.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function showInputMode(mode) {
  const kp = document.getElementById('keypad-input');
  const bd = document.getElementById('board-input');
  document.querySelectorAll('.mode-tab').forEach(t => t.classList.remove('active'));
  if (mode === 'keypad') {
    kp.style.display = 'flex';
    bd.style.display = 'none';
    document.querySelector('[data-mode="keypad"]').classList.add('active');
  } else {
    kp.style.display = 'none';
    bd.style.display = 'flex';
    document.querySelector('[data-mode="board"]').classList.add('active');
  }
}

// ─────────────────────────────────────────────────────────────────
// INIT
// ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function() {
  // Read logged-in user data injected by template
  const ud = document.getElementById('user-data');
  if (ud) {
    try { loggedInUser = JSON.parse(ud.textContent); } catch(e) {}
  }

  showPage('setup-page');
  initSetup();
  buildDartboard();

  // multiplier buttons
  document.querySelectorAll('.mult-btn').forEach(b => {
    b.addEventListener('click', () => setMult(parseInt(b.dataset.mult)));
  });
  setMult(1);

  // mode tabs
  document.querySelectorAll('.mode-tab').forEach(tab => {
    tab.addEventListener('click', () => showInputMode(tab.dataset.mode));
  });
  showInputMode('keypad');

  // double-in toggle
  const diChk = document.getElementById('double-in-chk');
  if (diChk) diChk.addEventListener('change', () => { setupDoubleIn = diChk.checked; });

  // stats player selector
  const statSel = document.getElementById('stats-player-sel');
  if (statSel) statSel.addEventListener('change', renderStats);

  // stats mode tabs
  document.querySelectorAll('.stats-mode-btn').forEach(b => {
    b.addEventListener('click', () => {
      statsMode = b.dataset.mode;
      document.querySelectorAll('.stats-mode-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderStats();
    });
  });
});
