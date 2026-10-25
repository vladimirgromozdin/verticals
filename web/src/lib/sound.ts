// The whole sound layer: eight assets, one `play` function, no dependency, and one switch: ⌥M or Alt+M turns the
// sounds off and on, remembered on this device. `docs/E2E.md` S-74 and `RESEARCH.md` §3 name the eight;
// `tools/make_sounds.py` generates them into `web/public/sounds/` (Vite copies `public/` into `dist/` verbatim, so the
// URLs below are the shipped ones, hash-free and stable).
//
// House rules this file is written against:
//
//  * Sound is never the only cue. Every event below already has a visible one — the checkbox
//    fills, the card leaves the column, the row disappears, the children fold away. Nothing here
//    carries information that is not on screen without it, so the sounds turned off lose nothing.
//  * A rejected `play()` is not an error. Browsers refuse audio before a user gesture, and a
//    refusal arrives as a rejected promise; an unhandled one is an uncaught exception, which
//    S-75 asserts there are zero of. Every call site is behind a real gesture, so this should
//    never fire — it is handled anyway, because "should never" is not a guarantee.
//  * No `prefers-reduced-motion` gate, deliberately. Reduced *motion* is a statement about
//    animation, not about audio, and the `ui` suite runs its whole browser context with
//    `reduced_motion="reduce"` — gating on it would mean the shipped product plays nothing for
//    the caller most likely to be running it.

import { ref } from '../reactivity'
import { say } from './fieldNotice'

export const SOUND_EVENTS = [
  'checked',
  'unchecked',
  'goal_dragging',
  'goal_deleted',
  'add_goal_clicked',
  'vertical_expanded',
  'vertical_collapsed',
  'all_completed',
] as const

export type SoundEvent = (typeof SOUND_EVENTS)[number]

/** Absolute, because the app serves real paths (`/h/2026-08-08`) and a relative asset URL would
 *  resolve against whichever one is open. */
const SOUND_URL: Record<SoundEvent, string> = {
  checked: '/sounds/checked.wav',
  unchecked: '/sounds/unchecked.wav',
  goal_dragging: '/sounds/goal_dragging.wav',
  goal_deleted: '/sounds/goal_deleted.wav',
  add_goal_clicked: '/sounds/add_goal_clicked.wav',
  vertical_expanded: '/sounds/vertical_expanded.wav',
  vertical_collapsed: '/sounds/vertical_collapsed.wav',
  all_completed: '/sounds/all_completed.wav',
}

/** Quiet by construction. The assets are already generated at 0.2 of full scale
 *  (`tools/make_sounds.py`); this is the second, independent step down, and it is the one knob a
 *  future settings surface would turn if the owner ever asks for one. */
const VOLUME = 0.5

/** One element per asset, built once and replayed. A fresh `new Audio()` per play would re-fetch
 *  on a cold cache and leak an element per gesture; one element per sound is eight objects for
 *  the lifetime of the page. */
const elements = new Map<SoundEvent, HTMLAudioElement>()

function element(name: SoundEvent): HTMLAudioElement | null {
  if (typeof Audio === 'undefined') return null
  let el = elements.get(name)
  if (!el) {
    el = new Audio(SOUND_URL[name])
    el.preload = 'auto'
    el.volume = VOLUME
    elements.set(name, el)
  }
  return el
}

/** Fetch all eight at load, so the first gesture of the session plays without waiting on a
 *  round-trip. Eight requests of a few kilobytes each, once — and no `play()` is issued here, so
 *  a page nobody has touched stays silent (S-74 asserts exactly that). */
export function preloadSounds(): void {
  for (const name of SOUND_EVENTS) element(name)
}

/** Play one. Never throws, never rejects, never returns a promise a caller has to handle: a
 *  sound that will not play is not a failure the UI should react to. */
export function playSound(name: SoundEvent): void {
  if (soundsOff.value) return
  const el = element(name)
  if (!el) return
  try {
    el.currentTime = 0
    const started = el.play()
    if (started && typeof started.catch === 'function') started.catch(() => {})
  } catch {
    // Same reasoning as the rejected promise above: audio is an accompaniment. Swallowed here
    // rather than logged, because a console error is an assertion failure in three suites and
    // the user-visible consequence of this branch is silence.
  }
}

const OFF_KEY = 'verticals:sounds-off'

function storedOff(): boolean {
  try { return localStorage.getItem(OFF_KEY) === '1' } catch { return false }
}

export const soundsOff = ref(storedOff())

/** ⌥M or Alt+M, read by the key's place so it works on any layout. */
export function isSoundToggle(event: KeyboardEvent): boolean {
  return event.altKey && !event.metaKey && !event.ctrlKey && !event.shiftKey && event.code === 'KeyM'
}

/** Turns the sounds off or on, and says so in the field: nothing else on screen shows it. */
export function toggleSounds(): void {
  soundsOff.value = !soundsOff.value
  try { localStorage.setItem(OFF_KEY, soundsOff.value ? '1' : '0') } catch { /* optional */ }
  say([{ text: soundsOff.value ? 'Sounds off' : 'Sounds on' }], { label: soundsOff.value ? 'Turn on' : 'Turn off', run: toggleSounds })
}

preloadSounds()
