// ─── Seeded PRNG (mulberry32) ────────────────────────────────────────────────
function mulberry32(seed) {
  return function() {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

// ─── Season detection ────────────────────────────────────────────────────────
export function getSeason() {
  const m = new Date().getMonth(); // 0-11
  if (m >= 2 && m <= 4) return 'spring';
  if (m >= 5 && m <= 7) return 'summer';
  if (m >= 8 && m <= 10) return 'autumn';
  return 'winter';
}

const SEASON_COLORS = {
  spring: {
    leaf: ['#7bc47f', '#a8d5a2', '#b5e8b0', '#c8f0c8'],
    flower: ['#f4b8c8', '#f9d4de', '#fce4ec'],
    trunk: '#7a5c42',
  },
  summer: {
    leaf: ['#3d7a47', '#4a8c5c', '#2d6638', '#5a9e6a'],
    trunk: '#6b4226',
  },
  autumn: {
    leaf: ['#d47a3a', '#c94f2c', '#e8a030', '#b84020', '#d4a040'],
    trunk: '#5c3820',
  },
  winter: {
    leaf: [],
    trunk: '#4a3020',
  },
};

// ─── Tree generation ─────────────────────────────────────────────────────────
export function generateTree(seed, style) {
  const rng = mulberry32(seed);
  const season = getSeason();
  const colors = SEASON_COLORS[season];

  // Base parameters vary by style
  const styleParams = {
    moyogi:     { trunkLean: (rng() - 0.5) * 0.3, windBias: 0,    straightness: 0.4 },
    shakan:     { trunkLean: 0.3 + rng() * 0.4,   windBias: 0,    straightness: 0.6 },
    fukinagashi:{ trunkLean: 0.2 + rng() * 0.2,   windBias: 0.6 + rng() * 0.3, straightness: 0.5 },
    chokkan:    { trunkLean: (rng() - 0.5) * 0.05, windBias: 0,   straightness: 0.9 },
  };
  const sp = styleParams[style] || styleParams.moyogi;

  const branches = [];
  let idCounter = 0;

  function addBranch(parent, x1, y1, x2, y2, cpx1, cpy1, cpx2, cpy2, depth, order) {
    branches.push({ id: idCounter++, parent, x1, y1, x2, y2, cpx1, cpy1, cpx2, cpy2, depth, order, pruned: false });
  }

  function grow(x, y, angle, length, depth, parentId, order) {
    if (depth > 7 || length < 4) return;

    // Bezier control points for organic curve
    const midLen = length * 0.5;
    const curve1 = (rng() - 0.5) * length * 0.4 * (1 - sp.straightness);
    const curve2 = (rng() - 0.5) * length * 0.4 * (1 - sp.straightness);

    const endX = x + Math.sin(angle) * length;
    const endY = y - Math.cos(angle) * length;

    const perp1X = -Math.cos(angle);
    const perp1Y = -Math.sin(angle);
    const cp1x = x + Math.sin(angle) * midLen * 0.5 + perp1X * curve1;
    const cp1y = y - Math.cos(angle) * midLen * 0.5 + perp1Y * curve1;
    const cp2x = x + Math.sin(angle) * midLen * 1.2 + perp1X * curve2;
    const cp2y = y - Math.cos(angle) * midLen * 1.2 + perp1Y * curve2;

    const myId = idCounter;
    addBranch(parentId, x, y, endX, endY, cp1x, cp1y, cp2x, cp2y, depth, order);

    const numChildren = depth < 2 ? 2 : (rng() < 0.7 ? 2 : 1);
    const baseAngleVariance = 0.3 + rng() * 0.4;

    for (let i = 0; i < numChildren; i++) {
      const side = i === 0 ? -1 : 1;
      let childAngle = angle + side * baseAngleVariance * (0.7 + rng() * 0.6);

      // Wind bias for fukinagashi
      if (sp.windBias > 0) {
        childAngle += sp.windBias * 0.3 * (depth + 1);
      }

      const childLength = length * (0.6 + rng() * 0.2);
      const childOrder = order * 10 + i;
      grow(endX, endY, childAngle, childLength, depth + 1, myId, childOrder);
    }
  }

  // Trunk: multiple segments with lean
  const trunkSegments = 4 + Math.floor(rng() * 3);
  const trunkLength = 80 + rng() * 40;
  const segLen = trunkLength / trunkSegments;
  let tx = 0, ty = 0;
  let trunkAngle = sp.trunkLean;
  let lastTrunkId = -1;

  for (let i = 0; i < trunkSegments; i++) {
    const bend = (rng() - 0.5) * 0.15 * (1 - sp.straightness);
    trunkAngle += bend;
    const endTX = tx + Math.sin(trunkAngle) * segLen;
    const endTY = ty - Math.cos(trunkAngle) * segLen;
    const cp1x = tx + Math.sin(trunkAngle) * segLen * 0.3 + (rng() - 0.5) * segLen * 0.1;
    const cp1y = ty - Math.cos(trunkAngle) * segLen * 0.3 + (rng() - 0.5) * segLen * 0.1;
    const cp2x = tx + Math.sin(trunkAngle) * segLen * 0.7 + (rng() - 0.5) * segLen * 0.1;
    const cp2y = ty - Math.cos(trunkAngle) * segLen * 0.7 + (rng() - 0.5) * segLen * 0.1;

    const myId = idCounter;
    addBranch(lastTrunkId, tx, ty, endTX, endTY, cp1x, cp1y, cp2x, cp2y, 0, i);
    lastTrunkId = myId;

    // Spawn side branches from trunk
    if (i >= 1 && i < trunkSegments - 1) {
      const sides = [-(0.4 + rng() * 0.3), (0.4 + rng() * 0.3)];
      const pick = rng() < 0.7 ? sides : sides.slice(0, 1);
      pick.forEach((sa, si) => {
        let ba = trunkAngle + sa;
        if (sp.windBias > 0 && sa > 0) ba += sp.windBias * 0.4;
        grow(tx, ty, ba, segLen * (0.7 + rng() * 0.3), 1, lastTrunkId, i * 100 + si);
      });
    }

    tx = endTX;
    ty = endTY;
  }

  // Top canopy
  grow(tx, ty, trunkAngle - 0.2, segLen * 0.8, 1, lastTrunkId, 900);
  grow(tx, ty, trunkAngle + 0.2, segLen * 0.8, 1, lastTrunkId, 901);
  grow(tx, ty, trunkAngle, segLen * 0.7, 1, lastTrunkId, 902);

  // Sort by order for consistent draw order
  branches.sort((a, b) => a.order - b.order);

  return { branches, season, colors, trunkColor: colors.trunk };
}

// ─── Compute branch widths ───────────────────────────────────────────────────
function getBranchWidth(branch, totalBranches) {
  const maxDepth = 7;
  const depthFactor = 1 - branch.depth / (maxDepth + 1);
  return Math.max(0.5, 12 * depthFactor * depthFactor);
}

// ─── Bezier interpolation ────────────────────────────────────────────────────
function bezierPoint(t, p0, p1, p2, p3) {
  const mt = 1 - t;
  return mt * mt * mt * p0 + 3 * mt * mt * t * p1 + 3 * mt * t * t * p2 + t * t * t * p3;
}

// ─── Leaf clusters ───────────────────────────────────────────────────────────
function drawLeaves(ctx, branch, progress, colors, season, rng) {
  if (season === 'winter') return;
  if (branch.depth < 3) return;

  const leafProgress = Math.max(0, (progress - 0.5) * 2); // appear in second half
  if (leafProgress <= 0) return;

  const leafColors = colors.leaf;
  if (!leafColors || leafColors.length === 0) return;

  const centerX = bezierPoint(0.7, branch.x1, branch.cpx1, branch.cpx2, branch.x2);
  const centerY = bezierPoint(0.7, branch.y1, branch.cpy1, branch.cpy2, branch.y2);

  const count = Math.floor(leafProgress * (4 + branch.depth));
  for (let i = 0; i < count; i++) {
    const angle = (i / count) * Math.PI * 2 + rng() * 0.5;
    const r = (8 + rng() * 12) * leafProgress;
    const lx = centerX + Math.cos(angle) * r;
    const ly = centerY + Math.sin(angle) * r * 0.7;
    const size = (3 + rng() * 4) * Math.min(1, leafProgress * 2);
    const color = leafColors[Math.floor(rng() * leafColors.length)];

    ctx.beginPath();
    ctx.ellipse(lx, ly, size, size * 0.7, angle, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.85 * leafProgress;
    ctx.fill();
    ctx.globalAlpha = 1;

    // Spring flowers
    if (season === 'spring' && colors.flower && rng() < 0.12) {
      const fc = colors.flower[Math.floor(rng() * colors.flower.length)];
      ctx.beginPath();
      ctx.arc(lx, ly, size * 0.7, 0, Math.PI * 2);
      ctx.fillStyle = fc;
      ctx.globalAlpha = 0.7 * leafProgress;
      ctx.fill();
      ctx.globalAlpha = 1;
    }
  }
}

// ─── Draw a single branch (partial for growth animation) ────────────────────
function drawBranch(ctx2d, branch, width, progress, trunkColor) {
  ctx2d.beginPath();
  ctx2d.moveTo(branch.x1, branch.y1);

  // Partial draw: sample along Bezier
  if (progress < 1) {
    const steps = 20;
    for (let s = 1; s <= Math.floor(steps * progress); s++) {
      const t = s / steps;
      const px = bezierPoint(t, branch.x1, branch.cpx1, branch.cpx2, branch.x2);
      const py = bezierPoint(t, branch.y1, branch.cpy1, branch.cpy2, branch.y2);
      ctx2d.lineTo(px, py);
    }
  } else {
    ctx2d.bezierCurveTo(branch.cpx1, branch.cpy1, branch.cpx2, branch.cpy2, branch.x2, branch.y2);
  }

  ctx2d.strokeStyle = trunkColor;
  ctx2d.lineWidth = width;
  ctx2d.lineCap = 'round';
  ctx2d.lineJoin = 'round';
  ctx2d.stroke();
}

// ─── Main render function ────────────────────────────────────────────────────
export function renderTree(canvas, treeData, growthProgress, prunedIds = [], ligatures = []) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth;
  const H = canvas.clientHeight;

  if (canvas.width !== W * dpr || canvas.height !== H * dpr) {
    canvas.width = W * dpr;
    canvas.height = H * dpr;
  }

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const { branches, season, colors, trunkColor } = treeData;
  const total = branches.length;
  if (total === 0) return;

  // Origin: bottom-center, with slight upward offset
  const originX = W / 2;
  const originY = H * 0.88;

  ctx.save();
  ctx.translate(originX, originY);

  // Distribute growth across branches in draw order
  const perBranch = 1 / total;
  const rng = mulberry32(42); // fixed seed for leaf placement consistency

  branches.forEach((branch, i) => {
    if (branch.pruned || prunedIds.includes(branch.id)) return;

    const branchStart = i * perBranch;
    const branchProgress = Math.max(0, Math.min(1, (growthProgress - branchStart) / (perBranch * 1.5)));
    if (branchProgress <= 0) return;

    const w = getBranchWidth(branch, total);
    drawBranch(ctx, branch, w, branchProgress, trunkColor);
    drawLeaves(ctx, branch, Math.min(growthProgress, branchProgress), colors, season, rng);
  });

  // Draw ligatures (copper wire)
  ligatures.forEach(lig => {
    const b = branches.find(br => br.id === lig.branchId);
    if (!b) return;
    ctx.save();
    ctx.strokeStyle = '#b87333';
    ctx.lineWidth = 1.5;
    ctx.globalAlpha = 0.7;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(b.x1, b.y1);
    ctx.bezierCurveTo(b.cpx1, b.cpy1, b.cpx2, b.cpy2, b.x2, b.y2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.restore();
  });

  ctx.restore();

  // Draw pot
  drawPot(ctx, originX, originY, W, treeData.potStyle || 'classic');
}

function drawPot(ctx, cx, y, W, style) {
  const potW = Math.min(W * 0.25, 90);
  const potH = potW * 0.45;
  const rimH = potH * 0.15;
  const rimExtra = potW * 0.06;

  const styles = {
    classic: { fill: '#8b5e3c', rim: '#a0703a', shadow: '#6b4226' },
    ceramic: { fill: '#c8b89a', rim: '#d4c4a8', shadow: '#b0a090' },
    dark:    { fill: '#3a3028', rim: '#4a3c32', shadow: '#2a2018' },
    blue:    { fill: '#4a6fa5', rim: '#6080b5', shadow: '#3a5a8a' },
  };
  const c = styles[style] || styles.classic;

  // Soil surface
  ctx.beginPath();
  ctx.ellipse(cx, y, potW * 0.46, potH * 0.12, 0, 0, Math.PI * 2);
  ctx.fillStyle = '#4a3020';
  ctx.fill();

  // Pot body (trapezoid)
  ctx.beginPath();
  ctx.moveTo(cx - potW * 0.42, y);
  ctx.lineTo(cx - potW * 0.48, y + potH);
  ctx.lineTo(cx + potW * 0.48, y + potH);
  ctx.lineTo(cx + potW * 0.42, y);
  ctx.closePath();
  ctx.fillStyle = c.fill;
  ctx.fill();

  // Pot rim
  ctx.beginPath();
  ctx.rect(cx - potW * 0.5 - rimExtra, y - rimH, (potW + rimExtra * 2) * 1.0 + potW * 0.0, rimH);
  ctx.fillStyle = c.rim;
  ctx.fill();

  // Highlight
  ctx.beginPath();
  ctx.moveTo(cx - potW * 0.3, y + 4);
  ctx.lineTo(cx - potW * 0.36, y + potH - 4);
  ctx.lineWidth = 3;
  ctx.strokeStyle = 'rgba(255,255,255,0.12)';
  ctx.stroke();
}

// ─── Hit testing for pruning ─────────────────────────────────────────────────
export function getBranchAtPoint(canvas, treeData, x, y) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const cx = (x - rect.left);
  const cy = (y - rect.top);
  const originX = canvas.clientWidth / 2;
  const originY = canvas.clientHeight * 0.88;

  const bx = cx - originX;
  const by = cy - originY;

  let closest = null, minDist = 18;
  treeData.branches.forEach(branch => {
    if (branch.pruned) return;
    // Sample along bezier
    for (let t = 0; t <= 1; t += 0.05) {
      const px = bezierPoint(t, branch.x1, branch.cpx1, branch.cpx2, branch.x2);
      const py = bezierPoint(t, branch.y1, branch.cpy1, branch.cpy2, branch.y2);
      const d = Math.hypot(px - bx, py - by);
      if (d < minDist) { minDist = d; closest = branch; }
    }
  });
  return closest;
}

// ─── Prune animation (fade-out cascade) ─────────────────────────────────────
export function getPrunedDescendants(treeData, branchId) {
  const result = [branchId];
  let frontier = [branchId];
  while (frontier.length > 0) {
    const next = [];
    treeData.branches.forEach(b => {
      if (frontier.includes(b.parent)) {
        result.push(b.id);
        next.push(b.id);
      }
    });
    frontier = next;
  }
  return result;
}
