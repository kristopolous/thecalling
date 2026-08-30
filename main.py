"""The Calling! -- a text adventure you play down the phone.

Run this and it does two things at once:

  * serves the map page on http://localhost:8080
  * answers calls on your Guava number

A browser tab shows a four digit code. The caller keys or says that code, and
from then on every command they speak moves the character on that tab's map.
"""

import argparse
import logging
import os
import re
import sys

import guava
from guava import Agent, Field, SuggestedAction, logging_utils

import server
from parser import parse, parse_dtmf, describe
from sessions import STORE

def load_env():
    """Load .env before anything constructs a Guava client.

    This has to happen at import time: guava.Agent() builds a Client in its
    constructor, and a Client with no GUAVA_API_KEY in the environment falls
    back to whichever org you last ran `guava login` as -- which is how you end
    up authenticated against the wrong account's phone numbers.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


load_env()

logger = logging.getLogger("kaldrath")

READONLY = {"look", "examine", "inventory", "status", "help", "search"}
RESTART = re.compile(r"\b(play again|start over|start again|new game|restart|try again|"
                     r"go back down|another run)\b", re.I)

NARRATION_RULES = (
    "You are the voice of a dungeon in an old text adventure. The player is exploring it over "
    "the telephone. Everything that happens in the dungeon is decided by the expert, not by you. "
    "When the expert gives you dungeon text, read it to the player as written, in an unhurried "
    "storyteller's voice, and add nothing to it. Never invent a room, an item, a monster, an exit "
    "or an outcome, and never repeat an old description from earlier in the call: the dungeon "
    "changes, and only the expert knows the truth of it. Every time the player asks what they can "
    "see, what they are carrying, where they can go, or how they are doing, ask the expert and "
    "read back the answer. "
    "Act on what the player says at once. Never ask them to confirm a move, and never say that "
    "you are checking, looking something up, or asking someone -- say nothing at all while you "
    "wait, then narrate. "
    "If the player asks how to play, tell them to say things like 'go north', 'take the sword', "
    "'look', 'what am I carrying', or 'attack the skeleton', and that the keypad works too: "
    "two, four, six and eight for north, west, east and south."
)

agent = Agent(
    name="the Dungeon",
    organization="The Calling",
    purpose=("Narrate a dungeon crawl to a caller. Relay the caller's commands to the expert and "
             "read the expert's dungeon text back, word for word."),
)


# --------------------------------------------------------------------- turns

def run_command(session, command, spoken_as=None):
    """Run one parsed command against a session's game and push it to the browser."""
    if session.game is None:
        session.start_game()

    session.say("player", spoken_as or describe(command))
    text = session.game.execute(*command)
    session.say("dungeon", text)

    if not session.game.alive and not getattr(session, "_recorded", False):
        session._recorded = True
        STORE.record_run(session)

    session.publish()
    logger.info("[%s] %s -> %s", session.code, describe(command), text[:90])
    return text


def restart(session):
    # An abandoned run still counts as a mark on the board.
    if session.game is not None and not getattr(session, "_recorded", False):
        session._recorded = True
        STORE.record_run(session)
    session.start_game()
    session._recorded = False
    text = "The stair takes you back down into the dark. " + session.game.describe_room()
    session.say("dungeon", text)
    session.publish()
    return text


def handle_text(session, text):
    """Parse and run one line of player input. Returns narration, or None."""
    if RESTART.search(text or ""):
        return restart(session)
    command = parse(text)
    if command is None:
        return ("I did not follow that. Try something like: go north, take the sword, look, "
                "or what am I carrying.")
    return run_command(session, command, spoken_as=text.strip())


def narrate(call, text):
    call.send_instruction(
        f'Read this to the player word for word, and add nothing of your own: "{text}"')


# ------------------------------------------------------------------ handlers

@agent.on_call_start
def on_call_start(call: guava.Call):
    call.read_script(
        "You have reached The Calling, and the Vault of Kaldrath is open. "
        "Look at the screen in front of you and give me your four digit dungeon code."
    )
    call.set_task(
        "join",
        objective="Bind this call to the player's screen, then get their name for the board.",
        checklist=[
            Field(key="dungeon_code", field_type="digit_sequence",
                  description="The four digit dungeon code shown on the player's screen.",
                  question="What is your four digit dungeon code?"),
            Field(key="player_name", field_type="text",
                  description="What to call this player on the leaderboard.",
                  question="And what name should go on the board?"),
        ],
    )


@agent.on_task_complete("join")
def on_join(call: guava.Call):
    code = re.sub(r"\D", "", str(call.get_field("dungeon_code") or ""))[:4]
    name = (str(call.get_field("player_name") or "").strip() or None)

    session = STORE.bind(code, call.id)
    if session is None:
        call.send_instruction(
            f"There is no dungeon open with the code {code}. Tell the player that code is not "
            "open, ask them to read the four digit code on their screen again, and try once more."
        )
        call.retry_task("The dungeon code the player gave is not open on any screen.")
        return

    session.player_name = name
    session.start_game(name)
    session._recorded = False
    session.publish()

    call.add_info("how_to_play", {
        "commands": ["go north", "go south", "go east", "go west", "look", "what am I carrying",
                     "take the sword", "drop the crown", "examine the statue",
                     "attack the skeleton", "open the sarcophagus", "go back", "play again"],
        "keypad": {"2": "north", "4": "west", "6": "east", "8": "south", "5": "look",
                   "1": "inventory", "0": "help"},
        "goal": "Find the Crown of Kaldrath and carry it back out through the Entrance Hall.",
    })
    call.set_persona(agent_purpose=NARRATION_RULES)
    call.send_instruction(NARRATION_RULES)

    call.set_task(
        "dungeon",
        objective=("Play the dungeon with the player. Send every instruction they give you to the "
                   "expert and read back exactly what the expert says. Never decide anything about "
                   "the dungeon yourself."),
        completion_criteria=("Only when the player has finished a run and says clearly that they "
                             "are done playing and want to hang up."),
    )
    narrate(call, f"{'Welcome, ' + name + '. ' if name else ''}{session.game.describe_room()}")


@agent.on_task_complete("dungeon")
def on_done(call: guava.Call):
    call.hangup("Wish the player well and tell them their run is on the board.")


@agent.on_action_request
def on_action_request(call: guava.Call, request: str):
    """Classify what the caller wants into a command the engine can run."""
    session = STORE.by_call(call.id)
    if session is None:
        return None
    if RESTART.search(request or ""):
        return SuggestedAction(key="restart||", description="start a new run")

    command = parse(request)
    if command is None:
        return None
    verb, noun, target = command
    # Pure queries are answered through on_question instead, so a look-around
    # never costs the player a turn.
    if verb in READONLY:
        return None
    return SuggestedAction(key=f"{verb}|{noun or ''}|{target or ''}",
                           description=describe(command))


@agent.on_action
def on_action(call: guava.Call, action_key: str):
    session = STORE.by_call(call.id)
    if session is None:
        return None

    verb, noun, target = (action_key.split("|") + ["", ""])[:3]
    if verb == "restart":
        narrate(call, restart(session))
        return None

    text = run_command(session, (verb, noun or None, target or None))
    narrate(call, text)
    return None


@agent.on_question
def on_question(call: guava.Call, question: str) -> str:
    session = STORE.by_call(call.id)
    if session is None or session.game is None:
        return "Give me the four digit dungeon code on your screen first."

    command = parse(question)
    if command and command[0] in READONLY:
        # Answered here rather than as an action, so looking around never costs a turn.
        return run_command(session, command, spoken_as=question.strip())

    # Anything else: the plain truth about where they are standing. The action
    # handler, running in parallel, does the acting.
    return session.game.describe_room()


@agent.on_dtmf
def on_dtmf(call: guava.Call, event):
    session = STORE.by_call(call.id)
    if session is None or session.game is None:
        return  # still joining -- the code field is collecting these digits
    command = parse_dtmf(event.digit)
    if command is None:
        return
    narrate(call, run_command(session, command, spoken_as=f"[keypad {event.digit}]"))


@agent.on_session_end
def on_session_end(call: guava.Call, event):
    session = STORE.by_call(call.id)
    if session is None:
        return
    if session.game and session.game.alive and not getattr(session, "_recorded", False):
        session._recorded = True
        STORE.record_run(session)   # an abandoned run still counts as a mark on the board
    STORE.release(call.id)
    logger.info("[%s] call ended: %s", session.code, event.termination_reason)


# ----------------------------------------------------------------- bootstrap

def main():
    logging_utils.configure_logging()

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8080, help="port for the map page")
    ap.add_argument("--channel", choices=["phone", "webrtc", "none"], default="phone",
                    help="how callers reach the dungeon (none = browser typing only)")
    ap.add_argument("--number", default=os.environ.get("GUAVA_AGENT_NUMBER"),
                    help="the Guava number to answer on")
    args = ap.parse_args()

    server.COMMAND_HOOK = handle_text
    server.CALL_INFO["number"] = args.number if args.channel == "phone" else None
    server.CALL_INFO["ready"] = args.channel != "none"
    server.serve(args.port)
    print(f"\n  The Vault of Kaldrath is open at http://localhost:{args.port}\n")

    if args.channel == "none":
        print("  Phone line disabled. Play by typing in the browser.\n")
        try:
            import time
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    if not os.environ.get("GUAVA_API_KEY"):
        sys.exit("GUAVA_API_KEY is not set. Put it in .env next to this file.")

    if args.channel == "webrtc":
        agent.listen_webrtc()
    else:
        if not args.number:
            sys.exit("No phone number. Set GUAVA_AGENT_NUMBER in .env or pass --number.")
        print(f"  Answering calls on {args.number}\n")
        agent.listen_phone(args.number)


if __name__ == "__main__":
    main()
