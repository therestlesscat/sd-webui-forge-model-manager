# `model_manager/api/`: the HTTP endpoints

Lessons from the routes. What each endpoint module is for is in
`model_manager/AGENTS.md`, under `api/`.

## Learned the hard way

### The code

- **A check in one route and an act in another race.** Sync images' Start
  read the folder list, then registered its job; a Remove landing between
  the two passed its "running" check and took the folder off the list, and
  the sync wrote 54 generations under it that no Remove could reach. Found
  live on 7880, not by a suite; one lock now spans both routes, and a check
  sends the Remove from inside Start.
- **`api/settings._kind` read a Radio as a choice and a Dropdown as text**,
  so the settings window drew Sync images' level as a box taking any word.
  It reads both.
- **Neo's server refuses a request line past 64 KB.**
  `GET /model-manager/sync/estimate` carried the scoped sync's paths in its
  address: 65,370 bytes were answered, 65,408 got `400 Invalid HTTP request
  received.`, plain text the page's `response.json()` threw on, so the cost
  never came for more than 493 of one library's 1,872 files (#355). A list
  a route needs goes in a POST body, or is not sent at all: the route finds
  it from what was picked. The test client has no such limit, so no suite
  sees it. The original Forge's limit is not measured.

## Kept elsewhere, and true here too

Rules whose main code is in another folder, which this folder's code must
keep as well:

- `javascript/AGENTS.md`, "Nothing in the WebUI versions".
