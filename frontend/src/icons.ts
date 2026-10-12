// Inline SVG icons: one stroke style (1.6px, round caps), drawn on a 20px grid.

const PATHS: Record<string, string> = {
  pin: '<path d="M10 18s5.5-5.2 5.5-9.5a5.5 5.5 0 0 0-11 0C4.5 12.8 10 18 10 18Z"/><circle cx="10" cy="8.5" r="2"/>',
  alert: '<circle cx="10" cy="10" r="7.5"/><path d="M10 6v4.5M10 13.5v.01"/>',
  info: '<circle cx="10" cy="10" r="7.5"/><path d="M10 9v5M10 6.5v.01"/>',
  moon: '<path d="M15.5 12.5A6.5 6.5 0 0 1 7.5 4.5a6.5 6.5 0 1 0 8 8Z"/>',
  back: '<path d="M16 10H5M9 5.5 4.5 10 9 14.5"/>',
  chevron: '<path d="m7.5 5 5 5-5 5"/>',
}

export function icon(name: keyof typeof PATHS | string): string {
  return `<svg class="icon" viewBox="0 0 20 20" aria-hidden="true">${PATHS[name] ?? ''}</svg>`
}

/**
 * Today's sun path from sunrise (left) to sunset (right). t = share of daylight gone (0..1),
 * or null when the sun is down. Elapsed path is solid, the rest dashed.
 */
export function sunArcSvg(t: number | null, riseText: string, setText: string): string {
  const cx = 140, cy = 100, rx = 116, ry = 78
  const left = `${cx - rx} ${cy}`
  const right = `${cx + rx} ${cy}`
  let elapsed = ''
  let sun = ''
  if (t !== null) {
    const a = Math.PI * (1 - Math.min(1, Math.max(0, t)))
    const x = (cx + rx * Math.cos(a)).toFixed(1)
    const y = (cy - ry * Math.sin(a)).toFixed(1)
    elapsed = `<path class="arc-done" d="M${left} A${rx} ${ry} 0 0 1 ${x} ${y}"/>`
    sun = `<circle class="sun-halo" cx="${x}" cy="${y}" r="13"/><circle class="sun" cx="${x}" cy="${y}" r="6"/>`
  }
  return `
    <svg class="sun-arc" viewBox="0 0 280 128" aria-hidden="true">
      <path class="arc-todo" d="M${left} A${rx} ${ry} 0 0 1 ${right}"/>
      ${elapsed}
      <line class="horizon" x1="8" y1="${cy}" x2="272" y2="${cy}"/>
      <circle class="arc-end" cx="${cx - rx}" cy="${cy}" r="3"/>
      <circle class="arc-end" cx="${cx + rx}" cy="${cy}" r="3"/>
      ${sun}
      <text class="arc-label" x="${cx - rx}" y="122" text-anchor="middle">${riseText}</text>
      <text class="arc-label" x="${cx + rx}" y="122" text-anchor="middle">${setText}</text>
    </svg>`
}

/** A small compass: N tick fixed, needle rotated to the bearing (0 = north, clockwise). */
export function compassSvg(bearing: number, direction: string): string {
  const ticks = [90, 180, 270]
    .map((d) => `<line x1="32" y1="5" x2="32" y2="9" transform="rotate(${d} 32 32)"/>`)
    .join('')
  return `
    <svg class="compass" viewBox="0 0 64 64" role="img" aria-label="Compass pointing ${direction}">
      <circle cx="32" cy="32" r="28" class="compass-ring"/>
      <g class="compass-ticks">${ticks}</g>
      <text x="32" y="14.5" class="compass-n" text-anchor="middle">N</text>
      <g class="compass-needle" style="--bearing:${bearing}deg">
        <path d="M32 18 36.5 32h-9Z" class="needle-head"/>
        <path d="M27.5 32h9L32 45Z" class="needle-tail"/>
      </g>
      <circle cx="32" cy="32" r="2.5" class="compass-hub"/>
    </svg>`
}
