"""End-to-end check: an LLM roleplays a caller and actually plays the dungeon.

Run with:  .venv/bin/python test_agent.py
"""

import json
import sys

import main
from sessions import STORE

main.load_env()

session = STORE.create()
print(f"opened dungeon code {session.code}\n")

PROMPT = f"""
You are calling a phone line that runs a text adventure game. Play it like a real person.

Your dungeon code is {session.code} -- say the four digits when asked for it.
Your name is Rasputin -- give that when asked for a name.

Then play, one command at a time, waiting for the narrator each time:
  1. say "go south"
  2. say "take the rope"
  3. say "go south"
  4. say "take the glowing fungus"
  5. say "what am I carrying"
  6. say "look around"
  7. say "go east"
Then say you are finished playing and want to hang up. Do not invent your own
dungeon details; just say the commands and listen.
"""

test_session = main.agent.roleplay(PROMPT)

print("\n===== TRANSCRIPT =====")
print(test_session.get_transcript())

print("\n===== GAME STATE =====")
if session.game is None:
    print("!! the call never bound to the session")
    sys.exit(1)
print(json.dumps(session.game.snapshot(), indent=1)[:1200])

print("\n===== PLAYER-VISIBLE LOG =====")
for line in session.transcript:
    print(f"  {line['who']:8} {line['text'][:110]}")

print("\nexecuted actions:", getattr(test_session, "executed_actions", None))
print("termination:", getattr(test_session, "termination_reason", None))
