"""End-to-end checks for the two ways a call finds its screen.

  1. Caller ID -- the normal path. Tested in-process, since a roleplay session
     has no real caller ID.
  2. Spoken last-four digits -- the fallback, tested with a real automated call
     where an LLM roleplays the caller.

Run with:  .venv/bin/python test_agent.py
"""

import json
import sys

import main
from sessions import STORE, last4


def test_caller_id():
    print("=== 1. caller ID binding ===")
    phone = "+1 657-210-1337"
    session, error = STORE.claim(phone, "Chris")
    assert error is None, error
    assert session.code == "1337", session.code
    print(f"  page claimed {phone} -> session {session.code}")

    bound = STORE.bind_caller("+16572101337", "call-abc")
    assert bound is session, "caller ID did not find the claimed session"
    print(f"  incoming +16572101337 -> recognised as {bound.player_name}")

    assert STORE.bind_caller("+19998887777", "call-xyz") is None
    print("  an unclaimed number is not bound (falls back to spoken digits)")

    assert last4("(657) 210 1337") == "1337" and last4("nope") is None
    print("  number normalising holds up\n")


def test_spoken_fallback():
    print("=== 2. spoken fallback (a real call) ===")
    phone = "+1 555 010 4477"
    session, _ = STORE.claim(phone, "Rasputin")
    print(f"  page claimed {phone} -> waiting on digits {session.code}\n")

    prompt = f"""
You are calling a phone line that runs a text adventure game. Play it like a real person.

It will not recognise your number, and will ask for the last four digits of your phone
number. They are {session.code} -- say those four digits.

Then play, one command at a time, waiting for the narrator each time:
  1. say "go south"
  2. say "take the rope"
  3. say "go south"
  4. say "take the glowing fungus"
  5. say "what am I carrying"
Then say you are finished playing and want to hang up. Do not invent your own dungeon
details; just say the commands and listen.
"""
    call = main.agent.roleplay(prompt)

    print("----- transcript -----")
    print(call.get_transcript())

    if session.game is None:
        print("\n!! the call never bound to the session")
        return False

    print("\n----- player-visible log -----")
    for line in session.transcript:
        print(f"  {line['who']:8} {line['text'][:100]}")
    print("\n  state:", json.dumps({
        "room": session.game.snapshot()["room_name"],
        "carrying": [i["key"] for i in session.game.snapshot()["inventory"]],
        "moves": session.game.moves,
    }))
    print("  executed:", getattr(call, "executed_actions", None))
    print("  termination:", getattr(call, "termination_reason", None))
    return True


if __name__ == "__main__":
    test_caller_id()
    ok = test_spoken_fallback() if "--offline" not in sys.argv else True
    print("\nOK" if ok else "\nFAILED")
    sys.exit(0 if ok else 1)
