// Thin client for the FastAPI backend. Errors carry the server's human sentence.

export type Mood = 'calm' | 'curious' | 'restless' | 'social'
export type Energy = 'low' | 'medium' | 'high'
export type Company = 'solo' | 'others'

export interface Prefs {
  mood: Mood
  minutes: 15 | 30 | 45 | 60
  energy: Energy
  company: Company
}

export interface Area {
  lat: number
  lon: number
  label: string
}

export interface Health {
  ok: boolean
  ollama: boolean
  model: string
  model_present: boolean
  message: string
}

export interface Prepared {
  places: number | null
  named: number | null
  places_error: string | null
  sunset_text: string | null
  sunrise_text: string | null
  sunrise_tomorrow_text: string | null
  weather: string | null
  weather_error: string | null
  now: string | null
  sunrise: string | null
  sunset: string | null
  sunrise_tomorrow: string | null
}

export interface Ticket {
  area_label: string
  place: {
    osm_id: string
    label: string
    kind: string
    kind_word: string
    named: boolean
    walk_min: number
    direction: string
    direction_short: string
    bearing_deg: number
  }
  mode: 'now' | 'after_dark' | 'later'
  now: string
  leave_by: string
  back_by: string
  leave_by_text: string
  back_by_text: string
  latest_leave_text: string | null
  sunset_text: string | null
  weather: string
  rain_pct: number | null
  notes: string[]
  title: string
  steps: string[]
  duration_min: number
  gemma_why: string | null
  why: string[]
  source: 'gemma' | 'fallback'
  model: string | null
  candidates: number
}

export class ApiError extends Error {}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError("Log Off's server isn't answering. Is it still running?")
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = body && typeof body.detail === 'string' ? body.detail : null
    throw new ApiError(detail ?? 'Something went wrong on the server. Try again.')
  }
  return body as T
}

export const api = {
  health: () => call<Health>('/api/health'),
  locate: (q: { query: string } | { lat: number; lon: number }) =>
    call<Area>('/api/locate', { method: 'POST', body: JSON.stringify(q) }),
  prepare: (a: Area, at: string | null) =>
    call<Prepared>(`/api/prepare${at ? `?at=${encodeURIComponent(at)}` : ''}`, {
      method: 'POST',
      body: JSON.stringify({ lat: a.lat, lon: a.lon }),
    }),
  plan: (a: Area, prefs: Prefs, exclude: string[], at: string | null) =>
    call<Ticket>(`/api/plan${at ? `?at=${encodeURIComponent(at)}` : ''}`, {
      method: 'POST',
      body: JSON.stringify({ lat: a.lat, lon: a.lon, label: a.label, prefs, exclude }),
    }),
}
