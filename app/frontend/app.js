// Pod Bay frontend — chat + tool-trace + diagram gallery.
// Talks to the same-origin FastAPI backend (/api/*).

const messagesEl = document.getElementById("messages");
const traceEl = document.getElementById("trace");
const diagramsEl = document.getElementById("diagrams");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");

// Conversation history sent to the backend each turn (text only).
let history = [];
// Richer transcript for debugging export: each turn with tool calls + diagrams.
let transcript = [];
let vehicleLabel = "";
let currentVehicleId = null;

// Friendly labels for the tool-call trace.
const TOOL_LABELS = {
  search_manual: (i) => `searched the manual for “${i.query}”`,
  get_section: (i) => `opened section ${i.section_id}`,
  lookup_component: (i) => `looked up “${i.query}” in the wiring database`,
  get_diagram: (i) => `requested diagram ${i.figure_id}`,
};

// ---- Bootstrap: vehicle picker + diagram gallery ----
const vehicleSelect = document.getElementById("vehicle-select");

async function init() {
  try {
    const { default: def, vehicles } = await fetch("/api/vehicles").then((r) => r.json());
    vehicleSelect.innerHTML = "";
    for (const v of vehicles) {
      const opt = document.createElement("option");
      opt.value = v.id;
      opt.textContent = v.label;
      vehicleSelect.append(opt);
    }
    currentVehicleId = def || (vehicles[0] && vehicles[0].id);
    vehicleSelect.value = currentVehicleId;
    await loadVehicle(currentVehicleId);
  } catch (e) {
    vehicleSelect.innerHTML = `<option>(backend offline)</option>`;
  }
}

// Load a vehicle's label + diagram gallery (does not touch the conversation).
async function loadVehicle(id) {
  const v = await fetch(`/api/vehicle?vehicle_id=${encodeURIComponent(id)}`).then((r) => r.json());
  vehicleLabel = v.label;
  renderDiagrams(v.id, v.diagrams);
}

// Switching vehicle starts a fresh conversation — context doesn't carry over.
function resetConversation() {
  history = [];
  transcript = [];
  messagesEl.querySelectorAll(".msg:not(.intro)").forEach((m) => m.remove());
  traceEl.innerHTML = `<p class="placeholder">Tool calls the assistant makes will show up here —
    which manual sections it opened, searches it ran, and components it looked up.</p>`;
}

function renderDiagrams(vehicleId, names) {
  if (!names || !names.length) {
    diagramsEl.innerHTML = `<p class="placeholder">No diagrams available.</p>`;
    return;
  }
  const grid = document.createElement("div");
  grid.className = "grid";
  for (const name of names) {
    const fig = document.createElement("figure");
    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = `/diagrams/${encodeURIComponent(vehicleId)}/${name}`;
    img.alt = name;
    img.addEventListener("click", () => openLightbox(img.src));
    const cap = document.createElement("figcaption");
    cap.textContent = name.replace(/\.gif$/, "");
    fig.append(img, cap);
    grid.append(fig);
  }
  diagramsEl.innerHTML = "";
  diagramsEl.append(grid);
}

vehicleSelect.addEventListener("change", async () => {
  currentVehicleId = vehicleSelect.value;
  resetConversation();
  diagramsEl.innerHTML = `<p class="placeholder">Loading diagrams…</p>`;
  await loadVehicle(currentVehicleId);
});

// ---- Chat ----
function addMessage(role, markdown) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = role === "assistant" ? marked.parse(markdown) : escapeHtml(markdown);
  wrap.append(bubble);
  messagesEl.append(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function renderTrace(toolCalls) {
  const turn = document.createElement("div");
  turn.className = "trace-turn";
  if (!toolCalls || !toolCalls.length) {
    turn.innerHTML = `<div class="turn-label">last answer</div>
      <p class="placeholder">Answered without consulting the manual.</p>`;
  } else {
    const label = document.createElement("div");
    label.className = "turn-label";
    label.textContent = "last answer — sources consulted";
    turn.append(label);
    for (const tc of toolCalls) {
      const item = document.createElement("div");
      item.className = "trace-item";
      const labelFn = TOOL_LABELS[tc.tool];
      item.innerHTML = `<span class="tool">${tc.tool}</span>
        <span class="arg">${escapeHtml(labelFn ? labelFn(tc.input) : JSON.stringify(tc.input))}</span>`;
      turn.append(item);
    }
  }
  // newest turn on top
  if (traceEl.querySelector(".placeholder") && !traceEl.querySelector(".trace-turn")) {
    traceEl.innerHTML = "";
  }
  traceEl.prepend(turn);
}

async function send(text) {
  addMessage("user", text);
  history.push({ role: "user", content: text });
  transcript.push({ role: "user", content: text, at: new Date().toISOString() });
  input.value = "";
  autosize();
  sendBtn.disabled = true;

  const pending = addMessage("assistant", "");
  pending.innerHTML = `<span class="thinking dot-flash">reading the manual</span>`;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages: history, vehicle_id: currentVehicleId }),
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });

    pending.innerHTML = marked.parse(res.reply);
    // Make any images the model embedded inline zoomable.
    pending.querySelectorAll("img").forEach((img) =>
      img.addEventListener("click", () => openLightbox(img.src))
    );
    // Only append diagrams the model did NOT already embed inline (avoids the
    // duplicate render that produced the stretched "blank" figure).
    const reply = res.reply || "";
    const extra = (res.diagrams || []).filter((d) => !reply.includes(d.url));
    if (extra.length) {
      const figs = document.createElement("div");
      figs.className = "answer-figures";
      for (const d of extra) {
        const fig = document.createElement("figure");
        const img = document.createElement("img");
        img.loading = "lazy";
        img.src = d.url;
        img.alt = d.figure_id;
        img.addEventListener("click", () => openLightbox(d.url));
        const cap = document.createElement("figcaption");
        cap.textContent = d.figure_id;
        fig.append(img, cap);
        figs.append(fig);
      }
      pending.append(figs);
    }
    history.push({ role: "assistant", content: res.reply });
    transcript.push({
      role: "assistant",
      content: res.reply,
      tool_calls: res.tool_calls || [],
      diagrams: res.diagrams || [],
      at: new Date().toISOString(),
    });
    renderTrace(res.tool_calls);
  } catch (e) {
    pending.innerHTML = `<span class="thinking">⚠️ ${escapeHtml(e.message)} — is the backend running with an API key?</span>`;
    transcript.push({ role: "assistant", error: e.message, at: new Date().toISOString() });
  } finally {
    sendBtn.disabled = false;
    messagesEl.scrollTop = messagesEl.scrollHeight;
    input.focus();
  }
}

// ---- UI wiring ----
form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (text && !sendBtn.disabled) send(text);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}
input.addEventListener("input", autosize);

document.querySelectorAll(".example").forEach((b) =>
  b.addEventListener("click", () => send(b.textContent))
);

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(tab.dataset.tab).classList.add("active");
  })
);

// Export the full conversation (messages + tool calls + diagrams) as JSON.
const exportBtn = document.getElementById("export");
exportBtn.addEventListener("click", () => {
  if (!transcript.length) {
    exportBtn.textContent = "nothing yet";
    setTimeout(() => (exportBtn.textContent = "⬇ Export"), 1200);
    return;
  }
  const payload = {
    exported_at: new Date().toISOString(),
    vehicle: vehicleLabel,
    page_url: location.href,
    turn_count: transcript.length,
    transcript,            // human-facing turns with tool calls + diagrams
    raw_history: history,  // exact messages sent to /api/chat
  };
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `podbay-conversation-${stamp}.json`;
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
});

// Lightbox for diagrams
const lightbox = document.createElement("div");
lightbox.id = "lightbox";
lightbox.innerHTML = `<img alt="diagram" />`;
lightbox.addEventListener("click", () => lightbox.classList.remove("open"));
document.body.append(lightbox);
function openLightbox(src) {
  lightbox.querySelector("img").src = src;
  lightbox.classList.add("open");
}

init();
