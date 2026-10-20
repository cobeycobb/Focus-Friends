# Focus Friends

A little study companion who keeps you company. All buddies currently use the Kawaii voice.

- **character**: choose Lumi, Yui, Yuzu, Miku, Soyo, Kano, Sakia, Momo, Kokona, Suzuka, Yume, Demon Girl, Butterfly Girl, Fighter Girl, or Megumi using the animated character gallery in Tools → Focus Friends Settings → General → Choose character. Confirm a selection to try its moods in Preview; save settings with OK to keep it.
- **pet_name**: your buddy's name (default "Yuzu").
- **mood_neutral_at**: cards/day where mood moves from Sleepy to Focused (default 50).
- **mood_happy_at**: cards/day where mood moves from tier 3 to tier 4 (default 100). Tier names use the Kawaii set.
- **mood_excited_at**: cards/day where mood moves from tier 4 to tier 5 (default 200).
- **sprite_size**: how big the buddy renders in the deck browser, in pixels (default 170, range 60–300). *Home screen* tab.
- **mini_size**: how big the buddy is on cards, in pixels (default 180, range 100–400). *Reviews → Buddy During Review* section. The new size appears on your next card.
- **show_during_review**: buddy in the corner during reviews (default true).
- **focus_seconds**: how many seconds you have to recall each card before the buddy looks worried (default 10, range 1–600). Recommended: 10. Purely cosmetic — it never changes Anki's rating or scheduling.
- **show_focus_timer**: show the recall timer at all (default true). Turn it off and the countdown never starts, so you are never punished for a slow recall and your buddy can never become sad from a timeout. Switching it off also clears any penalty already in progress — they go back to normal straight away.
- **recovery_reviews**: how many completed reviews before the buddy is okay again after a timeout (default 5, range 1–100). Recommended: 5. `1` is the quickest recovery, higher keeps them sad for longer.
- **recovery_timeout_behavior**: choose what another timeout does during recovery: `reset` (default) starts the full recovery count again; `hold` keeps the remaining count steady. In both modes the first timeout starts recovery, and a timed-out card does not consume a recovery review.
- **counter_style**: how the text counter looks (used when `recovery_display` is `text`) — `solid` (plain dark chip, default), `transparent` (see-through), `simple` (plain text, no background), or `kawaii` (pink lozenge with hearts).
- **show_recovery_counter**: show recovery hearts or a text counter under the buddy (default true). Hearts stay full when they are okay and refill as recovery reviews are completed. Turning this off hides the display.
- **color_theme**: matching colors for the timer, speech bubbles, recovery display, and home mood bar: `sakura` (default), `lavender`, `mint`, `sky`, or `amber`. Choose in the **Appearance** tab.
- **timer_style**: `pulse` (**Pulse Bar**, default; a short capsule with a health bar and right-side countdown), `glass` (translucent with a soft blur), `ring` (circular countdown), `kawaii` (pastel pill), or `tab` (**Floating Tab**, a very slim bar with a separate countdown tab). Older `minimal` and `classic` values migrate to `pulse` and `tab`.
- **timer_size**: timer size from 60–180% (default 100). Scales the panel, numbers, bars, and circular ring together while preserving its saved screen position. Set in **Appearance** and see the result immediately in the live preview.
- **timer_opacity**: Glass background opacity from 0–100% (default 38). The opacity slider leaves the numbers readable. Other timer styles use their own backgrounds.
- **recovery_display**: `hearts` (default), `hearts_text`, or `text`. Five hearts show recovery progress proportionally; with five recovery reviews, each completed review fills one heart. Other recovery lengths use partial hearts. Hover for the exact reviews remaining.
- **timer_position**: `last` (**Same as last time**, default) remembers a separate dragged position for each review deck across cards and Anki restarts. A deck without its own position falls back to the last saved general position; otherwise the timer starts at top center. Other choices are `top`, `top_left`, `top_right`, and `bottom`. Double-click resets the current deck's saved location. Fixed presets do not erase deck positions. Resizing keeps the timer within the window.
- **timer_pos_xy**: internal legacy/general fallback `[left, top]` coordinates. New drags are also stored by deck in `timer_pos_by_deck`.
- **timer_pos_by_deck**: internal map from deck ID to `[left, top]` timer coordinates, used by `timer_position: last`.
- **show_chatter**: master toggle for optional rating messages (default true). Timeout and recovery messages still appear when those events happen, and the session greeting appears once. No bubble appears when revealing an answer. Controls are on the **Message Bubbles** tab.
- **show_rating_messages**: occasionally react to Again, Hard, Good, and Easy, according to `chatter_percent` (default true).
- **bubble_font_size**: text size inside speech bubbles (default 12, range 8–28). The bubble widens as the text grows so longer lines still fit.
- **custom_messages_enabled**: include your custom message lines alongside the built-in Kawaii lines (default true). Turning this off keeps your saved lines but stops using them.
- **custom_messages**: lists of your own plain-text lines by event: `greeting`, `encouragement` (Again), `hard`, `review` (Good / Easy), `timeout`, `recovery`, `strict` (Hardcore), and `dialogue` (home screen). Add one line per entry in the **Message Bubbles** tab; each category supports up to 30 lines of 240 characters each.
- **mini_pos_xy**: internal legacy/general fallback `[left, top]` coordinates for the buddy. New drags are also stored by deck in `mini_pos_by_deck`.
- **mini_pos_by_deck**: internal map from deck ID to `[left, top]` buddy coordinates, used by `mini_position: last`.
- **chatter_percent**: chance for each enabled optional rating message. **Rarely**, **Sometimes**, and **Often** mean 5%, 30%, and 50% per eligible event. Rating reactions appear after you rate. No message appears when revealing an answer. Optional messages are limited to one per card and skip the following card after appearing. Timeout and recovery messages bypass that spacing and always appear for their events.
- **mini_position**: where they start each review — `last` (Same as last time, **default**), `right` (bottom-right), `center` (bottom-center), or `middle` (center of screen). In `last` mode, their position is remembered for the deck you opened and restored next session. Cards from its subdecks share that position throughout the session; a filtered deck has its own position. Double-click resets the current deck's saved spot. Fixed presets leave saved deck positions intact.
- **show_mood_bar**: show the mood label, progress bar, and today's card count (default true).
- **show_dialogue**: speech bubble + spell-cast text under it (default true).
- **run_across**: at the top two mood tiers they run back and forth across the deck browser as one character, turning to face each way (default true). *Home screen* tab.
- **side_panel**: dock them to the right side of the deck list on wide windows (≥1220px); below the decks otherwise (default true). *Home screen* tab.

## Animation map
- **neutral**: idle (6–7 frames depending on the character, weighted ~64% of idle picks), waiting (6f), review (6f)
- **sad**: failed (8f)
- **happy**: jumping (5f), waving (4f)
- **actions**: running (6f), look_a (8f), look_b (8f)
- **run**: running_right (8f), running_left (8f), running (6f)

Mood ladder → pool:
Drained (0 cards) = neutral · Sleepy = sad · Focused = neutral ·
Tier 4 = neutral + actions (+run-across) · tier 5 = happy (+run-across).

## In-review buddy (180px default size; saved position per deck)
Idle = calm `idle` most of the time, with occasional `waiting`, `review`,
`look_a`/`look_b` (looks play twice, then back to idle — never loop). No random thinking chatter is started. On every answer, 2s reaction:
- **Good / Easy** → the same shared praise pool; **Hard** → its own reaction pool
- **Again** → calm `idle` (+ a gentle rating message, never a disappointed pose)

Each question also starts the recall timer (`focus_seconds`). If it expires the buddy
looks sad and stays that way for `recovery_reviews` completed reviews, counting down in
the hearts (or optional text counter). Click them 5x fast → jumping. Press-and-hold 3s → waiting pose.

## Message style
Kawaii is the only available message style. No bubble appears when revealing an answer.

## Hardcore mode
Off by default, on its own **HARDCORE MODE** tab.
- **hardcore_mode**: turn the miss-streak mode on (default false).
- **hardcore_misses**: how many Again answers in a row put them out of sorts (default 3, range 1–100). Recommended: 3. Any correct answer resets the run to zero.
- **hardcore_recovery**: how many reviews they then stay sad for (default 5, range 1–100). Recommended: 5. They celebrate on the review that clears it.

They can be sad from a hardcore streak and a recall timeout at the same time; the larger counter
decides whether the box reads "Recover in N reviews" or "Okay again in N reviews". Turning the
mode off forgives any penalty it started; turning the recall timer off does not.

## Settings tabs
- **General** — character, name, and animation preview.
- **Home screen** — everything on the deck browser: mood thresholds, buddy size,
  mood bar, dialogue bubble, run-across, side docking.
- **Reviews** — everything during review: recall timer, recovery reviews, buddy size,
  position, and visibility.
- **Message Bubbles** — optional rating reactions, frequency, bubble text size, and custom messages. Good and Easy share the same praise pool; revealing an answer does not show a bubble.
- **Appearance** — shared color theme, timer style, Glass opacity, and hearts / text recovery display.
- **HARDCORE MODE** — miss-streak mode: on/off, misses in a row, reviews to recover.
- **About** — add-on overview and clickable animation source credits.

## Session greeting
The first card of every review session makes them wave with a greeting line from the active
Kawaii greeting — e.g. "Hello! Let's do this!". The wave and bubble hold until you answer that
card (no timeout), and the greeting appears even with **Show review messages** switched off. It
fires once per session and is re-armed when you return to the home screen or review ends.

## Preview playground
Settings → **General** has six preview choices: **Idle**, **Thinking**, **Sad**, **Jumping**, **Waving**, **Run left**, and **Run right**. Each plays the selected character's actual animation strip. The deck-browser character starts at 170 px by default; change its size in Home screen settings. These use the pending character selection, so Cancel leaves your saved settings unchanged.

## Recovering from a timeout
When the recall timer runs out they look sad until you've finished `recovery_reviews`
reviews. On the review that brings them back to okay they celebrate — a jumping or waving
pose held a beat longer than normal, with a "Hooray!"-style bubble from the Kawaii pack. Turning off **Show review messages** keeps the animation but drops the bubble.

## Undo and Redo
Undoing a review restores the buddy’s review count, correct count, streaks, timeout recovery, and hardcore recovery to their values before that rating. Redo restores the changes. Undoing a note edit leaves those counters alone. This follows reviews made in the current Anki collection session; switching profiles clears the in-memory history.

## Animation variety
Every included character has a separate jump and wave. Fighter Girl, Suzuka, and Soyo use their extra look-direction rows; Fighter Girl and Soyo have seven-frame idle strips. Celebrations alternate between available actions rather than repeating the same action on consecutive reactions. Look sequences use the selected character’s actual frame count.

## Kawaii message pack
The Kawaii pack contains home-screen dialogue, greetings, Again/Hard/Good/Easy ratings, strict-mode events, timeout, and recovery lines. Good and Easy share their praise pool. See [kawaii-messages.md](kawaii-messages.md) for the complete wording. No bubble appears when revealing an answer; rating reactions appear right after the rating. Message selection avoids the previous three lines in each event pool. Thinking itself never triggers random chatter.

## Live appearance preview
The **Appearance** tab previews pending timer style, size, opacity, theme, selected character, speech bubbles, and recovery display. **Replay** restarts a sample countdown and the bubble entrance; **Time’s up** previews expiration. The **Reviews left** slider demonstrates heart recovery. Switch between light and dark backgrounds with the checkbox. These use sample progress and never change study counters, penalties, or the reviewer’s timer. OK saves the pending settings; Cancel discards them. The preview countdown stops when you leave the tab or close settings.

Speech bubbles enter with a 180 ms fade and a subtle 4 px rise. This affects the bubble content, so its screen position remains stable. The entrance animation is skipped when the system requests reduced motion.

## Using Settings while reviewing
The card timer pauses while Settings is open and resumes its remaining time when you return to the same question. New appearance choices are applied to the buddy when Settings closes. Tabs are grouped into sections with explanations and can scroll on smaller displays. The live preview uses native Qt drawing and sample progress. It does not open an extra browser renderer. Closing Settings stops all preview timers and releases the dialog. Timer opacity, sizes, themes, animation, and recovery are illustrated; browser blur and font rendering can differ slightly in the actual reviewer.

Recovery hearts are now about 10% smaller; their progress and review counts are unchanged.
