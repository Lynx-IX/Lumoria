# Look timelines: plan

Status: being built on the branch `claude/look-timelines` (worktree `.claude/worktrees/look-timelines`), tried with
a test copy before anything lands on main.
- Step 1 (engine) done: `timeline.py` (lane values, sections, Playhead, cleaning), looks save / load / export their
  `timeline`, `lookcheck` cleans it, the App starts it when a look comes on and applies value lanes each frame after
  the waves (a slider with a lane skips its wave). Tests: `tests/test_timeline.py`. No editor yet: a timeline only
  comes from a look file.

## The idea in one paragraph

Each look can have a **timeline**, measured in bars on the tempo clock. It holds **lanes**: one per slider you choose,
each a line of **points** joined by **segments** (ramp, ease, or hold-then-jump). Three markers split it into an
**intro** (plays once when the look comes on), a **loop** (repeats while the look stays on) and an **outro** (plays
when the look is leaving). Take and auto-play hand over through the outro: the old look's outro runs while the next
look's intro starts. A look with no timeline behaves exactly as today.

## Decisions already made

- **Per look**, not one timeline for the whole set.
- **Bars** on the tempo clock by default (beats as the grid); seconds as an option for non-musical use.
- **Intro / loop / outro markers.** No markers: the whole timeline loops.
- A lane drives either a slider's **value**, or its wave's / music response's **depth (From-To range)** - never both
  at once - and the card shows which one is in control.
- The **crossfader stays fully manual**: moving it by hand ignores outro timing. Take and auto-play use the outro.

## What stays, changes and goes (from the cross-reference)

| Today | With timelines |
|---|---|
| Tiles, Cue, Take, previous / next | Stay: they choose *which* look plays. |
| Launch quantize (now / beat / bar / 4 / 8 / 16) | Stays: decides when an outro begins and where the next look lands. |
| Per-look transition (Dissolve, Grow, Cut, Wipe, Flash, Morph) and its length | Stays: becomes the overlap between one look's outro and the next look's intro. |
| Random auto-play | Stays; respects intros and outros. |
| Waves, music response, Rhythmic / Flow / Swell | Stay: the moment-to-moment movement. Lanes can shape their depth over a song. |
| The wave **Intro** shape (From -> To once, then a wave) | Stays (quick, per slider). The editor offers "turn into a lane" for it. |
| Effect fade-ins (Settings > Transitions) | Stay: adding / removing single effects is separate. |
| A look's custom **Stay** time (Transition popup) | Becomes **"loop N times"** for a look with a loop; looks without a timeline keep Stay. |
| Auto-play **"every N"** on the playlist bar | Only the default for looks without a timeline. Moves off the bar into auto-play's settings (the bar already crowds when narrow). |
| The **Transition... popup** | Becomes the *Transition* tab of a **look editor** (with a *Timeline* tab), opened from the tile's menu. |
| Tile badges | Also show a timeline mark; while playing, the section and loop count (e.g. "loop 3/4"). |
| **Removed** | Nothing outright: the cleanup comes from the merges above. |

## How it plays

Time inside a look is counted in beats from the moment the look came on (`start_beat`, on the tempo clock's phase),
so it follows tempo changes and Take / launch quantize land on the same grid.

- **Intro** `[0, loop_start)`: once.
- **Loop** `[loop_start, loop_end)`: repeats. Position = `loop_start + (t - loop_start) % loop_len`. A loop counter
  goes up each pass (for "loop N times" and the tile badge).
- **Outro** `[loop_end, end)`: only when leaving.

**Leaving** (Take, auto-play, a MIDI "go to outro" pad, or clicking another tile):
1. Each look has an *On leave* setting: **finish the loop pass, then outro** (smooth, default) or **jump to the
   outro** (tight).
2. The outro is placed so it **ends on the launch boundary** when launch quantize is on (bar / phrase); with *now* it
   just starts.
3. The next look's crossfade starts so that it overlaps the outro by the look's transition time (at most the outro's
   length). The old look keeps running its outro while fading out - the crossfade machinery already runs the outgoing
   look (`Pipeline.outgoing`), so its timeline just keeps advancing there.
4. No outro: today's behaviour (transition at the launch moment).

**Auto-play**: a look with a loop stays for *loop N times* (per look, default from auto-play's "every"), then leaves as
above. Without a timeline: today's hold time.

**Lanes each frame** (in `App.automate`'s place in the frame, after waves are worked out):
- *Value lane*: sets the slider's value (the same path MIDI and waves use), so the card's slider moves with it.
- *Depth lane*: scales the slider's wave / music response range (From-To) around its middle by the lane's value.
- A slider with a value lane has its wave paused while the lane holds it; MIDI on that slider takes over until the
  next point (like grabbing a fader with automation in a DAW), shown on the card.

## The editor

Opened from a tile's ▾ menu > *Timeline...* (and the look editor's tab); in the Custom layout it can also be its own
panel. Wide and short, docked above the playlist in Classic.

- **Ruler** in bars and beats, with the three markers (intro / loop / outro) dragged along it; the sections tinted.
- **Lanes**, one per row: name (effect > slider), the lane drawn as points and segments, a solo/mute dot, and a
  value / depth switch. Add a lane: *+ Lane* (pick effect and slider), or from a slider's automate menu ("Add to the
  look's timeline").
- **Points**: click to add, drag to move (snaps to the grid; Shift = free), right-click to delete or set the segment
  after it: *Ramp*, *Ease*, *Hold then jump*. Box-select and drag several. Ctrl+C / V within a lane.
- **Playhead** moving while the look plays; which section and loop pass it's in.
- **Length** and **grid** (1/4 beat .. 1 bar), zoom with Ctrl+wheel, scroll with the wheel.
- Undo through the app's existing undo (a timeline edit is a chain change).
- Everything respects the theme tokens and UI size like the rest of the interface.

## Saving

A look's timeline lives with the look (`presets/<look>.json`), so importing / exporting a look carries it:

```json
"timeline": {
  "unit": "bars", "length": 16, "grid": 0.25,
  "intro_end": 4, "loop_end": 12, "on_leave": "finish", "loops": 4,
  "lanes": [
    {"effect": "kaleido", "key": "amt", "mode": "value",
     "points": [[0, 0.2, "ease"], [4, 0.8, "ramp"], [12, 0.8, "hold"], [16, 0.0, null]]}
  ]
}
```

Lanes refer to effects by id (and copy number), like *Affects: Chosen* does. `lookcheck.clean_look` gets the matching
checks (types, ranges, sorted points, at most N lanes / points), so a damaged or hand-edited file can't break loading.
A look without `timeline` loads as today.

## Steps (each one usable and tested before the next)

1. **Engine**: timeline data on a look (load, save, `lookcheck`), the playback clock (sections, loop count), value
   lanes applied each frame. Tests with simulated time: positions, loop wrap, tempo change mid-loop.
2. **Handover**: On leave, outro placed against launch quantize, overlap with the transition, auto-play's "loop N
   times". Tests for each launch setting and for no-outro looks.
3. **Editor, basic**: ruler, markers, lanes, add / move / delete points, segment types, playhead.
4. **Merge the popups**: the look editor with Transition + Timeline tabs; Stay -> loop N times; "every" moves off the
   playlist bar.
5. **Depth lanes** and the card showing who's in control; MIDI takeover.
6. **Polish**: box-select, copy / paste, "turn wave Intro into a lane", tile badges, MIDI pads (go to outro, next
   loop pass), README.

Each step: all tests, the self-test, a throwaway-data screenshot run, and a test copy for you before merging.

## Open questions (can be decided along the way)

- Should a look's timeline restart when it's re-fired while already playing, or carry on?
- Random auto-play: play intros / outros, or only the loop?
- Should lanes on a group's effects be allowed (yes, technically easy) and on group settings (opacity, size)?
