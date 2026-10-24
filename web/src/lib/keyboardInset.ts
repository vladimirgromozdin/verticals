/* The phone's keyboard covers the bottom of the page without making the page shorter: only the visual viewport shrinks,
   so the circle, fixed to the bottom, stays under the keyboard. This puts the keyboard's height on <html> as
   `--vt-keyboard`, and the circle and everything that stands on it rise above the keyboard (`--vt-field-bottom`,
   circleField.css). A computer has no such keyboard and the value stays 0. */

/** How much of the window's bottom the keyboard covers, in CSS px. A pinch zoom also shrinks the visual viewport, so
 *  while the page is zoomed nothing rises. `offsetTop` is how far the browser has panned the page to show the field. */
export function keyboardInset(innerHeight: number, height: number, offsetTop: number, scale: number): number {
  if (Math.abs(scale - 1) > 0.01) return 0
  return Math.max(0, Math.round(innerHeight - height - offsetTop))
}

export function startKeyboardInset(): void {
  const viewport = window.visualViewport
  if (!viewport) return
  let last = -1
  const update = () => {
    const inset = keyboardInset(window.innerHeight, viewport.height, viewport.offsetTop, viewport.scale)
    if (inset === last) return
    last = inset
    document.documentElement.style.setProperty('--vt-keyboard', `${inset}px`)
  }
  viewport.addEventListener('resize', update)
  viewport.addEventListener('scroll', update)
  update()
}
