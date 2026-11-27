# autovideo (v4)

Turns scripts into REAL screen-demo videos with an AI voice-over, one after another. Windows only.

## Files
- autovideo.py : the whole pipeline. Settings are at the top of the file.
- scripts.txt  : MANY scripts, separated by a line containing only ---   (the queue reads this)
- jobs\*.txt   : optional, one script per file (the queue reads these too)
- brief.txt    : the single-video script for plan/make/all
- SCOUT_WITH_PLAYWRIGHT_MCP.txt : optional guide to let an AI agent scout sites with Playwright MCP (not needed)
- PROMPT_TEMPLATE.txt : paste into any AI (ChatGPT, Claude, Gemini...) to generate scripts in the right format for scripts.txt
- music.mp3    : optional royalty-free music bed (ducks under the voice). background.jpg : optional wallpaper.
- output\NN_title.mp4 : finished videos. output\plans\ : generated plans (safe to hand-edit before a re-run).
- output\queue_state.json / queue_log.txt : what is done/failed and why.

## Commands
- python autovideo.py check   -> 10-second self-test of the controlled environment
- python autovideo.py queue   -> make every script in scripts.txt / jobs\ one by one; finished ones are skipped on re-run
- python autovideo.py plan | make | finish | all -> single video from brief.txt (finish = resume without re-recording)
- When asked to write a plan json: follow the given prompt file exactly and output only the JSON file.

## Writing scripts (what the built-in planner understands)
One line (or sentence) = one scene. Narration is written from the line ("Open X and show Y" -> "Let's open X and show Y.").
- URL in a line -> typed into the address bar. scroll [down|up] [a bit|to the bottom] -> mouse-wheel scroll.
- click/pick/choose/select/open <name> -> click (the name is matched to the real button/link texts found on the page).
- type/search "text" in the <field> -> typing (search also presses Enter). hover over <name>. wait / pause.
- "End with a line telling people to try it free" / "Explain that ..." / "Say that ..." -> narration-only scene.
- Lines starting Video:, Tone:, Language: (Bangla), Voice: <edge-tts voice> are settings, not scenes.
- "actions || exact narration" on one line = one scene whose spoken text is exactly what follows ||. Empty left part = narration only.
- Exact control, any language: put tags in the line: [goto url] [click text] [hover text] [type field | text]
  [scroll 800] [wait 2] [press enter]. If a line has tags, ONLY the tags are used as actions.

## Outputs, voice, bot (v4)
- One recording -> OUTPUTS formats in ONE decode pass (render_video): "vertical" 1080x1920 (badges+title, rounded video window,
  word-highlight subtitles from edge-tts WordBoundary timings), "instagram" 1080x1350 (4:5, full screen, NO subtitles),
  "landscape". Each target has its own camera (camera_path with its aspect). <name>_transcript.txt is written for every video.
- Voice: resolve_voice(): script "Voice: <name|male|female>" > --male/--female (or bot /voice) > DEFAULT_GENDER. voice_profile.json
  (from `voice-lab`) holds the closest voices to the reference video; analyze_voice() is numpy-only and used for both.
- Script metadata lines: Video, Title (locks the headline), Tag, Part, Voice, Language. Actions use "actions || narration".
- PLANNER "auto": built-in planner, then the optional AI editor (ai_refine_plan: sanitises everything the model returns,
  only whitelisted actions) if AUTOVIDEO_AI_KEY is set in .env. Never make the AI mandatory.
- Telegram bot (`bot`): long polling with urllib only; ONLY TELEGRAM_ALLOWED_USERS may queue jobs; one job at a time (real
  mouse). Storage: Telegram reply + GitHub Release assets (monthly tag). Secrets only in .env.

## Why actions are verified (do not remove)
A page may not scroll or a button may not exist; the old pipeline silently did nothing and the video was static.
- Session.scroll_by() checks the real scroll position (window + the scroll container under the pointer) after the wheel:
  retry at another spot, then PageDown; if nothing moves, do_action() runs explore() (a real pointer tour of the page).
- A click/hover target that is not found becomes explore(1). Narration-only scenes also run explore(1).
- At plan time the scout (collect_page_hints) reports pages that cannot scroll and clicks that cannot be found.
- Calibration fits screen = a + b*client from positions WE sent and the page reported, and b follows devicePixelRatio, so
  display scaling and browser zoom (PAGE_ZOOM, real Ctrl+= presses) cannot break pointer accuracy. point_at() verifies landing.

## Cursor and camera (do not remove)
- ffmpeg records with draw_mouse 0. CursorLogger logs the REAL pointer (GetCursorPos + left button) ~60x/s into session.json
  ("cursor"). render_video draws a large cursor from that telemetry (pressed state, click ring), and the camera follows the
  pointer with a dead zone; every scene also gets a gentle breathing zoom (PUSH_IN). Old sessions without telemetry still render.

## Design rules (do not break)
- Planning must work with NO external AI: PLANNER = "builtin" is the default (plan_builtin). opencode is an optional upgrade
  (PLANNER = "opencode" or "auto"); if it is missing or fails, the built-in planner is used. The queue plans ALL scripts first
  (no mouse use), then records.
- Nothing is simulated: real browser window + throw-away profile, REAL mouse/keyboard (pyautogui), REAL screen recording (ffmpeg).
  Playwright (connect_over_cdp) is attached ONLY to read element positions. Never click or type through Playwright.
- Order: record first, voice after, then the voice is fitted to the video (the video is sped up/trimmed, never frozen).
- The pointer is never frozen: perform() drifts it between actions and records spare 'dwell' footage at the end of each scene.
  The edit trims that footage instead of holding a frame. Marks (move/click/type/load/wait/scroll/settle/hold/dwell/idle) are
  logged live by Session.mark() and drive the speed edit (BASE/CAP tables at the top of the file).
- Cleanup is mandatory: the browser is killed and its temp profile deleted right after each live session, also on errors.
  The raw recording in output\_work\<job> is kept ONLY until that video is finished.
- Plans/work folders are keyed by a hash of the script text, so an edited script never reuses an old plan.
- A queue job that fails is logged and skipped; the corner failsafe stops the whole queue.
- edge-tts is online and flaky: tts_one() retries, then falls back to the offline Windows voice.

## Open task: drive the real Recordly app (optional, only when asked)
Goal: use the installed Recordly (Electron, open source: github.com/webadderall/Recordly, AGPL-3.0) for capture/editing
instead of ffmpeg + the built-in edit step, only if it can be automated reliably.
1. Find the install folder and extract resources\app.asar (npx @electron/asar extract). Look for command-line flags,
   IPC handlers, how recording is started/stopped, how export is triggered.
2. Save one short test recording with a zoom and a trim as a .recordly project and inspect the file.
3. Report whether record/export can be triggered from code. Only then add a CAPTURE = "recordly" mode.
   If not possible, report why and stop. Never guess UI coordinates.

## v5 additions (Linux sandbox, templates, deep voice, Gemini, Telegram front end)
- `xinput_linux.py` real X11 mouse/keyboard (ctypes, XTEST). `autovideo.py` picks it automatically on Linux; Windows still uses pyautogui.
- `avx_templates.py` 10 reel templates + 7 device frames + ONE-LINE subtitles (`split_pages` must keep every word and fit one line; fuzz-tested).
- `avx_voice.py` voice depth 0-3: deep base voice + pitch drop (asetrate/atempo, duration unchanged) + EQ. Measure: `python avx_voice.py measure file.mp3`.
- `avx_gemini.py` Gemini client (key only in the back end) and the script writer; `avx_mail.py` mail.tm throw-away mailbox ({email} {password} {code}, [verify]).
- `avx_safety.py` checks every script before a browser opens; `avx_job.py` runs one video in a throw-away sandbox and deletes everything.
- `worker/` Cloudflare Worker (Telegram menus, roles, quotas, saved video type) -> `.github/workflows/make-video.yml` (one fresh machine per video).
- Rules unchanged: never click/type through Playwright (it only reads positions); the only Playwright call that touches input is handing a file to the native file chooser that a REAL click opened.
- Tests: `tests/run_all.sh` (offline).
