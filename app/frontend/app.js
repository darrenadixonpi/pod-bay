// Pod Bay frontend — streaming chat + photo/voice input + tool-trace + diagram gallery.
// Talks to the same-origin FastAPI backend (/api/*).

// ── Element refs ──────────────────────────────────────────────────────────────

const messagesEl     = document.getElementById("messages");
const traceEl        = document.getElementById("trace");
const diagramsEl     = document.getElementById("diagrams");
const form           = document.getElementById("composer");
const input          = document.getElementById("input");
const sendBtn        = document.getElementById("send");
const photoBtn       = document.getElementById("photo-btn");
const micBtn         = document.getElementById("mic-btn");
const photoInput     = document.getElementById("photo-input");
const attachPreview  = document.getElementById("attach-preview");
const attachThumb    = document.getElementById("attach-thumb");
const clearAttachBtn = document.getElementById("clear-attach");

// ── State ─────────────────────────────────────────────────────────────────────

// Conversation history sent to the backend each turn (text-only or multimodal).
let history = [];
// Richer transcript for the JSON export.
let transcript = [];
let vehicleLabel     = "";
let currentVehicleId = null;
// Photo waiting to be sent with the next message.
let pendingImage     = null; // { data: base64string, mediaType: "image/jpeg" }
// Workshop section ids present for the current vehicle — citations are only
// linkified when they match one of these, so no dead links are created.
const knownSections = new Set();

// ── Conversation persistence (localStorage) ──────────────────────────────────

const convKey = (id) => `pb_conv_${id}`;

function saveConv() {
  if (!currentVehicleId || !transcript.length) return;
  try {
    localStorage.setItem(convKey(currentVehicleId),
      JSON.stringify({ history, transcript, savedAt: new Date().toISOString() }));
  } catch { /* localStorage full or unavailable */ }
}

function clearConv() {
  if (currentVehicleId) localStorage.removeItem(convKey(currentVehicleId));
  resetConversation();
}

function restoreConv(vehicleId) {
  let saved;
  try {
    const raw = localStorage.getItem(convKey(vehicleId));
    if (!raw) return;
    saved = JSON.parse(raw);
  } catch { return; }
  if (!saved?.transcript?.length) return;

  history    = saved.history    || [];
  transcript = saved.transcript;

  for (const entry of transcript) {
    if (entry.role === "user") {
      // Images can't be stored in localStorage — add an inline note
      const txt = entry.hasImage
        ? (entry.content ? `📷  ${entry.content}` : "📷  [photo]")
        : (entry.content || "");
      addUserMessage(txt, null);
    } else if (entry.role === "assistant") {
      const wrap   = document.createElement("div");
      wrap.className = "msg assistant";
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      if (entry.error) {
        bubble.innerHTML = `<span class="thinking">⚠️ ${escapeHtml(entry.error)}</span>`;
      } else {
        bubble.innerHTML = marked.parse(entry.content || "");
        bubble.querySelectorAll("img").forEach((img) =>
          img.addEventListener("click", () => openLightbox(img.src))
        );
        linkifySections(bubble);
        appendExtraDiagrams(entry.diagrams || [], bubble, entry.content || "");
      }
      wrap.append(bubble);
      messagesEl.append(wrap);
    }
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Vehicle picker + diagram gallery ─────────────────────────────────────────

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
  } catch {
    vehicleSelect.innerHTML = `<option>(backend offline)</option>`;
    backendUp = false;
    updateComposerState();
  }
}

async function loadVehicle(id) {
  const [v, secs] = await Promise.all([
    fetch(`/api/vehicle?vehicle_id=${encodeURIComponent(id)}`).then((r) => r.json()),
    fetch(`/api/sections?vehicle_id=${encodeURIComponent(id)}`).then((r) => r.json()).catch(() => null),
  ]);
  vehicleLabel = v.label;
  renderDiagrams(v.id, v.diagrams);
  renderSections(secs, v.search);
  restoreConv(id);
}

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

function renderSections(data, searchInfo) {
  const el = document.getElementById("sections");
  if (!data || (!data.workshop.length && !data.owners.length)) {
    el.innerHTML = `<p class="placeholder">No section index available.</p>`;
    return;
  }
  const parts = [];
  knownSections.clear();

  if (data.workshop.length) {
    parts.push(`<div class="section-group-label">Workshop Manual</div>`);
    for (const s of data.workshop) {
      knownSections.add(s.section);
      parts.push(`<button class="section-item" data-section="${escapeHtml(s.section)}"
        data-query="Section ${escapeHtml(s.section)}: ${escapeHtml(s.name)}">
        <span class="section-id">${escapeHtml(s.section)}</span>
        <span class="section-name">${escapeHtml(s.name)}</span>
        <span class="section-meta">${s.page_count} pp</span>
      </button>`);
    }
  }

  if (data.owners.length) {
    parts.push(`<div class="section-group-label">Owner's Manual</div>`);
    for (const ch of data.owners) {
      parts.push(`<button class="section-item"
        data-query="What does the ${escapeHtml(ch)} section cover?">
        <span class="section-name">${escapeHtml(ch)}</span>
      </button>`);
    }
  }

  if (searchInfo) {
    const mode  = searchInfo.effective || "keyword";
    const cls   = mode === "hybrid" ? "hybrid" : "keyword";
    const note  = mode === "hybrid"
      ? "Keyword + semantic (vector) search active"
      : (searchInfo.index_built === false
          ? "Keyword-only — run <code>python -m vectorstore</code> to enable hybrid"
          : "Keyword-only search");
    parts.push(`<div class="search-info">
      <span class="search-pill ${cls}">${mode}</span>
      <span>${note}</span>
    </div>`);
  }

  el.innerHTML = parts.join("");

  el.querySelectorAll(".section-item").forEach((btn) =>
    btn.addEventListener("click", () => {
      input.value = btn.dataset.query;
      input.focus();
      autosize();
      if (window.innerWidth <= 768) closeDrawer();
    })
  );
}

vehicleSelect.addEventListener("change", async () => {
  currentVehicleId = vehicleSelect.value;
  resetConversation();
  diagramsEl.innerHTML = `<p class="placeholder">Loading diagrams…</p>`;
  await loadVehicle(currentVehicleId);
});

// ── Photo attachment ──────────────────────────────────────────────────────────

function attachImage(file) {
  if (!file || !file.type.startsWith("image/")) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const dataUrl = e.target.result;
    // "data:image/jpeg;base64,/9j/..." → split off the header
    const comma = dataUrl.indexOf(",");
    const header = dataUrl.slice(0, comma);
    const mediaType = (header.match(/:(.*?);/) || [])[1] || "image/jpeg";
    pendingImage = { data: dataUrl.slice(comma + 1), mediaType };
    attachThumb.src = dataUrl;
    attachPreview.hidden = false;
  };
  reader.readAsDataURL(file);
}

function clearPendingImage() {
  pendingImage = null;
  attachPreview.hidden = true;
  attachThumb.src = "";
}

photoBtn.addEventListener("click", () => photoInput.click());

photoInput.addEventListener("change", () => {
  attachImage(photoInput.files[0]);
  photoInput.value = ""; // reset so the same file can be re-attached
});

clearAttachBtn.addEventListener("click", clearPendingImage);

// Attach thumbnail is itself zoomable
attachThumb.addEventListener("click", () => {
  if (attachThumb.src) openLightbox(attachThumb.src);
});

// Drag image file onto the chat area
messagesEl.addEventListener("dragover", (e) => {
  e.preventDefault();
  messagesEl.classList.add("drag-over");
});
messagesEl.addEventListener("dragleave", () => messagesEl.classList.remove("drag-over"));
messagesEl.addEventListener("drop", (e) => {
  e.preventDefault();
  messagesEl.classList.remove("drag-over");
  const file = Array.from(e.dataTransfer.files).find((f) => f.type.startsWith("image/"));
  if (file) attachImage(file);
});

// Paste image from clipboard (Ctrl+V / Cmd+V)
document.addEventListener("paste", (e) => {
  const item = Array.from(e.clipboardData.items).find((i) => i.type.startsWith("image/"));
  if (item) {
    e.preventDefault();
    attachImage(item.getAsFile());
  }
});

// ── Voice input ───────────────────────────────────────────────────────────────

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition   = null;
let isListening   = false;
let stoppedByUser = false; // distinguish manual stop from natural end-of-speech

if (!SR) {
  // Browser doesn't support speech recognition — hide the button
  micBtn.hidden = true;
} else {
  recognition = new SR();
  recognition.continuous     = false;
  recognition.interimResults = true;
  recognition.lang           = "en-US";
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    isListening = true;
    micBtn.classList.add("listening");
    micBtn.title = "Stop listening";
    input.placeholder = "Listening…";
  };

  recognition.onresult = (e) => {
    let interim = "";
    let final   = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) final += t;
      else interim += t;
    }
    input.value = final || interim;
    autosize();
  };

  recognition.onend = () => {
    isListening = false;
    micBtn.classList.remove("listening");
    micBtn.title = "Voice input";
    input.placeholder = "Describe the problem or ask a question…";
    // Auto-send on natural end of speech (not when user clicked Stop)
    const text = input.value.trim();
    if (!stoppedByUser && text && !sendBtn.disabled) {
      send(text);
    }
    stoppedByUser = false;
  };

  recognition.onerror = (e) => {
    isListening = false;
    micBtn.classList.remove("listening");
    micBtn.title = "Voice input";
    input.placeholder = "Describe the problem or ask a question…";
    stoppedByUser = false;
    if (e.error !== "aborted" && e.error !== "no-speech") {
      console.warn("Speech recognition error:", e.error);
    }
  };

  micBtn.addEventListener("click", () => {
    if (isListening) {
      stoppedByUser = true;
      recognition.stop();
    } else {
      try {
        recognition.start();
      } catch (err) {
        // Already started (can happen on rapid clicks)
        console.warn("recognition.start():", err);
      }
    }
  });
}

// ── Human-readable tool labels ────────────────────────────────────────────────

const TOOL_LABELS = {
  search_manual:      (i) => `searching for "${i.query}"`,
  get_section:        (i) => `reading section ${i.section_id}${i.around_page ? ` (p. ${i.around_page})` : ""}`,
  lookup_component:   (i) => `looking up "${i.query}" in the wiring database`,
  get_diagram:        (i) => `fetching diagram ${i.figure_id}`,
  get_wiring_diagram: (i) => `pulling wiring schematic for "${i.query}"`,
};

// ── Chat message helpers ──────────────────────────────────────────────────────

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/** Append a user bubble (with optional attached image thumbnail). */
function addUserMessage(text, imageSrc) {
  const wrap   = document.createElement("div");
  wrap.className = "msg user";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (imageSrc) {
    const img = document.createElement("img");
    img.src   = imageSrc;
    img.className = "user-image";
    img.alt   = "attached photo";
    img.addEventListener("click", () => openLightbox(img.src));
    bubble.append(img);
  }
  if (text) {
    const p = document.createElement("p");
    p.className = "user-text";
    p.textContent = text;
    bubble.append(p);
  }
  wrap.append(bubble);
  messagesEl.append(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return bubble;
}

/** Create the two-zone streaming bubble used for assistant turns.
 *  - textEl   receives markdown-rendered text tokens as they arrive
 *  - statusEl shows the current tool-call status (hidden when text flows)
 */
function createStreamBubble() {
  const wrap     = document.createElement("div");
  wrap.className = "msg assistant";
  const bubble   = document.createElement("div");
  bubble.className = "bubble";

  const textEl   = document.createElement("div");
  textEl.className = "stream-text";

  const statusEl = document.createElement("div");
  statusEl.className = "tool-status";
  statusEl.innerHTML = `<span class="thinking dot-flash">reading the manual</span>`;

  bubble.append(textEl, statusEl);
  wrap.append(bubble);
  messagesEl.append(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return { bubble, textEl, statusEl };
}

/** Append diagrams the model didn't already embed inline. */
function appendExtraDiagrams(diagrams, bubble, fullText) {
  const extra = (diagrams || []).filter((d) => !fullText.includes(d.url));
  if (!extra.length) return;
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
  bubble.append(figs);
}

// ── Clickable section citations ───────────────────────────────────────────────
// Turn "Section 06-03" mentions in an answer into links that jump to (and flash)
// that section in the Sections browser. Only real sections (knownSections) are
// linked; code/pre/existing links are left alone.

const SECTION_CITE_RE = /\bSection\s+(\d+-\d+)\b/g;

function linkifySections(root) {
  if (!root || !knownSections.size) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.nodeValue || !/\bSection\s+\d+-\d+/.test(node.nodeValue))
        return NodeFilter.FILTER_REJECT;
      for (let pn = node.parentNode; pn && pn !== root; pn = pn.parentNode) {
        const tag = pn.nodeName;
        if (tag === "CODE" || tag === "PRE" || tag === "A") return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);

  for (const node of nodes) {
    const text = node.nodeValue;
    const frag = document.createDocumentFragment();
    let m, last = 0, linked = false;
    SECTION_CITE_RE.lastIndex = 0;
    while ((m = SECTION_CITE_RE.exec(text))) {
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (knownSections.has(m[1])) {
        const a = document.createElement("a");
        a.className = "section-cite";
        a.href = "#";
        a.dataset.section = m[1];
        a.textContent = m[0];
        a.addEventListener("click", (e) => { e.preventDefault(); jumpToSection(m[1]); });
        frag.appendChild(a);
        linked = true;
      } else {
        frag.appendChild(document.createTextNode(m[0])); // unknown — leave as text
      }
      last = m.index + m[0].length;
    }
    if (linked) {
      if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
      node.parentNode.replaceChild(frag, node);
    }
  }
}

function jumpToSection(id) {
  // Activate the Sections tab + panel
  document.querySelectorAll(".tab").forEach((tb) =>
    tb.classList.toggle("active", tb.dataset.tab === "sections"));
  document.querySelectorAll(".panel").forEach((pn) =>
    pn.classList.toggle("active", pn.id === "sections"));
  if (window.innerWidth <= 768) openDrawer();

  const item = document.querySelector(`#sections .section-item[data-section="${CSS.escape(id)}"]`);
  if (item) {
    item.scrollIntoView({ block: "center", behavior: "smooth" });
    item.classList.remove("flash");
    void item.offsetWidth; // force reflow so the animation can replay
    item.classList.add("flash");
  }
}

// ── Trace panel ───────────────────────────────────────────────────────────────

function addLiveTraceItem(tool, toolInput) {
  let turnEl = traceEl.querySelector(".trace-turn.current");
  if (!turnEl) {
    if (traceEl.querySelector(".placeholder") && !traceEl.querySelector(".trace-turn")) {
      traceEl.innerHTML = "";
    }
    turnEl = document.createElement("div");
    turnEl.className = "trace-turn current";
    const label = document.createElement("div");
    label.className = "turn-label";
    label.textContent = "this answer — sources consulted";
    turnEl.append(label);
    traceEl.prepend(turnEl);
  }
  const item = document.createElement("div");
  item.className = "trace-item";
  const labelFn = TOOL_LABELS[tool];
  const desc    = labelFn ? labelFn(toolInput) : JSON.stringify(toolInput);
  item.innerHTML = `<span class="tool">${escapeHtml(tool)}</span>
    <span class="arg">${escapeHtml(desc)}</span>`;
  turnEl.append(item);
}

function finaliseTrace(toolCalls) {
  const turnEl = traceEl.querySelector(".trace-turn.current");
  if (turnEl) {
    turnEl.classList.remove("current");
    const label = turnEl.querySelector(".turn-label");
    if (label) label.textContent = "last answer — sources consulted";
  }
  if (!toolCalls || !toolCalls.length) {
    if (traceEl.querySelector(".placeholder") && !traceEl.querySelector(".trace-turn")) {
      traceEl.innerHTML = "";
    }
    const turn = document.createElement("div");
    turn.className = "trace-turn";
    turn.innerHTML = `<div class="turn-label">last answer</div>
      <p class="placeholder">Answered without consulting the manual.</p>`;
    traceEl.prepend(turn);
  }
  // Let the panel-toggle badge know there's new content (mobile only)
  if (toolCalls && toolCalls.length) flashPanelToggle();
}

// ── Main send function (streaming + multimodal) ───────────────────────────────

async function send(text) {
  // Build the content block: plain string, or image + text array.
  let msgContent;
  let imgSrc = null;
  if (pendingImage) {
    msgContent = [
      {
        type: "image",
        source: {
          type: "base64",
          media_type: pendingImage.mediaType,
          data: pendingImage.data,
        },
      },
      { type: "text", text },
    ];
    imgSrc = attachThumb.src;
    clearPendingImage();
  } else {
    msgContent = text;
  }

  addUserMessage(text, imgSrc);
  history.push({ role: "user", content: msgContent });
  transcript.push({
    role: "user",
    content: text,
    hasImage: !!imgSrc,
    at: new Date().toISOString(),
  });

  input.value = "";
  autosize();
  sending = true;
  updateComposerState();

  const { bubble, textEl, statusEl } = createStreamBubble();
  let fullText = "";
  let hasText  = false;

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages: history, vehicle_id: currentVehicleId }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let data;
        try { data = JSON.parse(line.slice(6)); } catch { continue; }

        if (data.type === "text") {
          if (!hasText) {
            statusEl.hidden = true;
            hasText = true;
          }
          fullText += data.delta;
          textEl.innerHTML = marked.parse(fullText);
          messagesEl.scrollTop = messagesEl.scrollHeight;

        } else if (data.type === "tool_call") {
          const labelFn = TOOL_LABELS[data.tool];
          const desc    = labelFn ? labelFn(data.input) : data.tool;
          statusEl.innerHTML = `<span class="thinking dot-flash">${escapeHtml(desc)}</span>`;
          if (hasText) statusEl.classList.add("after-text");
          statusEl.hidden = false;
          addLiveTraceItem(data.tool, data.input);

        } else if (data.type === "done") {
          statusEl.hidden = true;
          textEl.querySelectorAll("img").forEach((img) =>
            img.addEventListener("click", () => openLightbox(img.src))
          );
          linkifySections(textEl);
          appendExtraDiagrams(data.diagrams, bubble, fullText);
          history.push({ role: "assistant", content: fullText });
          transcript.push({
            role: "assistant",
            content: fullText,
            tool_calls: data.tool_calls || [],
            diagrams: data.diagrams || [],
            at: new Date().toISOString(),
          });
          finaliseTrace(data.tool_calls);
          saveConv();

        } else if (data.type === "error") {
          statusEl.hidden = true;
          if (!hasText) {
            textEl.innerHTML = `<span class="thinking">⚠️ ${escapeHtml(data.message)}</span>`;
          }
          transcript.push({ role: "assistant", error: data.message, at: new Date().toISOString() });
        }
      }
    }
  } catch (e) {
    statusEl.hidden = true;
    if (!hasText) {
      textEl.innerHTML = `<span class="thinking">⚠️ ${escapeHtml(e.message)} — is the backend running with an API key?</span>`;
    }
    transcript.push({ role: "assistant", error: e.message, at: new Date().toISOString() });
    checkBackend(); // a fetch failure likely means the backend is unreachable
  } finally {
    sending = false;
    updateComposerState();
    messagesEl.scrollTop = messagesEl.scrollHeight;
    if (composerUsable()) input.focus();
  }
}

// ── Connectivity awareness ────────────────────────────────────────────────────
// The composer is usable only when the browser is online AND the backend
// answers /api/health. `sending` blocks it during an in-flight request. All
// three feed one place (updateComposerState) so the disabled/placeholder/banner
// states never drift apart.

const netBanner = document.getElementById("net-banner");
let sending   = false;
let online    = navigator.onLine;
let backendUp = true;            // optimistic until the first probe says otherwise
let healthTimer = null;

function composerUsable() { return online && backendUp; }

function updateComposerState() {
  const usable  = composerUsable();
  const blocked = sending || !usable;
  sendBtn.disabled  = blocked;
  photoBtn.disabled = blocked;
  if (micBtn) micBtn.disabled = blocked;
  if (!sending) {
    input.placeholder = usable
      ? "Describe the problem or ask a question…"
      : (online ? "Server unreachable — can't send right now"
                : "You're offline — reconnect to send");
  }
  renderNetBanner();
}

function renderNetBanner() {
  if (composerUsable()) { netBanner.hidden = true; netBanner.className = ""; return; }
  netBanner.hidden = false;
  if (!online) {
    netBanner.className = "offline";
    netBanner.textContent =
      "⚠ You're offline. The interface and any diagrams you've already opened still " +
      "work — new answers resume automatically when you reconnect.";
  } else {
    netBanner.className = "backend-down";
    netBanner.textContent = "⚠ Can't reach the Pod Bay server. Retrying…";
  }
}

async function checkBackend() {
  if (!online) { backendUp = false; updateComposerState(); return; }
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 4000);
    const r = await fetch("/api/health", { signal: ctrl.signal, cache: "no-store" });
    clearTimeout(timer);
    backendUp = r.ok;
  } catch {
    backendUp = false;
  }
  updateComposerState();
}

function startHealthPolling() {
  if (healthTimer) return;
  healthTimer = setInterval(() => {
    // Only poll when the tab is visible — no point probing in the background.
    if (document.visibilityState === "visible") checkBackend();
  }, 15000);
}

window.addEventListener("online",  () => { online = true;  checkBackend(); });
window.addEventListener("offline", () => { online = false; updateComposerState(); });
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") checkBackend();
});

// Establish the initial state immediately, then probe the backend.
updateComposerState();
checkBackend();
startHealthPolling();

// ── UI wiring ─────────────────────────────────────────────────────────────────

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if ((text || pendingImage) && !sendBtn.disabled) send(text);
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
  b.addEventListener("click", () => { if (!sendBtn.disabled) send(b.textContent); })
);

document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(tab.dataset.tab).classList.add("active");
  })
);

// ── New chat ─────────────────────────────────────────────────────────────────

document.getElementById("new-chat").addEventListener("click", () => {
  clearConv();
  input.focus();
});

// ── Export ────────────────────────────────────────────────────────────────────

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
    transcript,
    raw_history: history,
  };
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const blob  = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const a     = document.createElement("a");
  a.href      = URL.createObjectURL(blob);
  a.download  = `podbay-conversation-${stamp}.json`;
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
});

// ── Lightbox ──────────────────────────────────────────────────────────────────

const lightbox = document.createElement("div");
lightbox.id = "lightbox";
lightbox.innerHTML = `<img alt="diagram" />`;
lightbox.addEventListener("click", () => lightbox.classList.remove("open"));
document.body.append(lightbox);

function openLightbox(src) {
  lightbox.querySelector("img").src = src;
  lightbox.classList.add("open");
}


// ── Mobile reference-panel drawer ────────────────────────────────────────────

const panelToggle    = document.getElementById("panel-toggle");
const refCol         = document.getElementById("ref-col");
const drawerBackdrop = document.getElementById("drawer-backdrop");

function openDrawer() {
  refCol.classList.add("open");
  drawerBackdrop.classList.add("show");
  panelToggle.textContent = "\u2715 Close";
  panelToggle.classList.remove("has-update");
}

function closeDrawer() {
  refCol.classList.remove("open");
  drawerBackdrop.classList.remove("show");
  panelToggle.textContent = "\U0001f4cb Sources";
}

/** Badge-pulse the toggle button when trace updates while drawer is closed. */
function flashPanelToggle() {
  if (window.innerWidth <= 768 && !refCol.classList.contains("open")) {
    panelToggle.classList.add("has-update");
  }
}

panelToggle.addEventListener("click", () =>
  refCol.classList.contains("open") ? closeDrawer() : openDrawer()
);
drawerBackdrop.addEventListener("click", closeDrawer);

// Swipe down on the drawer to dismiss
let touchStartY = 0;
refCol.addEventListener("touchstart", (e) => {
  touchStartY = e.touches[0].clientY;
}, { passive: true });
refCol.addEventListener("touchend", (e) => {
  if (e.changedTouches[0].clientY - touchStartY > 80) closeDrawer();
});

// Close drawer when switching vehicles
vehicleSelect.addEventListener("change", closeDrawer);

// Close drawer when resizing back to desktop
window.addEventListener("resize", () => {
  if (window.innerWidth > 768) closeDrawer();
});


// ── Service worker (PWA) ──────────────────────────────────────────────────────

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').then((reg) => {
    // When a new SW finishes installing while an old one controls the page,
    // show a non-intrusive toast so the user can reload to get the update.
    reg.addEventListener('updatefound', () => {
      const next = reg.installing;
      next.addEventListener('statechange', () => {
        if (next.state === 'installed' && navigator.serviceWorker.controller) {
          showUpdateToast();
        }
      });
    });
  }).catch((err) => console.warn('SW registration failed:', err));
}

function showUpdateToast() {
  if (document.querySelector('.update-toast')) return; // already showing
  const toast = document.createElement('div');
  toast.className = 'update-toast';
  toast.innerHTML = '🔄 Update available &nbsp;<button id="sw-reload">Reload</button>';
  document.body.append(toast);
  document.getElementById('sw-reload').addEventListener('click', () => {
    navigator.serviceWorker.controller?.postMessage({ type: 'SKIP_WAITING' });
    // Reload once the new SW takes control
    navigator.serviceWorker.addEventListener('controllerchange', () => location.reload(), { once: true });
  });
}
// ── Go ────────────────────────────────────────────────────────────────────────

init();
