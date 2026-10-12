import '@fontsource-variable/schibsted-grotesk'
import '@fontsource-variable/martian-mono'
import './styles/tokens.css'
import './styles/base.css'
import './styles/layout.css'
import './styles/app.css'
import './styles/ask.css'

import { api, ApiError, type Area, type Prefs, type Prepared, type Ticket } from './api'
import { compassSvg, icon, sunArcSvg } from './icons'

// ---------- tiny helpers ----------

const $ = <T extends HTMLElement>(sel: string) => document.querySelector<T>(sel)!

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
}

function fmtTime(d: Date): string {
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

// `?at=19:30` plans as if it were that time today (demo and after-dark checks).
const mockAt = new URLSearchParams(location.search).get('at')

// ---------- state ----------

const AREA_KEY = 'logoff.area'
const GONE_KEY = 'logoff.gone'

interface Gone {
  backBy: string // ISO
  backByText: string
  leaveText: string | null // set when the plan is for later (after sunrise)
  place: string
  walk: string
  title: string
}

let area: Area | null = loadJSON<Area>(AREA_KEY)
let ticket: Ticket | null = null
let lastPrefs: Prefs | null = null
let excluded: string[] = []
let busy = false
let goneTimer: number | undefined

function loadJSON<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

// ---------- elements ----------

const viewAsk = $<HTMLElement>('#view-ask')
const viewResult = $<HTMLElement>('#view-result')
const resultBody = $<HTMLDivElement>('#result-body')
const viewGone = $<HTMLElement>('#view-gone')
const shell = $<HTMLDivElement>('#shell')
const form = $<HTMLFormElement>('#ask-form')
const areaInput = $<HTMLInputElement>('#area-input')
const locStatus = $<HTMLParagraphElement>('#loc-status')
const formError = $<HTMLParagraphElement>('#form-error')
const findBtn = $<HTMLButtonElement>('#find')
const useLocBtn = $<HTMLButtonElement>('#use-location')
const setAreaBtn = $<HTMLButtonElement>('#set-area')
const modelStatus = $<HTMLParagraphElement>('#model-status')
const daylight = $<HTMLElement>('#daylight')
const daylightArc = $<HTMLDivElement>('#daylight-arc')
const daylightLeft = $<HTMLParagraphElement>('#daylight-left')
const daylightMeta = $<HTMLParagraphElement>('#daylight-meta')

// ---------- daylight panel (real sunrise/sunset for the chosen area) ----------

let daylightToken = 0

function duration(ms: number): string {
  const mins = Math.max(0, Math.round(ms / 60_000))
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return h ? `${h} h ${m} min` : `${m} min`
}

async function loadDaylight(): Promise<Prepared | null> {
  if (!area) {
    daylight.hidden = true
    return null
  }
  const token = ++daylightToken
  try {
    const p = await api.prepare(area, mockAt)
    if (token === daylightToken) renderDaylight(p)
    return p
  } catch {
    if (token === daylightToken) daylight.hidden = true
    return null
  }
}

function renderDaylight(p: Prepared) {
  if (!p.now || !p.sunrise || !p.sunset || !p.sunrise_text || !p.sunset_text) {
    daylight.hidden = true
    return
  }
  const now = Date.parse(p.now)
  const rise = Date.parse(p.sunrise)
  const set = Date.parse(p.sunset)
  const t = (now - rise) / (set - rise)
  const up = t >= 0 && t <= 1
  daylightArc.innerHTML = sunArcSvg(up ? t : null, p.sunrise_text, p.sunset_text)
  if (up) {
    daylightLeft.innerHTML = `<span class="dur">${duration(set - now)}</span> of daylight left`
  } else if (t < 0) {
    daylightLeft.innerHTML = `Dark until <span class="dur">${esc(p.sunrise_text)}</span>`
  } else {
    daylightLeft.innerHTML = `Sun's down. Light again at <span class="dur">${esc(p.sunrise_tomorrow_text ?? '')}</span>`
  }
  const lines = [p.weather ? `Now: ${esc(p.weather)}` : '']
  if (p.places !== null && area) lines.push(`${p.places} places mapped within 2 km of ${esc(area.label)}`)
  daylightMeta.innerHTML = lines.filter(Boolean).join('<br />')
  daylight.hidden = false
}

// ---------- model status ----------

async function checkHealth() {
  const text = modelStatus.querySelector('.model-text')!
  try {
    const h = await api.health()
    modelStatus.dataset.state = h.ok ? 'ok' : 'warn'
    text.textContent = h.ok ? `${prettyModel(h.model)} on this computer` : 'Gemma is off: built-in activities'
    modelStatus.title = h.message
  } catch {
    modelStatus.dataset.state = 'warn'
    text.textContent = 'Server not answering'
  }
}

function prettyModel(m: string): string {
  const [base, tag = ''] = m.split(':')
  const n = base.replace(/^gemma/, '')
  return /^\d+$/.test(n) ? `Gemma ${n} ${tag.toUpperCase()}`.trim() : m
}

// ---------- location ----------

function showArea(a: Area | null, note = '') {
  locStatus.dataset.state = a ? 'ok' : ''
  locStatus.innerHTML = a
    ? `${icon('pin')}<span>Planning from <strong>${esc(a.label)}</strong>${note ? `. ${esc(note)}` : ''}</span>`
    : ''
  if (a) areaInput.placeholder = 'or type a different area'
}

function setArea(a: Area, note = '') {
  area = a
  excluded = []
  localStorage.setItem(AREA_KEY, JSON.stringify(a))
  showArea(a, note)
  void loadDaylight()
}

function locError(msg: string) {
  locStatus.dataset.state = 'error'
  locStatus.innerHTML = `${icon('alert')}<span>${esc(msg)}</span>`
}

useLocBtn.addEventListener('click', () => {
  if (!('geolocation' in navigator)) {
    locError("This browser can't share a location. Type an area instead.")
    areaInput.focus()
    return
  }
  useLocBtn.disabled = true
  useLocBtn.setAttribute('aria-busy', 'true')
  locStatus.dataset.state = ''
  locStatus.textContent = 'Asking the browser for your location...'
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      try {
        const a = await api.locate({ lat: pos.coords.latitude, lon: pos.coords.longitude })
        setArea(a, 'Rounded to about 100 m')
        areaInput.value = ''
      } catch (e) {
        locError(e instanceof ApiError ? e.message : 'Could not name that location.')
      } finally {
        useLocBtn.disabled = false
        useLocBtn.removeAttribute('aria-busy')
      }
    },
    (err) => {
      useLocBtn.disabled = false
      useLocBtn.removeAttribute('aria-busy')
      locError(
        err.code === err.PERMISSION_DENIED
          ? 'Location is blocked for this page. Type an area instead.'
          : "Couldn't get a location fix. Type an area instead.",
      )
      areaInput.focus()
    },
    { enableHighAccuracy: false, timeout: 15000, maximumAge: 10 * 60 * 1000 },
  )
})

async function lookUpTypedArea(): Promise<boolean> {
  const q = areaInput.value.trim()
  if (!q) return !!area
  setAreaBtn.disabled = true
  locStatus.dataset.state = ''
  locStatus.textContent = `Looking up "${q}"...`
  try {
    setArea(await api.locate({ query: q }))
    areaInput.value = ''
    return true
  } catch (e) {
    locError(e instanceof ApiError ? e.message : 'Could not look that up.')
    areaInput.focus()
    return false
  } finally {
    setAreaBtn.disabled = false
  }
}

setAreaBtn.addEventListener('click', () => void lookUpTypedArea())
areaInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault()
    void lookUpTypedArea()
  }
})

// ---------- ask -> result ----------

function readPrefs(): Prefs {
  const data = new FormData(form)
  return {
    mood: data.get('mood') as Prefs['mood'],
    minutes: Number(data.get('minutes')) as Prefs['minutes'],
    energy: data.get('energy') as Prefs['energy'],
    company: data.get('company') as Prefs['company'],
  }
}

form.addEventListener('submit', async (e) => {
  e.preventDefault()
  if (busy) return
  formError.textContent = ''
  if (!(await lookUpTypedArea()) || !area) {
    formError.textContent = 'Pick a starting point first: use your location or type an area.'
    if (!areaInput.value) useLocBtn.focus()
    return
  }
  lastPrefs = readPrefs()
  excluded = []
  void runPlan()
})

type StepState = 'wait' | 'run' | 'done' | 'fail'

const STEPS = ['places', 'sun', 'gemma'] as const

function loadingMarkup(): string {
  const rows = [
    ['places', 'Finding parks near you'],
    ['sun', "Checking today's sunset"],
    ['gemma', 'Asking Gemma for something to do'],
  ]
  return `
    <div class="loading" aria-live="polite">
      <ol class="steps-progress">
        ${rows
          .map(
            ([id, label]) => `
          <li data-step="${id}" data-state="wait">
            <span class="mark" aria-hidden="true"></span>
            <span class="what">${label}</span>
            <span class="fact"></span>
          </li>`,
          )
          .join('')}
      </ol>
      <div class="ticket ticket-skeleton" aria-hidden="true">
        <div class="ticket-main"><i></i><i></i><i></i><i></i></div>
        <div class="ticket-stub"><i></i><i></i></div>
      </div>
    </div>`
}

function step(id: (typeof STEPS)[number], state: StepState, fact = '') {
  const li = resultBody.querySelector<HTMLLIElement>(`[data-step="${id}"]`)
  if (!li) return
  li.dataset.state = state
  li.querySelector('.fact')!.textContent = fact
}

function show(view: 'ask' | 'result') {
  viewAsk.hidden = view !== 'ask'
  viewResult.hidden = view !== 'result'
}

async function runPlan() {
  if (!area || !lastPrefs) return
  busy = true
  findBtn.disabled = true
  show('result')
  resultBody.innerHTML = loadingMarkup()
  resultBody.focus?.()
  step('places', 'run')

  try {
    const prep = await api.prepare(area, mockAt)
    renderDaylight(prep)
    if (prep.places_error) {
      step('places', 'fail', 'Map data unavailable')
    } else {
      step('places', 'done', `${prep.places} on OpenStreetMap`)
    }
    step('sun', 'run')
    step('sun', prep.weather_error ? 'fail' : 'done', prep.sunset_text ? `Sunset ${prep.sunset_text}` : 'No weather data')
    step('gemma', 'run')
    ticket = await api.plan(area, lastPrefs, excluded, mockAt)
    step('gemma', 'done', ticket.source === 'gemma' ? 'Done' : 'Used a built-in activity')
    renderTicket(ticket)
  } catch (e) {
    renderError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')
  } finally {
    busy = false
    findBtn.disabled = false
  }
}

function renderError(msg: string) {
  resultBody.innerHTML = `
    <div class="notice" role="alert">
      ${icon('alert')}
      <div>
        <p class="notice-title">No ticket this time</p>
        <p>${esc(msg)}</p>
      </div>
    </div>
    <div class="actions actions-error">
      <button type="button" class="btn btn-secondary" data-act="retry">Try again</button>
      <button type="button" class="btn btn-primary" data-act="change">${icon('back')}Change my answers</button>
    </div>`
  resultBody.querySelector<HTMLButtonElement>('[data-act="change"]')!.focus()
}

function renderTicket(t: Ticket) {
  const later = t.mode === 'later'
  const leaveLabel = later ? 'Leave at' : 'Leave by'
  const notes = t.notes.filter(Boolean)
  const kind = t.place.named ? t.place.kind_word : `${t.place.kind_word} with no name on the map`
  const placeKind = `${kind.charAt(0).toUpperCase()}${kind.slice(1)} in`
  resultBody.innerHTML = `
    <article class="ticket" data-mode="${t.mode}" aria-labelledby="ticket-place">
      <div class="ticket-main">
        <p class="ticket-title">${esc(t.title)}</p>
        <h3 class="ticket-place" id="ticket-place">${esc(t.place.label)}</h3>
        <p class="ticket-kind">${esc(placeKind)} ${esc(t.area_label)}</p>
        <ol class="ticket-steps">
          ${t.steps.map((s) => `<li>${esc(s)}</li>`).join('')}
        </ol>
        <details class="why">
          <summary>${icon('chevron')}Why this place</summary>
          <ul>
            ${t.why.map((w) => `<li>${esc(w)}</li>`).join('')}
          </ul>
        </details>
      </div>
      <div class="ticket-stub">
        <div class="walk">
          ${compassSvg(t.place.bearing_deg, t.place.direction)}
          <p><span class="num">${t.place.walk_min} min</span><span class="dir">walk ${esc(t.place.direction)}</span></p>
        </div>
        <dl class="times">
          <div><dt>${leaveLabel}</dt><dd class="num">${esc(t.leave_by_text)}</dd></div>
          <div><dt>Back by</dt><dd class="num num-back">${esc(t.back_by_text)}</dd></div>
        </dl>
        <p class="weather">Now: ${esc(t.weather)}</p>
      </div>
    </article>
    ${
      notes.length
        ? `<div class="ticket-notes" data-mode="${t.mode}">${icon(later ? 'moon' : 'info')}<p>${notes.map(esc).join(' ')}</p></div>`
        : ''
    }
    <div class="actions">
      <button type="button" class="btn btn-quiet" data-act="change">${icon('back')}Change my answers</button>
      <button type="button" class="btn btn-secondary" data-act="another">Another place</button>
      <button type="button" class="btn btn-primary btn-lg" data-act="logoff">${later ? 'Log off until then' : 'Log off'}</button>
    </div>
    <p class="source-line">${
      t.source === 'gemma'
        ? `Activity written by ${esc(t.model ?? 'Gemma')} on this computer, checked against the map before you saw it.`
        : 'Activity from a built-in template (Gemma was off or its answers failed the checks).'
    }</p>`
  resultBody.querySelector<HTMLButtonElement>('[data-act="logoff"]')!.focus({ preventScroll: true })
}

resultBody.addEventListener('click', (e) => {
  const btn = (e.target as HTMLElement).closest<HTMLButtonElement>('button[data-act]')
  if (!btn || busy) return
  const act = btn.dataset.act
  if (act === 'change') {
    show('ask')
    findBtn.focus()
  } else if (act === 'retry') {
    void runPlan()
  } else if (act === 'another' && ticket) {
    excluded.push(ticket.place.osm_id)
    void runPlan()
  } else if (act === 'logoff' && ticket) {
    logOff(ticket)
  }
})

// ---------- logged off ----------

function logOff(t: Ticket) {
  const later = t.mode === 'later'
  let backBy = new Date(t.back_by)
  if (!later && !mockAt) {
    // Back-by from the moment you actually leave, never earlier than the ticket said.
    const outingMin = 2 * t.place.walk_min + t.duration_min
    const fromNow = new Date(Date.now() + outingMin * 60_000)
    if (fromNow > backBy) backBy = fromNow
  }
  const gone: Gone = {
    backBy: backBy.toISOString(),
    backByText: later || mockAt ? t.back_by_text : fmtTime(backBy),
    leaveText: later ? t.leave_by_text : null,
    place: t.place.label,
    walk: `${t.place.walk_min} min walk ${t.place.direction}`,
    title: t.title,
  }
  localStorage.setItem(GONE_KEY, JSON.stringify(gone))
  showGone(gone)
}

function showGone(g: Gone) {
  const leaving = g.leaveText !== null
  viewGone.innerHTML = `
    <div class="gone-inner">
      <h1 id="gone-title" class="gone-title">${leaving ? 'Rest now.' : 'Gone outside.'}</h1>
      <p class="gone-time">
        ${leaving ? `Leave at <span class="num">${esc(g.leaveText!)}</span>. ` : ''}
        Back by <span class="num num-back">${esc(g.backByText)}</span>
      </p>
      <p class="gone-place">${esc(g.place)}<span>${esc(g.walk)}</span></p>
      <p class="gone-hint" id="gone-hint">Leave the laptop here. This screen will wait.</p>
      <button type="button" class="btn btn-ghost-light" id="im-back">I'm back</button>
    </div>`
  shell.hidden = true
  shell.setAttribute('inert', '')
  viewGone.hidden = false
  document.title = leaving ? 'Log Off: rest now' : `Log Off: back by ${g.backByText}`
  viewGone.focus({ preventScroll: true })
  viewGone.querySelector<HTMLButtonElement>('#im-back')!.addEventListener('click', comeBack)
  tickGone(g)
}

function tickGone(g: Gone) {
  window.clearInterval(goneTimer)
  const update = () => {
    if (Date.now() >= new Date(g.backBy).getTime()) {
      const hint = viewGone.querySelector('#gone-hint')
      if (hint) hint.textContent = "Time's up. Welcome back, whenever you are."
      window.clearInterval(goneTimer)
    }
  }
  update()
  goneTimer = window.setInterval(update, 30_000)
}

function comeBack() {
  window.clearInterval(goneTimer)
  localStorage.removeItem(GONE_KEY)
  viewGone.hidden = true
  viewGone.innerHTML = ''
  shell.hidden = false
  shell.removeAttribute('inert')
  document.title = 'Log Off'
  ticket = null
  excluded = []
  show('ask')
  findBtn.focus()
}

// ---------- boot ----------

showArea(area)
void checkHealth()
void loadDaylight()
const gone = loadJSON<Gone>(GONE_KEY)
if (gone) showGone(gone)
