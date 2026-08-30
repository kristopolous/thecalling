/* The Calling! -- browser side.
 *
 * Draws the dungeon, then keeps it in sync with the phone call over SSE.
 * The page never decides anything about the game; it only renders what the
 * server pushes after each turn.
 */

const NS = "http://www.w3.org/2000/svg";
const CELL = 92;
const GAP = 30;
const PITCH = CELL + GAP;
const PAD = 26;

const GHOST_COLORS = ["#6fa8c4", "#a58ac9", "#7fa86a", "#c98a9b", "#c4a86f", "#7f9ac9"];

const ITEM_GLYPHS = {
  rope: "⌇", fungus: "✻", sword: "†", keys: "⚷", charm: "◈",
  amulet: "◎", acid: "⚗", brass_key: "⚷", skull: "☠", crown: "♛",
};
const MONSTER_GLYPHS = { skeleton: "☠", rats: "≋", spider: "✵", wight: "◑" };

const el = (id) => document.getElementById(id);

/* "The Vault" already has its article; "Ossuary" needs one. */
const the = (name) => (/^the /i.test(name || "") ? name : `the ${name}`);

/* A run keeps the same colour in the list and on the map. Leaderboard order
 * assigns first, so the best runs get the front of the palette. */
let runColors = new Map();

function assignColors() {
  runColors = new Map();
  const ordered = [...(state.leaderboard || []), ...(state.ghosts || [])];
  for (const run of ordered) {
    if (run.id && !runColors.has(run.id)) {
      runColors.set(run.id, GHOST_COLORS[runColors.size % GHOST_COLORS.length]);
    }
  }
}

const colorOf = (id) => runColors.get(id) || "#5a5563";
const svg = el("map");

let MAP = null;          // static world geometry
let state = null;        // latest push from the server
let code = null;
let clockBase = 0;       // elapsed seconds at the last push
let clockSetAt = 0;      // performance.now() at the last push

/* ------------------------------------------------------------------ helpers */

const cx = (room) => PAD + room.x * PITCH + CELL / 2;
const cy = (room) => PAD + room.y * PITCH + CELL / 2;

function make(tag, attrs, text) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  if (text != null) node.textContent = text;
  return node;
}

function clock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/* -------------------------------------------------------------- static map */

function torchGradient() {
  const defs = make("defs");
  const grad = make("radialGradient", { id: "torchlight" });
  for (const [offset, color] of [["0%", "#ffab3d38"], ["42%", "#ffab3d16"], ["100%", "#ffab3d00"]]) {
    grad.appendChild(make("stop", { offset, "stop-color": color }));
  }
  defs.appendChild(grad);
  return defs;
}

function drawBase() {
  const w = PAD * 2 + MAP.width * PITCH - GAP;
  const h = PAD * 2 + MAP.height * PITCH - GAP;
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.innerHTML = "";

  const byKey = Object.fromEntries(MAP.rooms.map((r) => [r.key, r]));
  MAP.byKey = byKey;

  const layers = {};
  // The torch sits above the stonework but under everything that must stay
  // readable, so it lights the map without washing anything out.
  svg.appendChild(torchGradient());
  for (const name of ["doors", "rooms", "torch", "ghosts", "glyphs", "wanderer", "you"]) {
    layers[name] = make("g", { class: `layer-${name}` });
    svg.appendChild(layers[name]);
  }
  MAP.layers = layers;

  // Doors first, so the room plates sit on top of their ends.
  for (const door of MAP.doors) {
    const a = byKey[door.a], b = byKey[door.b];
    const line = make("line", {
      x1: cx(a), y1: cy(a), x2: cx(b), y2: cy(b),
      class: "door",
      "data-door": `${door.a}:${door.b}`,
    });
    layers.doors.appendChild(line);
  }

  for (const room of MAP.rooms) {
    const g = make("g", { "data-room": room.key });
    g.appendChild(make("rect", {
      x: PAD + room.x * PITCH, y: PAD + room.y * PITCH,
      width: CELL, height: CELL, rx: 4, class: "room-plate",
    }));
    // Room names wrap onto two lines so long ones stay inside the plate.
    const words = room.name.split(" ");
    const lines = words.length > 2 ? [words.slice(0, 2).join(" "), words.slice(2).join(" ")]
                                   : [words.join(" ")];
    lines.forEach((text, i) => {
      g.appendChild(make("text", {
        x: cx(room), y: PAD + room.y * PITCH + CELL - 12 + (i - lines.length + 1) * 10,
        "text-anchor": "middle", class: "room-label",
      }, text));
    });
    layers.rooms.appendChild(g);
  }
}

/* --------------------------------------------------------------- live layer */

function renderMap() {
  const game = state && state.game;
  const seen = new Set(game ? game.visited : []);
  const here = game ? game.room : null;

  for (const room of MAP.rooms) {
    const g = MAP.layers.rooms.querySelector(`[data-room="${room.key}"]`);
    const plate = g.querySelector(".room-plate");
    const known = seen.has(room.key);
    plate.setAttribute("class", `room-plate${known ? " seen" : ""}${room.key === here ? " here" : ""}`);
    for (const label of g.querySelectorAll(".room-label")) {
      label.setAttribute("class", `room-label${known ? " seen" : ""}${room.key === here ? " here" : ""}`);
    }
  }

  const unlocked = new Set(game ? game.unlocked : []);
  for (const door of MAP.doors) {
    const id = `${door.a}:${door.b}`;
    const line = MAP.layers.doors.querySelector(`[data-door="${id}"]`);
    const known = seen.has(door.a) || seen.has(door.b);
    let cls = "door";
    if (door.secret && !(game && game.secret_open)) cls += " hidden";
    else if (door.blocked === "webs" && !(game && game.webs_cleared)) cls += " locked";
    else if (door.locked && !unlocked.has(id)) cls += known ? " locked" : "";
    else if (door.locked && unlocked.has(id)) cls += " opened";
    else if (known) cls += " seen";
    line.setAttribute("class", cls);
  }

  renderTorch(game);
  renderGhosts();
  renderGlyphs(game, seen);
  renderWanderer(game);
  renderYou(game);
}

function renderGhosts() {
  const layer = MAP.layers.ghosts;
  layer.innerHTML = "";
  const ghosts = (state && state.ghosts) || [];

  // One point per previous run, marking how far they got. Runs that ended in
  // the same room stack down the middle of the plate, clear of the item glyphs
  // along the top and the room name along the bottom.
  const byRoom = {};
  for (const ghost of ghosts) (byRoom[ghost.deepest_room] ||= []).push(ghost);

  for (const [roomKey, list] of Object.entries(byRoom)) {
    const room = MAP.byKey[roomKey];
    if (!room) continue;
    const left = PAD + room.x * PITCH;
    const top = PAD + room.y * PITCH;
    const flip = room.x >= MAP.width - 1;   // last column reads leftwards

    list.slice(0, 3).forEach((ghost, i) => {
      const color = colorOf(ghost.id);
      const y = top + 40 + i * 11;
      const dotX = flip ? left + CELL - 11 : left + 11;
      const group = make("g", { class: "ghost-group", "data-run": ghost.id || "" });
      group.appendChild(make("circle", { cx: dotX, cy: y - 3, r: 3, fill: color }));
      group.appendChild(make("text", {
        x: dotX + (flip ? -7 : 7), y,
        "text-anchor": flip ? "end" : "start",
        class: "ghost-name", fill: color,
      }, `${ghost.name.slice(0, 11)} ${clock(ghost.elapsed)}`));
      layer.appendChild(group);
    });

    if (list.length > 3) {
      layer.appendChild(make("text", {
        x: flip ? left + CELL - 11 : left + 11, y: top + 40 + 3 * 11,
        "text-anchor": flip ? "end" : "start", class: "ghost-more",
      }, `+${list.length - 3} more`));
    }
  }
}

function focusGhost(runId) {
  const layer = MAP.layers.ghosts;
  layer.classList.toggle("focusing", Boolean(runId));
  for (const group of layer.querySelectorAll(".ghost-group")) {
    group.classList.toggle("lit", group.getAttribute("data-run") === runId);
  }
}

/* The torch the character carries. It follows them room to room, and goes out
 * when the run does. */
function renderTorch(game) {
  const layer = MAP.layers.torch;
  const room = game && MAP.byKey[game.room];
  if (!room || (game.outcome && game.outcome !== "escaped")) {
    layer.innerHTML = "";
    return;
  }
  let torch = layer.querySelector(".torch");
  if (!torch) {
    torch = make("circle", { r: 168, cx: 0, cy: 0, fill: "url(#torchlight)", class: "torch" });
    layer.appendChild(torch);
  }
  torch.setAttribute("transform", `translate(${cx(room)}, ${cy(room)})`);
}

/* The Wanderer is always visible, seen room or not -- dodging it is the game. */
function renderWanderer(game) {
  const layer = MAP.layers.wanderer;
  const room = game && game.wanderer && MAP.byKey[game.wanderer];
  if (!room || (game.outcome && game.outcome !== "escaped")) {
    layer.innerHTML = "";
    return;
  }

  let group = layer.querySelector(".wanderer");
  if (!group) {
    group = make("g", { class: "wanderer" });
    group.appendChild(make("circle", { r: 15, cx: 0, cy: 0, class: "wanderer-haze" }));
    // Drawn at the origin and moved with a transform, because a transform is
    // the only thing an SVG <text> will animate smoothly along.
    group.appendChild(make("text", { x: 0, y: 5, class: "wanderer-mark" }, "\u2668"));
    layer.appendChild(group);
  }
  // Sit in the room's upper corner so it never hides the player's marker.
  group.setAttribute("transform", `translate(${cx(room) + 21}, ${cy(room) - 19})`);
}

function renderGlyphs(game, seen) {
  const layer = MAP.layers.glyphs;
  layer.innerHTML = "";
  if (!game) return;

  const perRoom = {};
  const place = (roomKey, glyph, cls) => {
    const room = MAP.byKey[roomKey];
    if (!room || !seen.has(roomKey)) return;
    const n = (perRoom[roomKey] = (perRoom[roomKey] || 0) + 1) - 1;
    layer.appendChild(make("text", {
      x: PAD + room.x * PITCH + 12 + n * 13,
      y: PAD + room.y * PITCH + 20,
      class: `glyph ${cls}`,
    }, glyph));
  };

  for (const m of game.monsters) place(m.room, MONSTER_GLYPHS[m.key] || "✖", "monster");
  for (const i of game.items_on_floor) place(i.room, ITEM_GLYPHS[i.key] || "▪", "item");
}

function renderYou(game) {
  const layer = MAP.layers.you;
  if (!game) { layer.innerHTML = ""; return; }

  // The trail is rebuilt each turn; the marker itself persists so it can glide.
  layer.querySelector(".you-trail")?.remove();
  const points = [];
  let last = null;
  for (const key of game.path) {
    const room = MAP.byKey[key];
    if (!room || key === last) continue;
    last = key;
    points.push(`${cx(room)},${cy(room)}`);
  }
  if (points.length > 1) {
    // fill="none" on the element as well as in the CSS: an unstyled polyline
    // defaults to a solid black fill, which paints over the whole map.
    layer.insertBefore(
      make("polyline", { points: points.join(" "), class: "you-trail", fill: "none" }),
      layer.firstChild);
  }

  const room = MAP.byKey[game.room];
  if (!room) return;
  const dead = game.outcome === "dead";

  let pulse = layer.querySelector(".pulse");
  if (!dead && !game.outcome) {
    if (!pulse) { pulse = make("circle", { r: 9, class: "pulse" }); layer.appendChild(pulse); }
    pulse.setAttribute("cx", cx(room));
    pulse.setAttribute("cy", cy(room));
  } else if (pulse) {
    pulse.remove();
  }

  keepInView(room);

  let you = layer.querySelector(".you");
  if (!you) { you = make("circle", { r: 6.5, class: "you" }); layer.appendChild(you); }
  you.setAttribute("class", `you${dead ? " dead" : ""}`);
  you.setAttribute("cx", cx(room));
  you.setAttribute("cy", cy(room));
}

/* Scroll the map pane so the character stays on screen as it moves down the
 * dungeon. Works off the rendered geometry, so it does nothing when the whole
 * map already fits. */
function keepInView(room) {
  const wrap = document.querySelector(".map-wrap");
  const ctm = svg.getScreenCTM();
  if (!wrap || !ctm) return;

  const point = new DOMPoint(cx(room), cy(room)).matrixTransform(ctm);
  const box = wrap.getBoundingClientRect();
  const margin = 90;

  let top = 0, left = 0;
  if (point.y > box.bottom - margin) top = point.y - (box.bottom - margin);
  else if (point.y < box.top + margin) top = point.y - (box.top + margin);
  if (point.x > box.right - margin) left = point.x - (box.right - margin);
  else if (point.x < box.left + margin) left = point.x - (box.left + margin);

  if (top || left) wrap.scrollBy({ top, left, behavior: "smooth" });
}

/* ------------------------------------------------------------------ the rail */

function renderRail() {
  const game = state && state.game;

  const claimed = Boolean(state.phone);
  el("claim").hidden = claimed;
  el("change").hidden = !claimed;
  el("dot").className = `status-dot${state.connected ? " live" : ""}`;
  el("link-state").textContent = state.connected
    ? "On the line" : claimed ? "Waiting for your call" : "Not on the line";

  // The number to call is always on show; the code appears once we know which
  // phone is yours, because the code IS the tail of that number.
  el("number").textContent = state.call_number || "phone line offline";
  el("code").textContent = claimed ? state.code : "····";
  el("code").classList.toggle("pending", !claimed);
  el("hint").innerHTML = !state.phone_ready
    ? "The phone line is not running — type your commands below instead."
    : !state.line_live
      ? "Reconnecting to the phone line — type your commands below meanwhile."
      : state.connected
      ? "You are connected. Say <em>look</em> to get your bearings."
      : claimed
        ? `from the number ending <b>${state.code}</b> — we will know it is you.`
        : "Put your number in below, then call.";

  if (game) {
    el("hp").textContent = game.health;
    el("score").textContent = game.score;
    el("warps").textContent = game.warps;
    el("warps-row").hidden = !game.warps;
    const pct = Math.max(0, game.health) / game.max_health * 100;
    const bar = el("hpbar");
    bar.className = `bar${pct <= 30 ? " dying" : pct <= 60 ? " hurt" : ""}`;
    bar.firstElementChild.style.width = `${pct}%`;

    const pack = el("pack");
    pack.innerHTML = "";
    if (!game.inventory.length) {
      pack.innerHTML = "<em>Nothing yet.</em>";
    } else {
      for (const item of game.inventory) {
        const span = document.createElement("span");
        const treasure = MAP.items.find((i) => i.key === item.key)?.treasure;
        if (treasure) span.className = "treasure";
        span.textContent = `${ITEM_GLYPHS[item.key] || ""} ${item.name}`.trim();
        pack.appendChild(span);
      }
    }

    const verdict = el("verdict");
    if (game.outcome) {
      verdict.hidden = false;
      verdict.className = `verdict ${game.outcome}`;
      verdict.textContent = {
        escaped: `Out alive in ${clock(game.elapsed)} with ${game.score} points. ` +
                 `Call back and say "play again" to go down again.`,
        dead: `Dead in ${the(game.room_name)} after ${clock(game.elapsed)}. ` +
              `Call back to try once more.`,
        abandoned: `You hung up in ${the(game.room_name)} after ${clock(game.elapsed)}. ` +
                   `The run is on the board. Call back to start a new one.`,
        quit: `You called it in ${the(game.room_name)} after ${clock(game.elapsed)}, ` +
              `with ${game.score} points. Call back to go down again.`,
      }[game.outcome];
    } else {
      verdict.hidden = true;
    }
  }

  renderLog();
  renderRuns();
}

function renderLog() {
  const log = el("log");
  const lines = (state.transcript || []);
  if (!lines.length) {
    log.innerHTML = `<div class="line"><div class="dungeon">${
      state.connected ? "Say something." : "Call in to begin."}</div></div>`;
    return;
  }
  log.innerHTML = "";
  for (const line of lines) {
    const wrap = document.createElement("div");
    wrap.className = "line";
    const body = document.createElement("div");
    body.className = line.who === "player" ? "player" : "dungeon";
    body.textContent = line.text;
    wrap.appendChild(body);
    log.appendChild(wrap);
  }
  log.scrollTop = log.scrollHeight;
}

function renderRuns() {
  const runs = state.leaderboard || [];
  const summary = state.summary || { runs: 0, escaped: 0, best_time: null };
  const trailed = new Set((state.ghosts || []).map((g) => g.id));
  const totalRooms = MAP.rooms.length;

  const stats = el("runs-stats");
  if (!summary.runs) {
    stats.textContent = "Nobody yet";
  } else {
    const best = summary.best_time != null
      ? ` &middot; best escape <span class="best">${clock(summary.best_time)}</span>` : "";
    stats.innerHTML =
      `<b>${summary.runs}</b> ${summary.runs === 1 ? "run" : "runs"} &middot; ` +
      `<b>${summary.escaped}</b> escaped${best}`;
  }

  const list = el("runs-list");
  if (!runs.length) {
    list.innerHTML = '<p class="runs-empty">No one has come back up from the vault. ' +
                     'The board is yours to open.</p>';
    return;
  }

  list.innerHTML = "";
  runs.forEach((run, i) => {
    const color = colorOf(run.id);
    const row = document.createElement("div");
    row.className = `run ${run.outcome}${i === 0 ? " best" : ""}`;
    row.style.color = color;
    row.innerHTML = `
      <span class="mark${trailed.has(run.id) ? " trailed" : ""}"></span>
      <span class="who"></span>
      <span class="time"></span>
      <span class="where"></span>
      <span class="depth"><i><b></b></i><span class="rooms"></span></span>`;
    row.querySelector(".who").textContent = run.name;
    row.querySelector(".time").textContent = clock(run.elapsed);
    row.querySelector(".where").innerHTML = {
      escaped: '<span class="badge">escaped with the crown</span>',
      dead: `died in ${the(run.deepest_room_name)}`,
      abandoned: `hung up in ${the(run.deepest_room_name)}`,
      quit: `gave up in ${the(run.deepest_room_name)}`,
    }[run.outcome] || `stopped in ${the(run.deepest_room_name)}`;
    row.querySelector(".depth b").style.width =
      `${Math.round((run.rooms / totalRooms) * 100)}%`;
    row.querySelector(".rooms").textContent = `${run.rooms}/${totalRooms}`;

    row.addEventListener("mouseenter", () => focusGhost(run.id));
    row.addEventListener("mouseleave", () => focusGhost(null));
    list.appendChild(row);
  });
}

/* -------------------------------------------------------------------- clock */

function tickClock() {
  const game = state && state.game;
  if (!game) return;
  const live = game.outcome ? game.elapsed
                            : clockBase + (performance.now() - clockSetAt) / 1000;
  el("clock").textContent = clock(live);
}
setInterval(tickClock, 250);

/* ------------------------------------------------------------------- wiring */

function apply(next) {
  state = next;
  assignColors();
  if (state.game) {
    clockBase = state.game.elapsed;
    clockSetAt = performance.now();
  }
  renderMap();
  renderRail();
}

async function boot() {
  MAP = await (await fetch("/api/map")).json();
  drawBase();

  // A returning player is remembered by their phone number, so the dungeon is
  // already theirs when the page loads.
  const savedPhone = localStorage.getItem("kaldrath-phone");
  let bootState = null;
  if (savedPhone) {
    bootState = await claimPhone(savedPhone, localStorage.getItem("kaldrath-name"));
  }
  if (!bootState) {
    bootState = await (await fetch("/api/new")).json();   // keyboard-only play
  }
  code = bootState.code;
  apply(bootState);
  listen();
}

let events = null;

function listen() {
  if (events) events.close();
  events = new EventSource(`/api/events?code=${code}`);
  events.onmessage = (e) => apply(JSON.parse(e.data));
  events.onerror = () => { el("dot").className = "status-dot"; };
}

async function claimPhone(phone, name) {
  const r = await fetch("/api/claim", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phone, name }),
  });
  if (!r.ok) {
    const note = el("claim-note");
    note.className = "claim-note error";
    note.textContent = (await r.json()).error || "That number was not accepted.";
    return null;
  }
  localStorage.setItem("kaldrath-phone", phone);
  if (name) localStorage.setItem("kaldrath-name", name);
  return await r.json();
}

el("claim").addEventListener("submit", async (e) => {
  e.preventDefault();
  const next = await claimPhone(el("phone").value.trim(), el("who").value.trim());
  if (!next) return;
  code = next.code;
  apply(next);
  listen();
});

el("change").addEventListener("click", () => {
  localStorage.removeItem("kaldrath-phone");
  el("phone").value = state.phone || "";
  el("who").value = state.player_name || "";
  apply({ ...state, phone: null });
});

el("compose").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = el("cmd");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  const r = await fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, text }),
  });
  if (r.ok) apply({ ...state, ...(await r.json()) });
});

boot();
