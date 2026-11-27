# Free 24/7 video bot: Telegram + Cloudflare + GitHub (about 25 minutes, no credit card)

## How it works

```
Telegram group / chat
   │  (menus, approvals, quotas, saved settings: instant)
   ▼
Cloudflare Worker  (worker/worker.js, free, always on)  ── D1 database: members, roles, settings, daily counters
   │  one encrypted "start" message per video
   ▼
GitHub Actions  (.github/workflows/make-video.yml)
   a brand-new Ubuntu machine for EVERY video:
   Xvfb virtual screen → real Chrome + real mouse/keyboard → Gemini writes the script (idea mode)
   → record → deep voice → edit → send the finished video to Telegram
   → the machine is destroyed.  Nothing is kept.
```

Why this and not something else (checked on 26 Nov 2026):

| Option | Verdict |
|---|---|
| **GitHub Actions + Cloudflare Workers** | Free, no card, a clean machine per video (the strongest "everything is removed" guarantee). **Used here.** |
| Oracle Cloud Always Free VM | Needs a card; the free ARM allowance was cut to 2 cores / 12 GB in June 2026; idle VMs can be reclaimed. Works with the included `Dockerfile` if you already have one. |
| Hugging Face Spaces | Docker Spaces now need a paid plan. |
| Your own PC | Works (Windows, as before), but not 24/7 and members would use your real machine. |

**Public repo, private content.** A public repository gets unlimited free runner minutes (4 CPU / 16 GB). Public repos show
workflow logs to everyone, so (1) the Worker sends each job **AES-256 encrypted**, (2) the job prints **nothing** to the
log unless you turn `DEBUG_LOGS` on, (3) all keys are GitHub/Cloudflare secrets. The finished video goes only to Telegram.
If you prefer a private repo, it works the same but is limited to 2,000 free minutes per month (about 300-400 videos).

## 0. First: rotate the keys you pasted

`env.example.env` in the zip you sent contained what looks like a **real Gemini API key**. Anything you put in a zip or a chat
can leak. Create a new key at https://aistudio.google.com/apikey and delete the old one. Do the same for a Telegram token if it was
ever in a file. In `.env` the model must be an **ID** (`gemini-4-hydrogen`), not the display name `Gemini 4 Hydrogen`
(the new code normalises it, but use the ID anyway).

## 1. Telegram bot

1. In Telegram open **@BotFather** → `/newbot` → copy the **token**.
2. Open **@userinfobot** → copy **your numeric id** (you are the admin).
3. Add the bot to your group. Members only need to send `/video <idea>` in the group, or talk to the bot privately
   (private chat has the full button menu).

## 2. GitHub

1. Create a **public** repository (for example `video-bot`) and upload this whole folder (do **not** upload a `.env`).
2. Repo → *Settings → Secrets and variables → Actions → New repository secret*:

| Secret | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the BotFather token |
| `GEMINI_API_KEY` | your **new** Gemini key |
| `PAYLOAD_KEY` | run `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"` and paste the output (keep a copy: the Worker needs the same value) |
| `DONE_SECRET` | any long random text (the Worker needs the same value) |
| `DONE_URL` | `https://videobot.YOUR-SUBDOMAIN.workers.dev/done` (you get the real address in step 3) |

3. Create the token the Worker uses to start jobs: *GitHub → Settings → Developer settings → Fine-grained tokens → Generate*:
   only this repository, permission **Actions: Read and write**. Copy it.
4. Optional repository *variables*: `GEMINI_MODEL`, `BLOCKED_HOSTS` (comma separated sites to never open), `DEBUG_LOGS=1` (only while testing).

## 3. Cloudflare Worker (free account, no card)

```bash
cd worker
npm install -g wrangler
wrangler login
wrangler d1 create videobot              # copy the database_id it prints into wrangler.toml
wrangler d1 execute videobot --remote --file=schema.sql
# edit wrangler.toml: GITHUB_REPO, ADMIN_IDS (your id), DEFAULT_LIMIT, MAX_ACTIVE
wrangler secret put TELEGRAM_BOT_TOKEN
wrangler secret put WEBHOOK_SECRET       # any long random text
wrangler secret put DONE_SECRET          # SAME value as the GitHub secret
wrangler secret put GITHUB_TOKEN         # the fine-grained token from step 2.3
wrangler secret put PAYLOAD_KEY          # SAME value as the GitHub secret
wrangler secret put SETUP_KEY            # any random text, used once below
wrangler deploy                          # prints https://videobot.<you>.workers.dev
```

Then open `https://videobot.<you>.workers.dev/setup?key=<SETUP_KEY>` once. It connects Telegram to the Worker. Put the Worker address
(`.../done`) into the `DONE_URL` GitHub secret. Send `/start` to your bot: you should see the menu.

Free-plan limits that matter: Worker 100,000 requests/day, D1 100,000 row-writes/day (every menu tap is one write), GitHub public
repo unlimited minutes. Cloudflare KV was **not** used because its free plan allows only 1,000 writes/day.

## 4. Using it

* New people message the bot and wait. You get a message with **Approve / Block** buttons. `/members`, `/limit <id> <n>`, `/stats`,
  `/block <id>` are admin commands. Members get `DEFAULT_LIMIT` videos per UTC day; admins are unlimited; one video per person
  at a time; `MAX_ACTIVE` videos at once for everybody.
* **Buttons** (they appear where the phone keyboard is): 🎨 Template (10 looks), 🗣 Voice (male/female + depth), 📐 Formats
  (tap several), 💬 Captions, 🧩 Frame, 📦 Extras, **✍️ Video type**, 📊 My status.
* **✍️ Video type**: pick a preset or describe it in simple words ("calm tutorials for grandparents, slow and clear, about 50 s").
  It is saved and used for **every** video until you change or clear it.
* Send an **idea in plain words** → Gemini writes the script first (using your video type), then the robot records. Or send a full
  script (see `PROMPT_TEMPLATE.txt`). Send photos first if the video should upload one.
* In a script you can add `Template: neon`, `Depth: 3`, `Outputs: vertical, instagram`, `Captions: box`, `Frame: tablet`.
  They apply to that one video and override the saved buttons.

New robot actions (in scripts, or written by Gemini):

| Tag | What the robot does |
|---|---|
| `[type Message \| hello] [press enter]` | real typing into any chat/text box |
| `[upload Upload photo]` | real click on the upload button/drop-zone; the chosen photo is handed to the file chooser (your photo, or a built-in sample) |
| `[type Email \| {email}]` `[type Password \| {password}]` | a throw-away mail.tm address and a generated password, typed with the real keyboard |
| `[verify]` / `[type Code \| {code}]` | waits for the confirmation e-mail, opens its link / types its one-time code |

Use sign-up demos only on services that allow disposable e-mail. Many sites block data-centre IPs or ask for a captcha;
the robot does not try to bypass captchas, phone checks or payments.

## 5. What is removed, and what protects the group

* Every video runs on a fresh GitHub machine, in a fresh Chrome profile, on its own virtual screen; the machine is destroyed after the
  job. Photos are re-encoded and live only inside that machine. The member's text is encrypted in transit and not logged.
* Before a browser opens, `avx_safety.py` rejects scripts that point at localhost, private/internal addresses, `file:` /
  `javascript:` links, credentials in the URL, or text that looks like a key/token/card number; and it caps length, scenes and actions.
  A 25-minute hard limit stops stuck jobs. Add more blocked sites with `BLOCKED_HOSTS`.
* Members only get the bot's menu; they never see your keys. The Gemini key exists only as a GitHub secret.
* GitHub's rules still apply to you as the repository owner: this is personal, moderate use. If many people start using it
  heavily, expect throttling, or move the same `Dockerfile` to a small paid server.

## 6. Running on your own computer / a server (optional)

```bash
pip install -r requirements.txt
python autovideo.py templates sheet.png          # preview all 10 templates
python autovideo.py job payload.json             # one video in a throw-away sandbox (Linux: starts its own Xvfb)
xvfb-run -a -s "-screen 0 1920x1080x24" python autovideo.py make    # the classic commands also work on Linux
```

Windows keeps working as before (`check`, `make`, `queue`, `bot`).

## 7. What was and was not tested

Tested here with a real browser, a real virtual screen, real mouse/keyboard events and ffmpeg: Linux port, typing in a chat box,
photo upload, sign-up + verification flow (with a mocked mailbox), all 10 templates, one-line subtitles (fuzz test: 400 scripts × 4 styles),
voice depth (measured), the full job in the sandbox (and that it left nothing behind), the Telegram menus/roles/quotas (mocked
Telegram), payload encryption between JavaScript and Python, and the Gemini client (mocked: 3 response shapes, fallback, rate-limit).

**Not tested, because my environment has no internet:** the real Telegram API, a real GitHub Actions run, a real Cloudflare deploy,
the live Gemini API, the live edge-tts voice and the live mail.tm service. Expect to fix small things on the first real run:
set `DEBUG_LOGS=1`, send one test idea, and read the Actions log.
I measured the voice but could not listen to it: try the four **Voice** levels and tell me which one you like.
