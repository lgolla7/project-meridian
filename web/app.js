const messages = document.querySelector("#messages");
const examples = document.querySelector("#examples");
const form = document.querySelector("#composer");
const input = document.querySelector("#input");
const sheet = document.querySelector("#sheet");
const diagram = document.querySelector("#diagram");
const pageBar = document.querySelector("#page-bar");
const pageLabel = document.querySelector("#page-label");
const pdfLink = document.querySelector("#pdf-link");
let pageState = { id: null, page: 1, pages: 1 };
const emptyStage = document.querySelector("#empty-stage");
const viewerTitle = document.querySelector("#viewer-title");
const viewerBadges = document.querySelector("#viewer-badges");
const switches = document.querySelector("#switches");
const caveat = document.querySelector("#recon-caveat");
const parts = document.querySelector("#parts");
const reviewList = document.querySelector("#review-list");
const pendingCount = document.querySelector("#pending-count");
const graphCanvas = document.querySelector("#graph");
const graphDetail = document.querySelector("#graph-detail");
const viewer = window.MeridianViewer.create(document.querySelector("#view3d"));

let graphData = null;
let graphNodes = [];

function showView(name) {
  document.querySelector("#explore").hidden = name !== "explore";
  document.querySelector("#review").hidden = name !== "review";
  document.querySelector("#graph-view").hidden = name !== "graph";
  document.querySelectorAll("nav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
  if (name === "review") loadReview();
  if (name === "graph") ensureGraph();
}

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

function addBubble(role, node) {
  const wrap = document.createElement("article");
  wrap.className = `bubble ${role}`;
  wrap.append(node);
  messages.append(wrap);
  messages.scrollTop = messages.scrollHeight;
}

function renderAnswer(data) {
  const wrap = document.createElement("div");
  data.blocks.forEach((block) => {
    if (block.type === "fact") {
      const row = document.createElement("div");
      row.className = "fact";
      const label = document.createElement("b");
      label.textContent = block.label;
      const value = document.createElement("span");
      value.textContent = block.value;
      row.append(label, value);
      wrap.append(row);
      return;
    }
    const p = document.createElement(block.type === "warn" ? "div" : "p");
    if (block.type === "warn") p.className = "warn";
    p.textContent = block.text;
    wrap.append(p);
  });
  if (data.model) {
    const via = document.createElement("p");
    via.className = "via";
    via.textContent = `Written by ${data.model} from the records retrieved for this question.`;
    wrap.append(via);
  }
  if (data.citations && data.citations.length) {
    const cites = document.createElement("div");
    cites.className = "citations";
    data.citations.forEach((cite) => {
      const row = document.createElement("div");
      row.className = "cite";
      const title = document.createElement("strong");
      title.textContent = `${cite.source} ${cite.id} · ${cite.label}`;
      row.append(title);
      if (cite.snippet) {
        row.append(document.createElement("br"), document.createTextNode(cite.snippet));
      }
      cites.append(row);
    });
    wrap.append(cites);
  }
  addBubble("assistant", wrap);
  if (data.visuals && data.visuals.length) {
    switches.replaceChildren();
    data.visuals.forEach((visual, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = visual.has_3d ? `${visual.id} + 3D` : visual.id;
      button.addEventListener("click", () => openVisual(visual));
      switches.append(button);
      if (index === 0) openVisual(visual);
    });
    const solid = data.visuals.find((visual) => visual.has_3d);
    if (solid) loadReconstruction(solid.id);
    else clearReconstruction();
  }
}

async function ask(message) {
  const user = document.createElement("p");
  user.textContent = message;
  addBubble("user", user);
  input.value = "";
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    const err = document.createElement("p");
    err.textContent = "The request failed.";
    addBubble("assistant", err);
    return;
  }
  renderAnswer(await response.json());
  refreshPending();
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (message) ask(message);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

function showDrawingPage() {
  sheet.hidden = false;
  diagram.hidden = true;
  sheet.alt = `${pageState.id} page ${pageState.page}`;
  sheet.src = `/api/drawings/${pageState.id}/pages/${pageState.page}`;
  pageLabel.textContent = `Page ${pageState.page} of ${pageState.pages}`;
  pageBar.hidden = false;
  pdfLink.href = `/api/drawings/${pageState.id}/file`;
}

async function openVisual(visual) {
  emptyStage.hidden = true;
  viewerTitle.textContent = `${visual.id} · ${visual.title}`;
  viewerBadges.replaceChildren();
  const badge = document.createElement("span");
  badge.className = `badge ${visual.distribution || "clean"}`;
  badge.textContent = visual.distribution === "degraded-only" ? "Degraded scan" : visual.kind === "diagram" ? "Diagram" : "Clean sheet";
  viewerBadges.append(badge);
  if (visual.kind === "diagram") {
    sheet.hidden = true;
    pageBar.hidden = true;
    diagram.hidden = false;
    diagram.src = `/api/diagrams/${visual.id}/file`;
    diagram.alt = visual.title;
    return;
  }
  const meta = await (await fetch(`/api/drawings/${visual.id}`)).json();
  pageState = { id: visual.id, page: 1, pages: meta.pages };
  showDrawingPage();
}

document.querySelector("#prev-page").addEventListener("click", () => {
  if (pageState.page > 1) {
    pageState.page -= 1;
    showDrawingPage();
  }
});
document.querySelector("#next-page").addEventListener("click", () => {
  if (pageState.page < pageState.pages) {
    pageState.page += 1;
    showDrawingPage();
  }
});

async function loadReconstruction(id) {
  const response = await fetch(`/api/reconstructions/${id}`);
  if (!response.ok) return;
  const spec = await response.json();
  viewer.setSpec(spec);
  caveat.textContent = `${spec.label}. ${spec.caveat}`;
}

function clearReconstruction() {
  viewer.clear();
  caveat.textContent = "This part has no reconstruction. The three solids are D-005, D-007, and D-010.";
}

async function loadExamples() {
  const data = await (await fetch("/api/examples")).json();
  data.questions.forEach((question) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.textContent = question;
    button.addEventListener("click", () => ask(question));
    examples.append(button);
  });
}

async function loadParts() {
  const data = await (await fetch("/api/catalog")).json();
  const groups = {};
  data.drawings.forEach((drawing) => {
    (groups[drawing.subsystem] ||= []).push(drawing);
  });
  Object.keys(groups).forEach((name) => {
    const heading = document.createElement("h3");
    heading.textContent = name;
    parts.append(heading);
    groups[name].forEach((drawing) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "part-row";
      const flag = drawing.readable ? "" : " · no text";
      const solid = drawing.has_3d ? " · 3D" : "";
      button.innerHTML = `${drawing.id} ${drawing.title}<br><small>${drawing.distribution}${flag}${solid}</small>`;
      button.addEventListener("click", () => {
        openVisual({
          kind: "drawing",
          id: drawing.id,
          title: drawing.title,
          distribution: drawing.distribution,
          has_3d: drawing.has_3d,
        });
        if (drawing.has_3d) loadReconstruction(drawing.id);
        else clearReconstruction();
      });
      parts.append(button);
    });
  });
}

async function refreshPending() {
  const data = await (await fetch("/api/corrections")).json();
  const pending = data.corrections.filter((row) => row.status === "pending").length;
  pendingCount.textContent = pending ? `(${pending})` : "";
  return data.corrections;
}

async function loadReview() {
  const rows = await refreshPending();
  reviewList.replaceChildren();
  if (!rows.length) {
    reviewList.innerHTML = "<p>No proposals yet. In chat: Propose a correction: Window Frame material should be 6061 aluminium</p>";
    return;
  }
  rows.forEach((row) => {
    const card = document.createElement("article");
    card.className = "card";
    const title = document.createElement("h3");
    title.textContent = `#${row.id} ${row.status} · ${row.target_label} · ${row.field}`;
    const body = document.createElement("p");
    body.textContent = `Original: ${row.original_value || "(blank)"}. Proposed: ${row.proposed_value}.`;
    const summary = document.createElement("p");
    summary.textContent = row.check_summary;
    const detail = document.createElement("pre");
    detail.textContent = row.check_detail;
    card.append(title, body, summary, detail);
    if (row.reviewer_note) {
      const note = document.createElement("p");
      note.textContent = `Reviewer note: ${row.reviewer_note}`;
      card.append(note);
    }
    if (row.status === "pending") {
      const actions = document.createElement("div");
      actions.className = "actions";
      const note = document.createElement("input");
      note.placeholder = "Reviewer note";
      const accept = document.createElement("button");
      accept.className = "primary";
      accept.type = "button";
      accept.textContent = "Accept";
      const reject = document.createElement("button");
      reject.className = "danger";
      reject.type = "button";
      reject.textContent = "Reject";
      accept.addEventListener("click", () => review(row.id, "accept", note.value));
      reject.addEventListener("click", () => review(row.id, "reject", note.value));
      actions.append(note, accept, reject);
      card.append(actions);
    }
    reviewList.append(card);
  });
}

async function review(id, action, note) {
  await fetch(`/api/corrections/${id}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note }),
  });
  await loadReview();
}

function layoutGraph(data) {
  const width = graphCanvas.clientWidth || 800;
  const height = graphCanvas.clientHeight || 600;
  const nodes = data.nodes.map((node, index) => ({
    ...node,
    x: width / 2 + Math.cos(index) * (80 + (index % 12) * 18),
    y: height / 2 + Math.sin(index * 1.7) * (80 + (index % 9) * 16),
  }));
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
  for (let step = 0; step < 80; step += 1) {
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        let dx = nodes[j].x - nodes[i].x || 0.01;
        let dy = nodes[j].y - nodes[i].y || 0.01;
        const dist = Math.max(12, Math.hypot(dx, dy));
        const force = 220 / dist;
        dx /= dist; dy /= dist;
        nodes[i].x -= dx * force;
        nodes[i].y -= dy * force;
        nodes[j].x += dx * force;
        nodes[j].y += dy * force;
      }
    }
    data.edges.forEach((edge) => {
      const a = byId[edge.source];
      const b = byId[edge.target];
      if (!a || !b) return;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      a.x += dx * 0.01;
      a.y += dy * 0.01;
      b.x -= dx * 0.01;
      b.y -= dy * 0.01;
    });
    nodes.forEach((node) => {
      node.x += (width / 2 - node.x) * 0.02;
      node.y += (height / 2 - node.y) * 0.02;
    });
  }
  return nodes;
}

function drawGraph() {
  const ctx = graphCanvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const width = graphCanvas.clientWidth;
  const height = graphCanvas.clientHeight;
  graphCanvas.width = width * dpr;
  graphCanvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const byId = Object.fromEntries(graphNodes.map((node) => [node.id, node]));
  ctx.strokeStyle = "#cfc6b8";
  graphData.edges.forEach((edge) => {
    const a = byId[edge.source];
    const b = byId[edge.target];
    if (!a || !b) return;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  });
  graphNodes.forEach((node) => {
    ctx.beginPath();
    ctx.fillStyle = node.kind === "drawing" ? "#0f4c5c" : node.kind === "material" ? "#9a3412" : node.kind === "subsystem" ? "#1d1a16" : "#8a8175";
    ctx.arc(node.x, node.y, node.kind === "bom" ? 3.5 : 6, 0, Math.PI * 2);
    ctx.fill();
    if (node.kind === "subsystem" || node.kind === "family") {
      ctx.fillStyle = "#1d1a16";
      ctx.font = "12px sans-serif";
      ctx.fillText(node.label, node.x + 8, node.y - 8);
    }
  });
}

async function ensureGraph() {
  if (!graphData) graphData = await (await fetch("/api/graph")).json();
  graphNodes = layoutGraph(graphData);
  drawGraph();
  graphDetail.innerHTML = `<p>${graphData.note}</p><p>${graphData.nodes.length} nodes.</p>`;
}

graphCanvas.addEventListener("click", (event) => {
  if (!graphNodes.length) return;
  const rect = graphCanvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  let nearest = null;
  let best = 18;
  graphNodes.forEach((node) => {
    const dist = Math.hypot(node.x - x, node.y - y);
    if (dist < best) {
      best = dist;
      nearest = node;
    }
  });
  if (!nearest) return;
  graphDetail.innerHTML = `<p><strong>${nearest.label}</strong></p><p>${nearest.kind}</p>`;
  if (nearest.kind === "drawing") {
    const button = document.createElement("button");
    button.className = "primary";
    button.type = "button";
    button.textContent = "Open drawing";
    button.addEventListener("click", () => {
      showView("explore");
      ask(`Tell me about ${nearest.id}`);
    });
    graphDetail.append(button);
  } else if (nearest.kind === "bom") {
    const button = document.createElement("button");
    button.className = "primary";
    button.type = "button";
    button.textContent = "Ask about this part";
    button.addEventListener("click", () => {
      showView("explore");
      ask(`Tell me about ${nearest.label}`);
    });
    graphDetail.append(button);
  }
});

window.addEventListener("resize", () => {
  if (!document.querySelector("#graph-view").hidden && graphData) {
    graphNodes = layoutGraph(graphData);
    drawGraph();
  }
});

async function loadModelStatus() {
  const status = document.querySelector("#model-status");
  try {
    const health = await fetch("/api/health").then((response) => response.json());
    status.textContent = health.model
      ? `Answers written by ${health.model}`
      : "Set OPENAI_API_KEY to write answers";
  } catch {
    status.textContent = "Model status unavailable";
  }
}

loadExamples();
loadParts();
refreshPending();
loadModelStatus();
