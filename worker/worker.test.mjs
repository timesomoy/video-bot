// node --test worker.test.mjs     (no network, no Cloudflare: the bot logic runs against in-memory fakes)
import test from "node:test";
import assert from "node:assert/strict";
import { createBot, encryptPayload, looksLikeScript, TEMPLATES } from "./worker.js";

function makeWorld(envOver = {}) {
  const db = new Map(); const sent = []; const dispatched = []; let t = 1_800_000_000;
  const store = {
    async get(id) { const u = db.get(id); return u ? structuredClone(u) : null; },
    async put(u) { const c = structuredClone(u); delete c.isNew; db.set(u.id, c); },
    async list() { return [...db.values()].map((u) => structuredClone(u)); },
    async activeCount(now) { return [...db.values()].filter((u) => u.active_until > now).length; },
  };
  const env = { ADMIN_IDS: "1", DEFAULT_LIMIT: "2", MAX_ACTIVE: "2", ...envOver };
  const bot = createBot({ env, store, tg: async (m, p) => { sent.push([m, p]); return {}; }, github: async (p) => { dispatched.push(p); }, now: () => t, rand: () => 0.5 });
  const msg = (from, text, extra = {}) => ({ message: { from: { id: from, first_name: "U" + from }, chat: { id: from, type: "private" }, text, ...extra } });
  return { bot, db, sent, dispatched, msg, tick: (s) => (t += s), last: () => sent.filter(([m]) => m === "sendMessage").at(-1)[1] };
}

test("new member waits for approval, admin approves with the inline button", async () => {
  const w = makeWorld();
  await w.bot.handle(w.msg(2, "hello"));
  assert.equal(w.db.get(2).status, "pending");
  const adminMsg = w.sent.find(([m, p]) => m === "sendMessage" && p.chat_id === 1);
  assert.ok(adminMsg, "admin was notified");
  assert.equal(adminMsg[1].reply_markup.inline_keyboard[0][0].callback_data, "ap:2");
  await w.bot.handle(w.msg(2, "make me a video about windows"));
  assert.equal(w.dispatched.length, 0, "pending members cannot start jobs");
  await w.bot.handle({ callback_query: { id: "c", from: { id: 5 }, data: "ap:2", message: { chat: { id: 1 }, message_id: 9 } } });
  assert.equal(w.db.get(2).status, "pending", "a non-admin cannot approve");
  await w.bot.handle({ callback_query: { id: "c", from: { id: 1 }, data: "ap:2", message: { chat: { id: 1 }, message_id: 9 } } });
  assert.equal(w.db.get(2).status, "approved");
});

test("reply keyboard menus: single select, multi select, video type persists", async () => {
  const w = makeWorld();
  await w.bot.handle(w.msg(1, "/start"));
  assert.ok(w.last().reply_markup.keyboard.flat().some((b) => b.text.includes("New video")));
  await w.bot.handle(w.msg(1, "🎨 Template"));
  await w.bot.handle(w.msg(1, "⚪ neon"));
  assert.equal(w.db.get(1).settings.template, "neon");
  assert.ok(w.last().reply_markup.keyboard.flat().some((b) => b.text === "🔘 neon"), "selection is shown on the keyboard");
  await w.bot.handle(w.msg(1, "⬅️ Back"));
  // multi-select formats
  await w.bot.handle(w.msg(1, "📐 Formats"));
  await w.bot.handle(w.msg(1, "✅ Vertical reel"));          // switch vertical OFF
  await w.bot.handle(w.msg(1, "⬜ Landscape"));              // switch landscape ON
  assert.deepEqual(w.db.get(1).settings.outputs.sort(), ["instagram", "landscape"]);
  await w.bot.handle(w.msg(1, "✅ Done"));
  assert.equal(w.db.get(1).state, "");
  // voice
  await w.bot.handle(w.msg(1, "🗣 Voice"));
  await w.bot.handle(w.msg(1, "⚪ Very deep"));
  await w.bot.handle(w.msg(1, "⚪ Female"));
  assert.equal(w.db.get(1).settings.depth, 3); assert.equal(w.db.get(1).settings.gender, "female");
  await w.bot.handle(w.msg(1, "⬅️ Back"));
  // video type: preset, then own words, then it is used by a job
  await w.bot.handle(w.msg(1, "✍️ Video type"));
  await w.bot.handle(w.msg(1, "⚪ Tutorial"));
  assert.match(w.db.get(1).settings.video_type, /step-by-step/);
  await w.bot.handle(w.msg(1, "✍️ Type my own"));
  await w.bot.handle(w.msg(1, "slow calm videos for grandparents"));
  assert.equal(w.db.get(1).settings.video_type, "slow calm videos for grandparents");
  await w.bot.handle(w.msg(1, "show how to remove a photo background for free"));
  const p = w.dispatched[0];
  assert.equal(p.mode, "idea");
  assert.equal(p.options.video_type, "slow calm videos for grandparents");
  assert.equal(p.options.template, "neon"); assert.equal(p.options.depth, 3); assert.equal(p.options.gender, "female");
  assert.deepEqual(p.options.outputs.sort(), ["instagram", "landscape"]);
  // the previous video type stays in effect for the NEXT video too (until changed)
  w.tick(2000); await w.bot.done(1);
  await w.bot.handle(w.msg(1, "another idea about linux distros in the browser"));
  assert.equal(w.dispatched[1].options.video_type, "slow calm videos for grandparents");
});

test("scripts are detected; quotas, one-job-at-a-time and global limit", async () => {
  assert.ok(looksLikeScript("Video: x\nOpen https://a.com || hi") && looksLikeScript("[click Go]") && !looksLikeScript("make a video about cats"));
  const w = makeWorld();
  await w.bot.handle(w.msg(2, "hi")); await w.bot.handle({ callback_query: { id: "c", from: { id: 1 }, data: "ap:2", message: { chat: { id: 1 }, message_id: 1 } } });
  await w.bot.handle(w.msg(2, "Video: Test\nOpen https://example.com || Hook line.\n|| Bye."));
  assert.equal(w.dispatched.at(-1).mode, "script");
  await w.bot.handle(w.msg(2, "a second idea right away please"));
  assert.match(w.last().text, /already have a video/);
  assert.equal(w.dispatched.length, 1);
  await w.bot.done(2);
  await w.bot.handle(w.msg(2, "second idea of the day for you"));
  await w.bot.done(2);
  await w.bot.handle(w.msg(2, "third idea should hit the daily limit"));
  assert.match(w.last().text, /used your 2 videos/);
  assert.equal(w.dispatched.length, 2);
  w.tick(86400); // next UTC day
  await w.bot.handle(w.msg(2, "next day idea works again fine"));
  assert.equal(w.dispatched.length, 3);
  // admin limit command
  await w.bot.handle(w.msg(1, "/limit 2 10")); assert.equal(w.db.get(2).lim, 10);
  // global active limit (MAX_ACTIVE=2): admin + user 2 busy -> user 3 refused
  await w.bot.handle(w.msg(3, "hi")); await w.bot.handle(w.msg(1, "/approve 3"));
  await w.bot.handle(w.msg(1, "idea from the admin about something")); // admin busy (user 2 busy too)
  await w.bot.handle(w.msg(3, "idea from third member right now"));
  assert.match(w.last().text, /machines are all busy/);
});

test("photos are kept for the next video; groups only react to /video", async () => {
  const w = makeWorld();
  await w.bot.handle(w.msg(1, "x", { text: undefined, photo: [{ file_id: "small" }, { file_id: "BIG" }] }));
  await w.bot.handle(w.msg(1, "upload my photo to the tool and show the result"));
  assert.deepEqual(w.dispatched[0].files.map((f) => f.file_id), ["BIG"]);
  const w2 = makeWorld();
  const grp = (text) => ({ message: { from: { id: 1, first_name: "A" }, chat: { id: -100, type: "supergroup" }, text } });
  await w2.bot.handle(grp("just chatting in the group"));
  assert.equal(w2.dispatched.length, 0);
  await w2.bot.handle(grp("/video show how to use a free tool"));
  assert.equal(w2.dispatched.length, 1); assert.equal(w2.dispatched[0].chat_id, -100);
});

test("blocked users are ignored; github failure does not use up the quota", async () => {
  const w = makeWorld();
  await w.bot.handle(w.msg(2, "hi")); await w.bot.handle(w.msg(1, "/block 2"));
  const n = w.sent.length; await w.bot.handle(w.msg(2, "make a video please about cats")); assert.equal(w.sent.length, n);
  const w3 = makeWorld();
  const bot = createBot({ env: { ADMIN_IDS: "1" }, store: (() => { const m = new Map(); return { get: async (i) => m.get(i) && structuredClone(m.get(i)), put: async (u) => m.set(u.id, structuredClone(u)), list: async () => [], activeCount: async () => 0 }; })(), tg: async () => ({}), github: async () => { throw new Error("GitHub answered 401"); } });
  const sent = [];
  await bot.handle({ message: { from: { id: 1, first_name: "A" }, chat: { id: 1, type: "private" }, text: "an idea long enough to run" } });
  const u = await (async () => { const m = new Map(); let st; const b2 = createBot({ env: { ADMIN_IDS: "1", DEFAULT_LIMIT: "1" }, store: st = { get: async (i) => m.get(i) && structuredClone(m.get(i)), put: async (x) => m.set(x.id, structuredClone(x)), list: async () => [], activeCount: async () => 0 }, tg: async (mm, p) => { sent.push(p); return {}; }, github: async () => { throw new Error("GitHub answered 401"); } }); await b2.handle({ message: { from: { id: 1, first_name: "A" }, chat: { id: 1, type: "private" }, text: "an idea long enough to run" } }); return m.get(1); })();
  assert.equal(u.used, 0, "a failed start must not use up the daily quota");
  assert.ok(sent.some((p) => /could not start/.test(p.text || "")));
});

test("payload encryption round-trips (decrypted in Python by avx_job)", async () => {
  const key = Buffer.alloc(32, 7).toString("base64");
  const enc = await encryptPayload({ hello: "wörld", n: 3 }, key);
  const fs = await import("node:fs"); fs.writeFileSync("/tmp/enc_payload.txt", enc);
  assert.ok(enc.length > 20);
});
