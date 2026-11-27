// worker.js - the Telegram front end (Cloudflare Workers, free plan).
//
// It answers instantly (menus, settings, approvals, quotas) and, for a video, starts ONE throw-away GitHub Actions
// machine that does all the heavy work and then disappears. This file never records or renders anything itself.
//
// Secrets (wrangler secret put ...): TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET, DONE_SECRET, GITHUB_TOKEN, PAYLOAD_KEY, SETUP_KEY
// Vars (wrangler.toml): GITHUB_REPO, GITHUB_REF, WORKFLOW_FILE, ADMIN_IDS, DEFAULT_LIMIT, MAX_ACTIVE
// Database: D1 binding "DB" (see schema.sql)

export const TEMPLATES = ["clean-light", "clean-dark", "terrazzo", "editorial", "neon", "sunset", "mint", "bold", "slate", "photo"];
export const FRAMES = ["laptop", "tablet", "monitor", "card", "glass", "plain", "brutal"];
export const CAPTIONS = ["pill", "box", "text", "underline"];
export const DEPTHS = [["Natural", 0], ["Warm", 1], ["Deep", 2], ["Very deep", 3]];
export const FORMATS = [["Vertical reel", "vertical"], ["Instagram", "instagram"], ["Landscape", "landscape"]];
export const EXTRAS = [["Send the script text", "script"], ["Send the transcript file", "transcript"]];
export const PRESETS = {
  "Fast tips": "fast, punchy tips reel for beginners, friendly, about 35 seconds",
  "Tutorial": "calm step-by-step tutorial, clear and patient, about 50 seconds",
  "Tool review": "honest first-impression review of a free tool: what it does, what is good, one limit, about 45 seconds",
  "News style": "short news-style explainer, neutral and factual tone, about 40 seconds",
};
export const DEFAULTS = { template: "clean-light", depth: 2, gender: "male", outputs: ["vertical", "instagram"], captions: "auto", frame: "auto", video_type: "", extras: ["script"] };

const BTN = {
  newVideo: "🎬 New video", template: "🎨 Template", voice: "🗣 Voice", formats: "📐 Formats", captions: "💬 Captions",
  frame: "🧩 Frame", type: "✍️ Video type", status: "📊 My status", help: "❓ Help", extras: "📦 Extras", back: "⬅️ Back",
  done: "✅ Done", random: "🎲 Surprise me", auto: "Auto", clear: "🗑 Clear video type", own: "✍️ Type my own",
};
const stripMark = (t) => t.replace(/^(✅|⬜|🔘|⚪)\s*/u, "").trim();
const mark = (on, label) => `${on ? "✅" : "⬜"} ${label}`;
const radio = (on, label) => `${on ? "🔘" : "⚪"} ${label}`;

// ---------------------------------------------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------------------------------------------
export function looksLikeScript(t) {
  return /^\s*video\s*:/im.test(t) || t.includes("||") || /\[(goto|click|type|scroll|upload|verify|explore|hover|wait|press)\b/i.test(t);
}
const adminIds = (env) => String(env.ADMIN_IDS || "").split(",").map((s) => s.trim()).filter(Boolean).map(Number);
const today = (now) => new Date(now * 1000).toISOString().slice(0, 10);
const esc = (s) => String(s ?? "").replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
const b64e = (u8) => btoa(String.fromCharCode(...u8));
const b64d = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

export async function encryptPayload(obj, keyB64) {
  const key = await crypto.subtle.importKey("raw", b64d(keyB64), "AES-GCM", false, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(JSON.stringify(obj))));
  const out = new Uint8Array(12 + ct.length);
  out.set(iv); out.set(ct, 12);
  return b64e(out);
}

function kb(rows, placeholder) {
  return { reply_markup: { keyboard: rows.map((r) => r.map((text) => ({ text }))), resize_keyboard: true, is_persistent: true, input_field_placeholder: placeholder || "Send an idea or a script…" } };
}
function chunk(arr, n) { const o = []; for (let i = 0; i < arr.length; i += n) o.push(arr.slice(i, i + n)); return o; }

export function mainKeyboard() {
  return kb([[BTN.newVideo, BTN.template], [BTN.voice, BTN.formats], [BTN.captions, BTN.frame], [BTN.type, BTN.extras], [BTN.status, BTN.help]]);
}

// ---------------------------------------------------------------------------------------------------------------
// storage: D1 in production, any object with the same 4 methods in tests
// ---------------------------------------------------------------------------------------------------------------
const hydrate = (r) => r && { ...r, settings: { ...DEFAULTS, ...JSON.parse(r.settings || "{}") }, files: JSON.parse(r.files || "[]") };
export function d1Store(db) {
  return {
    async get(id) { return hydrate(await db.prepare("SELECT * FROM users WHERE id=?").bind(id).first()); },
    async put(u) {
      await db.prepare(`INSERT INTO users(id,name,role,status,settings,state,files,files_at,day,used,lim,active_until,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role, status=excluded.status, settings=excluded.settings, state=excluded.state,
        files=excluded.files, files_at=excluded.files_at, day=excluded.day, used=excluded.used, lim=excluded.lim, active_until=excluded.active_until`)
        .bind(u.id, u.name, u.role, u.status, JSON.stringify(u.settings), u.state, JSON.stringify(u.files), u.files_at, u.day, u.used, u.lim, u.active_until, u.created).run();
    },
    async list() { return ((await db.prepare("SELECT * FROM users ORDER BY created").all()).results || []).map(hydrate); },
    async activeCount(now) { return (await db.prepare("SELECT COUNT(*) AS c FROM users WHERE active_until > ?").bind(now).first()).c; },
  };
}

// ---------------------------------------------------------------------------------------------------------------
// the bot
// ---------------------------------------------------------------------------------------------------------------
export function createBot({ env, store, tg, github, now = () => Math.floor(Date.now() / 1000), rand = Math.random }) {
  const admins = adminIds(env);
  const defaultLimit = Number(env.DEFAULT_LIMIT || 3);
  const maxActive = Number(env.MAX_ACTIVE || 4);
  const say = (chat, text, extra = {}) => tg("sendMessage", { chat_id: chat, text, parse_mode: "HTML", disable_web_page_preview: true, ...extra });

  async function ensureUser(from) {
    let u = await store.get(from.id);
    const isAdmin = admins.includes(from.id);
    const name = [from.first_name, from.last_name].filter(Boolean).join(" ") || from.username || String(from.id);
    if (!u) {
      u = { id: from.id, name, role: isAdmin ? "admin" : "member", status: isAdmin ? "approved" : "pending", settings: { ...DEFAULTS }, state: "", files: [], files_at: 0, day: "", used: 0, lim: defaultLimit, active_until: 0, created: now() };
      await store.put(u);
      u.isNew = true;
    } else if (isAdmin && (u.role !== "admin" || u.status !== "approved")) {
      u.role = "admin"; u.status = "approved"; await store.put(u);
    }
    return u;
  }

  const summary = (u) => {
    const s = u.settings;
    const dn = DEPTHS.find((d) => d[1] === Number(s.depth));
    return `🎨 Template: <b>${esc(s.template === "random" ? "surprise me" : s.template)}</b>\n🗣 Voice: <b>${esc(s.gender)}, ${esc(dn ? dn[0].toLowerCase() : "deep")}</b>\n📐 Formats: <b>${esc(s.outputs.join(", "))}</b>\n💬 Captions: <b>${esc(s.captions)}</b>   🧩 Frame: <b>${esc(s.frame)}</b>\n✍️ Video type: <b>${esc(s.video_type || "not set (default style)")}</b>`;
  };
  const quotaLine = (u) => {
    if (u.role === "admin") return "Daily videos: unlimited (admin)";
    const used = u.day === today(now()) ? u.used : 0;
    return `Daily videos: ${used}/${u.lim}`;
  };

  // ----- menus ---------------------------------------------------------------------------------------------------
  async function showMain(u, chat, text) {
    u.state = ""; await store.put(u);
    return say(chat, text || "Main menu. Pick a setting, or just send me an <b>idea</b> (plain words) or a <b>script</b>.", mainKeyboard());
  }
  async function showMenu(u, chat, which) {
    const s = u.settings;
    u.state = "menu:" + which; await store.put(u);
    if (which === "template") {
      const rows = chunk(TEMPLATES.map((t) => radio(s.template === t, t)), 2);
      rows.push([radio(s.template === "random", BTN.random)], [BTN.back]);
      return say(chat, "Pick a <b>template</b> (tap one):", kb(rows));
    }
    if (which === "voice") {
      const rows = [[radio(s.gender === "male", "Male"), radio(s.gender === "female", "Female")], ...chunk(DEPTHS.map(([n, v]) => radio(Number(s.depth) === v, `${n}`)), 2), [BTN.back]];
      return say(chat, "Pick the <b>voice</b>: Male / Female, then how deep it should sound (Deep is the default; Very deep is a big baritone).", kb(rows));
    }
    if (which === "formats") {
      const rows = [...FORMATS.map(([n, v]) => [mark(s.outputs.includes(v), n)]), [BTN.done]];
      return say(chat, "Select the <b>formats</b> to make (tap to switch on/off, you can pick several), then press Done:", kb(rows));
    }
    if (which === "captions") {
      const rows = chunk([radio(s.captions === "auto", "Auto (template default)"), ...CAPTIONS.map((c) => radio(s.captions === c, c))], 2);
      rows.push([BTN.back]);
      return say(chat, "Pick the <b>subtitle style</b> (always one line):", kb(rows));
    }
    if (which === "frame") {
      const rows = chunk([radio(s.frame === "auto", "Auto (template default)"), ...FRAMES.map((f) => radio(s.frame === f, f))], 2);
      rows.push([BTN.back]);
      return say(chat, "Pick the <b>device frame</b> around the screen recording:", kb(rows));
    }
    if (which === "extras") {
      const rows = [...EXTRAS.map(([n, v]) => [mark(s.extras.includes(v), n)]), [BTN.done]];
      return say(chat, "Extras to send with every video (tap to switch on/off), then Done:", kb(rows));
    }
    if (which === "type") {
      const rows = [...chunk(Object.keys(PRESETS).map((p) => radio(s.video_type === PRESETS[p], p)), 2), [BTN.own, BTN.clear], [BTN.back]];
      return say(chat, `Choose the <b>kind of video</b>. It stays in effect for every video until you change it.\nCurrent: <b>${esc(s.video_type || "none")}</b>\nOr press “${BTN.own}” and describe it in simple words.`, kb(rows));
    }
  }

  async function handleMenuText(u, chat, raw) {
    const t = stripMark(raw);
    const s = u.settings;
    const st = u.state.startsWith("menu:") ? u.state.slice(5) : "";
    if (raw === BTN.back || raw === BTN.done && !["formats", "extras"].includes(st)) { await showMain(u, chat, "Saved. Main menu:"); return true; }
    if (raw === BTN.done) {
      if (st === "formats" && s.outputs.length === 0) { s.outputs = ["vertical"]; }
      await store.put(u); await showMain(u, chat, "Saved ✅"); return true;
    }
    if (st === "template") {
      const hit = t === BTN.random.replace(/^\S+\s/, "") || raw.endsWith("Surprise me") ? "random" : TEMPLATES.find((x) => x === t);
      if (hit) { s.template = hit; await store.put(u); await showMenu(u, chat, "template"); return true; }
    }
    if (st === "voice") {
      if (t === "Male" || t === "Female") { s.gender = t.toLowerCase(); await store.put(u); await showMenu(u, chat, "voice"); return true; }
      const d = DEPTHS.find(([n]) => n === t);
      if (d) { s.depth = d[1]; await store.put(u); await showMenu(u, chat, "voice"); return true; }
    }
    if (st === "formats") {
      const f = FORMATS.find(([n]) => n === t);
      if (f) { s.outputs = s.outputs.includes(f[1]) ? s.outputs.filter((x) => x !== f[1]) : [...s.outputs, f[1]]; await store.put(u); await showMenu(u, chat, "formats"); return true; }
    }
    if (st === "extras") {
      const f = EXTRAS.find(([n]) => n === t);
      if (f) { s.extras = s.extras.includes(f[1]) ? s.extras.filter((x) => x !== f[1]) : [...s.extras, f[1]]; await store.put(u); await showMenu(u, chat, "extras"); return true; }
    }
    if (st === "captions") {
      const c = t.startsWith("Auto") ? "auto" : CAPTIONS.find((x) => x === t);
      if (c) { s.captions = c; await store.put(u); await showMenu(u, chat, "captions"); return true; }
    }
    if (st === "frame") {
      const f = t.startsWith("Auto") ? "auto" : FRAMES.find((x) => x === t);
      if (f) { s.frame = f; await store.put(u); await showMenu(u, chat, "frame"); return true; }
    }
    if (st === "type") {
      if (PRESETS[t]) { s.video_type = PRESETS[t]; await store.put(u); await showMenu(u, chat, "type"); return true; }
      if (raw === BTN.clear) { s.video_type = ""; await store.put(u); await showMenu(u, chat, "type"); return true; }
      if (raw === BTN.own) { u.state = "await:type"; await store.put(u); await say(chat, "Describe the kind of video in <b>simple words</b>, for example:\n<i>calm tutorials for older people, slow and clear, about 50 seconds</i>\nSend <code>clear</code> to remove it.", { reply_markup: { remove_keyboard: true } }); return true; }
    }
    return false;
  }

  // ----- starting a video ----------------------------------------------------------------------------------------
  async function startJob(u, chat, thread, text, files) {
    const t = now();
    if (u.role !== "admin") {
      if (u.day !== today(t)) { u.day = today(t); u.used = 0; }
      if (u.used >= u.lim) { await store.put(u); return say(chat, `You have used your ${u.lim} videos for today. The counter resets at 00:00 UTC.`); }
    }
    if (u.active_until > t) return say(chat, "⏳ You already have a video being made. Wait for it to arrive (usually 3-7 minutes).");
    if ((await store.activeCount(t)) >= maxActive) return say(chat, "The machines are all busy right now. Please try again in a few minutes.");
    const s = u.settings;
    const script = looksLikeScript(text);
    const payload = {
      id: `v${t}-${u.id}`, chat_id: chat, thread_id: thread || null, uid: u.id, user: u.name,
      mode: script ? "script" : "idea", text: text.slice(0, 4000), files: (files || []).slice(0, 5).map((id, i) => ({ file_id: id, name: `photo${i + 1}.jpg` })),
      options: {
        template: s.template === "random" ? TEMPLATES[Math.floor(rand() * TEMPLATES.length)] : s.template,
        depth: Number(s.depth), gender: s.gender, outputs: s.outputs.length ? s.outputs : ["vertical"],
        captions: s.captions === "auto" ? undefined : s.captions, frame: s.frame === "auto" ? undefined : s.frame,
        video_type: s.video_type || undefined, language: /[\u0980-\u09FF]/.test(text) ? "Bangla" : "English", seconds: 40,
        extras: s.extras,
      },
    };
    try {
      await github(payload);
    } catch (e) {
      return say(chat, "I could not start the machine: " + esc(String(e.message || e).slice(0, 200)) + "\nTell the admin.");
    }
    u.used += 1; u.day = today(t); u.active_until = t + 1800; u.files = []; u.state = ""; await store.put(u);
    await say(chat, `🚀 Started. ${script ? "Using your script." : "Gemini will write the script first."} Template <b>${esc(payload.options.template)}</b>, ${esc(s.gender)} voice, depth ${Number(s.depth)}.\n${quotaLine(u)}\nA private machine builds it now; when it's done, it is deleted.`, mainKeyboard());
  }

  // ----- admin ---------------------------------------------------------------------------------------------------
  async function notifyAdmins(u) {
    for (const a of admins) {
      await tg("sendMessage", { chat_id: a, text: `🙋 New member wants access:\n<b>${esc(u.name)}</b>  (id <code>${u.id}</code>)`, parse_mode: "HTML",
        reply_markup: { inline_keyboard: [[{ text: "✅ Approve", callback_data: `ap:${u.id}` }, { text: "⛔ Block", callback_data: `bl:${u.id}` }]] } }).catch(() => {});
    }
  }
  async function setStatus(id, status) {
    const u = await store.get(id);
    if (!u) return null;
    u.status = status; await store.put(u); return u;
  }
  async function adminCommand(u, chat, cmd, arg) {
    const id = Number((arg || "").split(/\s+/)[0]);
    if (cmd === "/approve" || cmd === "/block") {
      if (!id) return say(chat, `Usage: <code>${cmd} 123456789</code>`);
      const m = await setStatus(id, cmd === "/approve" ? "approved" : "blocked");
      if (!m) return say(chat, "I don't know that id yet (the person must message the bot once).");
      if (cmd === "/approve") await say(m.id, "✅ You are approved! Send /start to open the menu.").catch(() => {});
      return say(chat, `${cmd === "/approve" ? "Approved" : "Blocked"} ${esc(m.name)} (${m.id}).`);
    }
    if (cmd === "/limit") {
      const n = Number((arg || "").split(/\s+/)[1]);
      const m = id && (await store.get(id));
      if (!m || !(n >= 0)) return say(chat, "Usage: <code>/limit 123456789 5</code>");
      m.lim = n; await store.put(m); return say(chat, `${esc(m.name)} can now make ${n} videos per day.`);
    }
    if (cmd === "/members") {
      const all = await store.list();
      const lines = all.map((m) => `${m.status === "approved" ? "✅" : m.status === "blocked" ? "⛔" : "⏳"} ${esc(m.name)} <code>${m.id}</code> ${m.role}${m.role === "admin" ? "" : ` ${m.day === today(now()) ? m.used : 0}/${m.lim}`}`);
      return say(chat, lines.join("\n") || "No members yet.");
    }
    if (cmd === "/stats") {
      const all = await store.list(); const t = now();
      return say(chat, `Members: ${all.length}\nApproved: ${all.filter((m) => m.status === "approved").length}\nBuilding now: ${await store.activeCount(t)}\nVideos started today: ${all.filter((m) => m.day === today(t)).reduce((a, m) => a + m.used, 0)}`);
    }
  }

  const HELP = `<b>How it works</b>\n1. Press <b>🎨 Template</b>, <b>🗣 Voice</b>, <b>📐 Formats</b> … to set how videos look (saved for next time).\n2. Press <b>✍️ Video type</b> and describe the kind of video in simple words - it stays active until you change it.\n3. Send an <b>idea</b> in plain words (Gemini writes the script) or a full <b>script</b>. Attach a photo first if the video should upload one.\n4. A private machine builds the video, sends it here, and is deleted.\n\n<b>Script lines</b> (optional): <code>Template: neon</code>, <code>Depth: 3</code>, <code>Outputs: vertical, instagram</code>, <code>Captions: box</code>.\nCommands: /menu /status /cancel /video &lt;idea&gt;`;

  // ----- entry point ---------------------------------------------------------------------------------------------
  async function onMessage(msg) {
    if (!msg.from || msg.from.is_bot) return;
    const chat = msg.chat.id, thread = msg.message_thread_id;
    const isPrivate = msg.chat.type === "private";
    const u = await ensureUser(msg.from);
    if (u.status === "blocked") return;
    if (u.status === "pending") {
      if (isPrivate) await say(chat, "Hi! You're on the waiting list. The admin has to approve you first - I'll message you here when it happens.");
      if (u.isNew) await notifyAdmins(u);
      return;
    }
    const text = (msg.text || msg.caption || "").trim();
    // photos: kept for the next video
    const fileId = msg.photo ? msg.photo[msg.photo.length - 1].file_id : (msg.document && /^image\//.test(msg.document.mime_type || "") ? msg.document.file_id : null);
    if (fileId) {
      if (now() - u.files_at > 900) u.files = [];
      u.files = [...u.files, fileId].slice(-5); u.files_at = now(); await store.put(u);
      if (!text) return say(chat, `📷 Got ${u.files.length} photo(s). Now send the idea or script - the video can upload ${u.files.length > 1 ? "them" : "it"}.`);
    }
    if (!text) return;

    const m = text.match(/^\/(\w+)(?:@\w+)?\s*([\s\S]*)$/);
    if (m) {
      const cmd = "/" + m[1].toLowerCase(), arg = m[2].trim();
      if (["/approve", "/block", "/limit", "/members", "/stats"].includes(cmd)) return u.role === "admin" ? adminCommand(u, chat, cmd, arg) : null;
      if (cmd === "/start" || cmd === "/menu") return isPrivate ? showMain(u, chat, cmd === "/start" ? `Welcome ${esc(u.name)}! 👋\n${quotaLine(u)}\nSend an <b>idea</b> or a <b>script</b>, or tune the look with the buttons.` : undefined) : say(chat, "Open a private chat with me to use the menu 🙂");
      if (cmd === "/help") return say(chat, HELP);
      if (cmd === "/status") return say(chat, `${summary(u)}\n${quotaLine(u)}${u.active_until > now() ? "\n⏳ A video is being made." : ""}`);
      if (cmd === "/cancel") { u.state = ""; await store.put(u); return say(chat, "Cancelled.", mainKeyboard()); }
      if (cmd === "/video") return arg ? startJob(u, chat, thread, arg, u.files) : say(chat, "Usage: <code>/video your idea or script</code>");
      return;
    }
    if (!isPrivate) return;                                   // in groups only /video starts a video (no accidental jobs)

    if (u.state === "await:type") {
      u.settings.video_type = /^(clear|none|reset)$/i.test(text) ? "" : text.slice(0, 400);
      await showMain(u, chat, u.settings.video_type ? `✅ Video type saved:\n<i>${esc(u.settings.video_type)}</i>\nIt stays active until you change it.` : "Video type cleared.");
      return;
    }
    if (u.state === "await:idea") u.state = "";
    if (text === BTN.help) return say(chat, HELP);
    if (text === BTN.status) return say(chat, `${summary(u)}\n${quotaLine(u)}${u.active_until > now() ? "\n⏳ A video is being made." : ""}`);
    if (text === BTN.newVideo) { u.state = "await:idea"; await store.put(u); return say(chat, "Send your <b>idea</b> in plain words (or a full script). You can attach photos first.", { reply_markup: { remove_keyboard: true } }); }
    const menuOf = { [BTN.template]: "template", [BTN.voice]: "voice", [BTN.formats]: "formats", [BTN.captions]: "captions", [BTN.frame]: "frame", [BTN.type]: "type", [BTN.extras]: "extras" };
    if (menuOf[text]) return showMenu(u, chat, menuOf[text]);
    if (u.state.startsWith("menu:") && (await handleMenuText(u, chat, text))) return;
    if (u.state.startsWith("menu:")) { await showMain(u, chat); }
    if (text.length < 6) return say(chat, "That's a bit short. Send an idea like “show how to remove a photo background for free”.");
    return startJob(u, chat, thread, text, u.files);
  }

  async function onCallback(cb) {
    const from = cb.from;
    await tg("answerCallbackQuery", { callback_query_id: cb.id }).catch(() => {});
    if (!admins.includes(from.id)) return;
    const [kind, id] = (cb.data || "").split(":");
    if (kind !== "ap" && kind !== "bl") return;
    const m = await setStatus(Number(id), kind === "ap" ? "approved" : "blocked");
    if (!m) return;
    if (kind === "ap") await say(m.id, "✅ You are approved! Send /start to open the menu.").catch(() => {});
    await tg("editMessageText", { chat_id: cb.message.chat.id, message_id: cb.message.message_id, text: `${kind === "ap" ? "✅ Approved" : "⛔ Blocked"}: ${m.name} (${m.id})` }).catch(() => {});
  }

  return {
    async handle(update) {
      if (update.message) return onMessage(update.message);
      if (update.callback_query) return onCallback(update.callback_query);
    },
    async done(uid) { const u = await store.get(Number(uid)); if (u) { u.active_until = 0; await store.put(u); } },
  };
}

// ---------------------------------------------------------------------------------------------------------------
// Cloudflare entry
// ---------------------------------------------------------------------------------------------------------------
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const tg = async (method, params) => {
      const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(params) });
      const d = await r.json();
      if (!d.ok) throw new Error(`Telegram ${method}: ${d.description}`);
      return d.result;
    };
    const github = async (payload) => {
      const enc = await encryptPayload(payload, env.PAYLOAD_KEY);
      const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/${env.WORKFLOW_FILE || "make-video.yml"}/dispatches`, {
        method: "POST",
        headers: { Authorization: `Bearer ${env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "videobot-worker", "content-type": "application/json" },
        body: JSON.stringify({ ref: env.GITHUB_REF || "main", inputs: { payload: enc } }),
      });
      if (r.status !== 204) throw new Error(`GitHub answered ${r.status}`);
    };
    const bot = createBot({ env, store: d1Store(env.DB), tg, github });

    if (url.pathname === "/telegram" && request.method === "POST") {
      if (request.headers.get("x-telegram-bot-api-secret-token") !== env.WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
      const update = await request.json();
      ctx.waitUntil(bot.handle(update).catch((e) => console.log("handler error", String(e).slice(0, 200))));
      return new Response("ok");
    }
    if (url.pathname === "/done" && request.method === "POST") {
      if (request.headers.get("x-done-secret") !== env.DONE_SECRET) return new Response("forbidden", { status: 403 });
      const { uid } = await request.json();
      await bot.done(uid);
      return new Response("ok");
    }
    if (url.pathname === "/setup" && url.searchParams.get("key") === env.SETUP_KEY && env.SETUP_KEY) {
      await tg("setWebhook", { url: `${url.origin}/telegram`, secret_token: env.WEBHOOK_SECRET, allowed_updates: ["message", "callback_query"], drop_pending_updates: true });
      await tg("setMyCommands", { commands: [{ command: "menu", description: "Open the menu" }, { command: "status", description: "My settings and daily quota" }, { command: "video", description: "Make a video from an idea or script" }, { command: "help", description: "How it works" }] });
      return new Response("webhook and commands set");
    }
    return new Response("videobot is running");
  },
};
