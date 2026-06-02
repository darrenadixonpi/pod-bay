// Pod Bay frontend — chat + tool-trace + diagram gallery.
// Talks to the same-origin FastAPI backend (/api/*).

const messagesEl = document.getElementById("messages");
const traceEl = document.getElementById("trace");
const diagramsEl = document.getElementById("diagrams");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send");

// Conversation history sent to the backend each turn (text only).
const history = [];

// Friendly labels for the tool-call trace.
const TOOL_LABELS = {
  search_manual: (i) => `searched the manual for “${i.query}”`,
  get_section: (i) => `opened section ${i.section_id}`,
  lookup_component: (i) => `looked up “${i.query}” in the wiring database`,
  get_diagram: (i) => `requested diagram ${i.figure_id}`,
};

// ---- Bootstrap: vehicle label + diagram gallery ----
async function init() {
  try {
    const v = await fetch("/api/vehicle").then((r) => r.json());
    document.getElementById("vehicle-label").textContent = v.label;
    renderDiagrams(v.diagrams);
  } catch (e) {
    document.getElementById("vehicle-label").textContent = "(backend offline)";
  }
}

function renderDiagrams(names) {
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
    img.src = `/diagrams/${name}`;
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
  input.value = "";
  autosize();
  sendBtn.disabled = true;

  const pending = addMessage("assistant", "");
  pending.innerHTML = `<span class="thinking dot-flash">reading the manual</span>`;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages: history }),
    }).then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });

    pending.innerHTML = marked.parse(res.reply);
    if (res.diagrams && res.diagrams.length) {
      const figs = document.createElement("div");
      figs.className = "answer-figures";
      for (const d of res.diagrams) {
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
    renderTrace(res.tool_calls);
  } catch (e) {
    pending.innerHTML = `<span class="thinking">⚠️ ${escapeHtml(e.message)} — is the backend running with an API key?</span>`;
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
