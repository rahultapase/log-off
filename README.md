# Log Off

Pick a mood, how long you have, your energy and whether you're alone. Log Off finds one real
place near you, works out when to leave so you're back before sunset, and asks a local Gemma 4
model (via Ollama) for a short thing to do there. Then it shows one quiet screen until you're back.

Started on 12 Oct 2026 for the DEV Hacktoberfest Open-Source AI Challenge, Week 1 (Touch Grass),
inside the challenge window. Work in progress.

## Security note

The server binds to `127.0.0.1` only and has no login. That's deliberate: it's a single-user
laptop app. Don't expose it on a network as-is. The only data that leaves the machine is your
location rounded to 3 decimal places (about 100 m), sent to OpenStreetMap (Nominatim, Overpass,
map API) and Open-Meteo. Gemma runs locally through Ollama and never sees coordinates.

License: MIT.
