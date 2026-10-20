# Focus Friends

A desktop-pet study companion for [Anki](https://apps.ankiweb.net/). A small animated
character sits on the deck browser ("home screen") and, during reviews, appears in a
corner of the card window. Their mood, animation, and dialogue all derive from how many
cards you've reviewed today, so they visibly brighten as you work and dim if you stall.

It is **entirely cosmetic**. It never modifies scheduling, card data, ratings, or the
collection database. It reads the collection for review history and writes only its own
state file.

Fifteen characters ship: **Yuzu** (default; sailor outfit), **Lumi**, **Yui**, **Miku**, **Soyo**, **Kano**, **Sakia**, **Momo**, **Kokona**, **Suzuka**, **Yume**, **Demon Girl**, **Butterfly Girl**, **Fighter Girl**, and **Megumi**. Kawaii is the default personality. The player is
named via `pet_name`. Choose a character from the animated gallery in Settings → General → Choose character; the existing mood preview lets you try the selection before saving.

## Source layout

```
__init__.py      main add-on module
manifest.json    package: lumi_study_buddy, name: "Focus Friends"
config.json      defaults for a fresh install
config.md        human-readable settings reference
kawaii-messages.md complete built-in Kawaii message list
img/             bundled sprite strips for all characters
dev/             local development files; omitted from the public repo and add-on archive
user_files/      local runtime state (gitignored; never distribute)
meta.json        local Anki metadata (never distribute)
```

## Building the add-on archive

The first public release is **1.0.0**. From this folder, run `./build_release.sh 1.0.0`.
The script writes `dist/Focus_Friends-1.0.0.ankiaddon` with the add-on files at the archive
root, as AnkiWeb expects. It includes the module, manifest, default config, documentation,
and runtime `img/` assets. It excludes `dev/`, local Anki metadata, review state, Python
caches, and generated files. If a `LICENSE` file is present, it is included.

The manifest keeps the package key `lumi_study_buddy` so existing installations retain
their add-on identity; the visible add-on name is Focus Friends. The development folder
name does not control the installed package key.

For GitHub, publish this project folder as its own repository. The parent `anki add ons`
directory contains other projects and local changes, so it should not be published as the
Focus Friends repository.

Sprites are horizontal PNG strips, one row of frames. Rendering is CSS: the strip is
inlined as a base64 data URI in a `background-image`, and `background-position` is
animated with `steps(n)` keyframes. **No PyQt/QPainter sprite rendering** — everything is
HTML in Anki's existing web views.

All included characters expose the same 11 animation keys:
`idle, waiting, review, failed, jumping, waving, running, running_right, running_left, look_a, look_b`.

## Two surfaces

### 1. Deck browser ("home screen")

Injected via `gui_hooks.deck_browser_will_render_content` by appending HTML to
`content.stats`.

**Mood ladder**, driven purely by *today's review count* at Anki's day cutoff:

| Tier | Cards today | Animation pool |
|---|---|---|
| 1 | 0 | idle, waiting, review, look_a, look_b |
| 2 | 1-50 | failed |
| 3 | 51-100 | idle, waiting, review, look_a, look_b |
| 4 | 101-200 | neutral pool + running |
| 5 | 200+ | jumping, waving |

The Kawaii voice supplies the labels for each mood tier; the numbers remain stable.

Thresholds are user-configurable. Within the neutral pool, `idle` is weighted 7 vs 1 for
the others, so they stand calmly ~64% of the time. A JS token-based rotator swaps poses
every 5-10 s; `look_a`/`look_b` play through their cycle twice then revert to idle rather
than looping.

Optional, individually toggleable: a **dialogue bubble + spell sub-line**, a **mood progress
bar with today's card count**, a **run-across animation** at the top two tiers, and
**fixed right-side docking** at >=1220 px window width (below the deck list on narrower
windows).

At the top two tiers (with `run_across` on) it is **one character, not two**: they hold a
pose, sprint one way, turns, sprints back, settles on a different pose and goes again. The
sprite swaps to `running_left` / `running_right` to match the direction of travel, so they always
face where they are going.

### 2. During reviews

Rendered by injecting HTML into `mw.reviewer.web` via `.eval()`.

- **Session greeting**: on the first card of every review session they wave and say a
  greeting line, e.g. "Hello! Let's do this!". It **holds until you answer that first card**
  (no timeout), and ignores the text-bubble toggle — the greeting is part of the hello, not
  chatter. Fires once per session; re-armed when the deck browser renders or review ends.
- **Idle rotation** while thinking, same weighted pool as above.
- **Answer reactions**: Good/Hard/Easy -> `jumping`, `waving`, or a run-left-then-back-right
  sequence; Again -> calm `idle` with no disappointed pose.
- **Recall timer**: a draggable countdown box (see below). Can be switched off entirely.
- **Draggable**: grab them anywhere on screen. The spot is remembered and they reappear there
  next session (**Same as last time**, the default), with a separate position for each review
  deck. Double-click resets that deck's saved spot. Choosing a fixed corner in settings leaves
  the remembered positions intact.

## Recall timer and the recovery mechanic

The deck-browser character starts at **170 px** by default; the Home screen size setting changes this.

At the start of a deck, the first countdown waits with **Click to begin** so you can place
the buddy and timer. After you start it, each new question starts a countdown
(`focus_seconds`, default 10). If it expires:

1. They take the `failed` (sad) pose immediately.
2. `timed_out_current` is set — this is the card that timed out, and it does **not**
   consume a recovery review.
3. Every subsequent completed review decrements `sad_reviews_remaining` (from
   `recovery_reviews`, default 5).
4. On the review where the counter hits zero, they **celebrate**: a `jumping`/`waving` pose
   held 3000 ms instead of the usual 2000, plus a "Hooray!"-style bubble from the active
   message style. This takes priority over the normal reaction, including when the final
   answer is Again.
5. Five recovery hearts refill below them; the default five-review recovery fills one heart per completed recovery review. Other recovery lengths use proportional fills. Appearance settings offers hearts, hearts with remaining reviews, or the existing text counter. The display can be hidden independently of the sad pose.

Revealing the answer pauses the countdown where it is and dims the timer to 50% opacity. The next question starts a fresh countdown at full opacity.

**Timer specifics**: position presets are top-center / top-left / top-right / bottom-center.
It is draggable with double-click snap-back, using its **own** drag globals
(`_lumiTimerDrag`) so it never interferes with the buddy's drag state. The countdown bar is
proportional to the configured duration, and the "running low" amber threshold scales to
the last ~30%.

The timer is purely cosmetic and never affects Anki's scheduling.

**Turning it off**: `show_focus_timer` (default on) is a checkbox on the *Reviews* tab. With
it off the countdown never starts, the box never appears, and nothing can ever set a timeout —
so you are never punished for a slow recall. Switching it off also **forgives any penalty
already running**: the sad pose clears immediately and they go back to normal, because they
are no longer being timed.

## Text bubbles

Message pools, all driven by the active **Kawaii voice**:

| Pool | When | Count |
|---|---|---|
| `dialogue` | deck browser bubble, per mood tier | 5 tiers x 5 (Kawaii) |
| `spell` | coloured sub-line under the bubble, per mood tier | 4 non-empty lines across 5 tiers |
| `review` | shared Good / Easy praise | 28 |
| `hard` | occasional Hard reaction | 12 |
| `encouragement` | occasional Again reaction | 14 |
| `strict` | occasional Hardcore Mode reaction | 10 |
| `recovery` | the "they're okay again" celebration | 21 |
| `timeout` | the timer ran out and they became sad | 12 |
| `greeting` | the wave on entering a review session | 12 |

**Kawaii is the only active voice.** All buddies use the same message pack and mood labels.

**Frequency** applies to each enabled rating event: Rarely / Sometimes / Often mean a 5% / 30% / 50% chance per eligible event. Good and Easy share the same praise pool. No bubble appears when you reveal an answer. Optional messages are limited to one per card and skip the following card after appearing. Timeout and recovery messages always appear, even back-to-back. Recent lines in each event pool are excluded to reduce repetition.

A master `show_chatter` toggle silences optional rating bubbles. The **session greeting**, timeout message, and recovery message still speak when their events happen.

**Minimum on-screen time**: a bubble that has just appeared is not yanked away. Hiding is
deferred until it has been up for `BUBBLE_MIN_MS` (3000 ms), so hitting Next quickly no
longer makes a bubble flash and disappear. Showing a new bubble restarts the clock.
`bubble_font_size` (default 12 px, range 8-28) sets the text size; the bubble widens with it
so longer lines still fit.

## Easter eggs (deck browser only)

- 5 rapid clicks within 1500 ms -> `jumping` for 2 s.
- Press-and-hold 3 s -> `waiting` pose.

## Settings dialog

Opened from **Tools -> Focus Friends Settings…**. Seven tabs:

- **General** — character, name, plus a **preview playground** (below)
- **Home screen** — Daily Mood Goals, Home Screen Buddy Size, mood bar, dialogue, run-across, side docking
- **Reviews** — Thinking Countdown Timer, buddy size/visibility/position, hearts and recovery
- **Message Bubbles** — optional rating reactions, frequency, bubble text size, and the custom message editor. Good and Easy share praise lines; answer reveals have no bubble.
- **Appearance** — timer styles, Glass opacity, shared color theme, and recovery hearts / text.
- **HARDCORE MODE** — the miss-streak mode (below)
- **About** — a short overview and clickable animation source credits.
- The **Appearance** tab also picks the recovery-counter look (solid / transparent / plain / kawaii)

Size controls pair a slider with an editable number field and a **Reset** button.
Changing the review size reveals a note that the new size appears on the next card.

### Preview playground

On the *General* tab, the seven animation choices are **Idle**, **Thinking**, **Sad**,
**Jumping**, **Waving**, **Run left**, and **Run right**. The mood preview also offers
**Timeout** and **Recovering** examples; both use the sad animation and show recovery
progress. Each preview uses the selected character's animation. The preview uses the
pending character choice, so Cancel leaves saved settings unchanged.

## Hardcore mode

Off by default, on its own **HARDCORE MODE** tab.

- `hardcore_misses` — how many **Again answers in a row** put them out of sorts (default 3).
  Any correct answer resets the run to zero.
- `hardcore_recovery` — how many reviews they then stay sad for (default 5).

On the review that trips the threshold they drop straight into the `failed` pose and say a
line from the style's `strict` pool. They then stay sad for `hardcore_recovery` completed
reviews **whatever you answer** — you have to earn it back, not merely stop making mistakes. The
review that trips it does not also count as the first recovery review. On the review that
clears the counter they celebrate, exactly like the timeout recovery.

Turning the mode off forgives any penalty it started. Turning the *timer* off does not, since
the two are independent.

The penalties are tracked separately and can be active at once. The larger counter wins the
on-screen label, which is why it reads `Recover in N reviews` under hardcore and
`Okay again in N reviews` after a timeout. Both are governed by `show_recovery_counter`.

## Configuration and state

**Config** lives via `mw.addonManager.getConfig/writeConfig` under the add-on's own key,
merged over `DEFAULT_CONFIG` so new options get sensible values on upgrade. Any number not
matching a named dropdown band snaps to the nearest one.

**State** is `user_files/state.json`:
`reviews, correct, streak, best_streak, sad_reviews_remaining, timed_out_current,
consecutive_misses, hardcore_sad_remaining`, plus a `day` marker.

Day rollover uses Anki's `sched.today` (respecting the user's day cutoff), falling back to
the calendar ordinal when no collection is open. On a new day the counters are rebuilt by
backfilling from the `revlog` for the trailing day, so counts survive restarts and
multi-device sync; `gui_hooks.sync_did_finish` reconciles again after a sync. The
`sad_reviews_remaining` / `timed_out_current` penalty deliberately **carries across the day
boundary**.

## Config keys and defaults

```
character              'yuuhi_sailor'          pet_name               'Yuzu'
talking_style          'kawaii' (fixed)        chatter_percent        30
mood_neutral_at        50                      mood_happy_at          100
mood_excited_at        200                     focus_seconds          10
show_focus_timer       True                    recovery_reviews       5
counter_style          'solid'                 timer_position         'last'
sprite_size            170                     mini_size              180
mini_position          'last'                  show_during_review     True
mini_pos_xy            None                    show_chatter           True
bubble_font_size       12                      hardcore_mode          False
hardcore_misses        3                       hardcore_recovery      5
show_mood_bar          True                    show_recovery_counter  True
show_dialogue          True                    run_across             True
side_panel             True
```

## Anki hooks used

```
gui_hooks.deck_browser_will_render_content   -> deck browser companion
gui_hooks.reviewer_did_show_question        -> start recall timer, idle pose
gui_hooks.reviewer_did_show_answer          -> stop recall timer
gui_hooks.reviewer_will_end                 -> stop recall timer (guarded, optional)
gui_hooks.reviewer_did_answer_card          -> counters, reactions, recovery
gui_hooks.sync_did_finish                   -> backfill reconciliation
gui_hooks.webview_did_receive_js_message    -> remembered drag position (pycmd bridge)
```

The last three are wrapped in `getattr(..., None)` so the add-on still loads on Anki versions
that lack them.

### A note on the bridge hook

`webview_did_receive_js_message` changed shape in Anki 25.09. Older versions passed a bare
`bool` in and wanted a bare `bool` back; 25.09+ passes `(handled, result)` and unpacks a
tuple back, adding a third `context` argument. The handler detects which contract is in use
from the type of its first argument, so both work, and it never touches a message another
add-on already claimed. Getting either half of that wrong raises inside `aqt/webview.py` on
*every* message any webview sends, which looks like Anki itself crashing.

## Known gaps

- `streak` and `best_streak` are tracked in state but never displayed anywhere.
- Review positions are stored for the deck you open when **Same as last time** is selected.
  Its subdeck cards share that position, and filtered decks keep their own positions.
- All character profiles use the Kawaii message style.

## Gallery, timer placement, and review history

- **Character gallery:** animated thumbnails for every bundled character. Choose one, explore its moods in Preview, and save settings with OK. Cancel leaves the saved character unchanged.
- **Timer placement:** choose **Reviews → Timer starts at → Same as last time** to remember a separate dragged location for each deck, including across Anki restarts. The deck you opened owns the location for the whole session, even when cards come from different subdecks. A new deck uses the saved general fallback or top center. Fixed presets leave remembered deck positions intact. Double-click resets the current deck's position.
- **Repeated timeouts:** Reviews settings offers **Reset the recovery counter** (the existing behavior) or **Hold the remaining reviews steady**. A timed-out card does not advance recovery in either mode.
- **Undo and Redo:** review counts, correct counts, streaks, and both recovery counters follow the review being undone or redone. Unrelated edits do not change buddy counters. Review snapshots last for the current collection session.

## Appearance and animation variety

Settings → **Appearance** offers **Pulse Bar** (the default), **Glass**, **Ring**, **Kawaii**, and **Floating Tab** timers. Pulse Bar is a compact capsule with a health bar and countdown; Floating Tab uses a thin bar with a separate small countdown. Older Minimal and Classic settings migrate to these compact styles. Glass has a 0–100% background opacity slider (default 38%). **Sakura**, **Lavender**, **Mint**, **Sky**, and **Amber** themes coordinate the timer, bubbles, recovery hearts, text counters, and home mood bar. Timers keep their saved location when changing appearance.

The default recovery display is five hearts. They empty on a timeout, refill as recovery reviews are completed, and remain full once they recover. With another recovery length, the same five hearts fill proportionally; hovering shows the exact number of reviews left. Text-only and hearts-with-text options remain available. Both recovery modes and Undo/Redo preserve the original recovery length so progress remains accurate.

All 15 characters have jump and wave animations. Fighter Girl, Suzuka, and Soyo also use their two extra look-direction rows; Fighter Girl and Soyo have seven-frame idle animations. Consecutive celebrations choose different actions, and look sequences are timed for each character’s frame count. The developer-only local installer is in `dev/install_local.sh` and copies character strips into the existing local Anki installation.

## Kawaii messages

The active Kawaii pack uses soft phrasing and occasional emoji, with pools for greetings, encouragement, rating reactions, timeouts, and recovery. Good and Easy use the same praise pool. There are no answer-reveal bubbles, and no random chatter appears during recall.

The **Message Bubbles** tab lets you add up to 30 plain-text lines per category, one per line (240 characters per line). Categories are greetings, Again encouragement, Hard, shared Good/Easy praise, timeout, recovery, Hardcore, and home-screen dialogue. Custom lines join the built-in pool and follow the same event and frequency rules. **Restore built-in messages** clears all custom lines; turning off **Use my messages** keeps them saved but inactive.

## Live appearance preview and timer size

Settings → **Appearance** includes a native Qt live preview. Try all five timer styles, 60–180% timer size, Glass opacity, color themes, bubbles, characters, and recovery displays before saving. **Replay**, **Time’s up**, a sample recovery slider, and light/dark backgrounds let you inspect the states without affecting study progress. Cancel discards pending appearance changes; OK saves them. The preview timer is independent of the reviewer and stops when the tab closes.

Timer size scales its typography, panel, progress bar, and SVG ring together; preset and saved position coordinates remain in screen pixels. Speech bubbles use a gentle 180 ms fade and 4 px rise, applied to their contents so dragging and bubble anchoring stay stable. Reduced motion preferences disable the entrance animation.

## Clearer settings and return to reviewing

Settings are divided into labeled sections with short explanations. Every tab can scroll while OK and Cancel stay visible. New setups use 12 px bubble text, and recovery hearts are about 10% smaller.

Opening Settings pauses the card timer. Closing it restores review keyboard focus, rebuilds the buddy display, and resumes the remaining time on the same question. The Appearance preview now uses native Qt drawing instead of an extra browser renderer. It shows sample progress, stops all preview timers when Settings closes, and releases the dialog before returning to reviews. Browser blur and font rendering can differ slightly from the sample. This removes the preview browser and asynchronous JavaScript teardown as possible causes of freezes; confirmation in Anki is still needed.

## Animation previews

General settings offers seven animation choices: Idle, Thinking, Sad, Jumping, Waving, Run left, and Run right. Timeout and Recovering are mood examples that reuse the sad animation and add the recovery display. Each preview plays the selected character's animation, and pending selections are discarded with Cancel.
