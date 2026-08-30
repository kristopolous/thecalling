# The Calling!

A text adventure you play **down the phone**, while your character moves on a map in
the browser.

Open the page, put in your phone number, and call the number it shows you. It knows
you by your caller ID, so there is nothing to read out — the call just *is* the game:
you say `go north`, `take the sword`, `attack the skeleton`, and the character on
screen moves in real time. The map also shows the ghost trails of everyone who has
played before you — how far they got, and how long it took them — so you know exactly
what you have to beat.

The dungeon is the Vault of Kaldrath: 22 rooms, four monsters, ten items, a locked
vault and one Crown. Find the Crown and carry it back out of the Entrance Hall.

Something else is down there too. **The Wanderer** is a ghost that drifts from room
to room on its own clock, walking straight through locked and secret doors. It is
always drawn on the map, whether or not you have been to the room it is in, and it
keeps moving while you stand there thinking. If it touches you it throws you
somewhere else in the dungeon entirely — which can be a shortcut or a death
sentence, depending on whether you brought a light. Stand next to it and you will
hear it dragging in the next room.

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install guava-sdk
.venv/bin/python main.py
```

Then open <http://localhost:8080>.

Credentials come from `.env` next to `main.py`:

```
GUAVA_API_KEY="gva-..."
GUAVA_AGENT_NUMBER="+1..."
```

Useful flags:

| Flag | What it does |
|---|---|
| `--port 8080` | port for the map page |
| `--channel phone` | answer real calls on `GUAVA_AGENT_NUMBER` (default) |
| `--channel webrtc` | answer browser calls instead, dialable from <https://app.goguava.ai/debug-webrtc> |
| `--channel none` | no phone at all — play by typing in the box under the map |

Run with `--channel none` and a text box appears under the map, running the identical
engine, so you can develop and test the whole game without spending a phone call.
Whenever the phone line is up that box stays hidden — this is a game you play by
calling.

## Joining

The page asks for your phone number and files your dungeon under its last four
digits. When you call, the agent reads the caller ID and picks up that session
silently — `on_call_start` binds and starts narrating immediately.

If your number is withheld, or you called before filling the page in, it falls back
to asking for those last four digits by voice or keypad.

Hanging up ends your run: it freezes where you stood, stops the clock, and goes on
the board as `abandoned`. Call back for a fresh one.

## Playing

Say (or type) things like:

```
go north / south / east / west      look                what am I carrying
take the sword                      drop the crown      examine the statue
attack the skeleton                 open the sarcophagus
put the charm in the socket         go back             play again
```

The keypad works too, which is handy when the line is noisy:
**2** north, **8** south, **6** east, **4** west, **5** look, **1** inventory, **0** help.

Two things will kill you: the dark, and whatever is in it. Find a light before you go
below.

## How it fits together

```
  caller ──phone── Guava dialog system ──websocket── main.py ──┐
                                                               ├── engine.py  the game
  browser ──SSE──────────── server.py ─────────────────────────┘
```

`main.py` is the Guava *expert*. Guava does the speech; every decision about the
dungeon is made locally:

| File | Job |
|---|---|
| `world.py` | the dungeon — rooms on a 5×5 grid, items, monsters, doors |
| `engine.py` | …including the Wanderer, which moves on wall-clock time, not turns |
| `engine.py` | one `GameState` per run; turns, damage, darkness, win and death |
| `parser.py` | turns "the caller wants to take the iron sword" into `("take", "sword", None)` |
| `sessions.py` | binds a browser tab to a phone call by four digit code; stores past runs |
| `server.py` | stdlib HTTP server, static files, and the SSE stream to the page |
| `main.py` | the Guava agent: handlers, narration, and the entry point |
| `static/` | the map page |

The Guava side is deliberately thin. `on_action_request` parses what the caller
wants and hands back a `SuggestedAction` whose key *is* the encoded command
(`take|sword|`); the generic `on_action` handler decodes it, runs it against the
engine, pushes the new state to the browser, and instructs the agent to read the
result back word for word. Read-only commands (`look`, inventory, `examine`) go
through `on_question` instead, so looking around never costs you a turn.

Finished runs — escaped, dead or hung up on — are appended to `runs.json`, which is
what the ghost trails and the dashboard down the left are drawn from. Writes re-read
the file and merge, so running the tests beside a live server does not lose runs.

## Testing

```bash
.venv/bin/python test_agent.py
```

Two checks. The first covers caller-ID binding in process. The second places a real
automated call: a roleplay session has no caller ID, so it exercises the spoken
fallback, plays a few turns, and hangs up. It prints the transcript, the resulting
game state, and the actions the engine actually executed.

`--offline` runs only the first, and places no call.
