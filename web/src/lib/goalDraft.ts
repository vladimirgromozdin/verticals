/** Keep the complete draft in notes when it exceeds the title's character limit. */
export function wordsToGoal(text: string): { title: string; body?: string } {
  const line = text.replace(/\s+/g, ' ').trim()
  const characters = Array.from(line)
  if (characters.length <= 250) return { title: line }
  const cut = characters.slice(0, 249).join('')
  const at = cut.lastIndexOf(' ')
  return { title: `${(at > 150 ? cut.slice(0, at) : cut).trimEnd()}…`, body: text.trim() }
}
