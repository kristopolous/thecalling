"""Turn what a caller said into a (verb, noun, target) command.

Guava hands us a natural-language *summary* of the caller's intent, e.g.
"the caller wants to take the iron sword", so this parser is deliberately
loose: it scans for a known verb and a known noun anywhere in the sentence
rather than insisting on classic two-word adventure grammar.
"""

import re

from world import ITEMS, MONSTERS

DIRECTION_WORDS = {
    "north": "north", "n": "north", "up": "north", "forward": "north", "forwards": "north",
    "south": "south", "s": "south", "down": "south",
    "east": "east", "e": "east", "right": "east",
    "west": "west", "w": "west", "left": "west",
}

# Digit -> direction, for the phone keypad.
DTMF_DIRECTIONS = {"2": "north", "8": "south", "6": "east", "4": "west"}
DTMF_VERBS = {"5": ("look", None, None), "0": ("help", None, None), "1": ("inventory", None, None)}

VERBS = {
    "go": ("go", "walk", "move", "head", "run", "travel", "proceed", "continue", "enter", "exit",
           "climb", "crawl", "step", "leave", "flee"),
    "look": ("look", "survey", "describe"),
    "examine": ("examine", "inspect", "x", "read", "study", "check"),
    "take": ("take", "get", "grab", "pick", "collect", "steal", "acquire", "loot", "retrieve"),
    "drop": ("drop", "discard", "leave behind", "put down"),
    "inventory": ("inventory", "carrying", "holding", "have", "possess"),
    "open": ("open", "lift", "pry", "force"),
    "unlock": ("unlock",),
    "attack": ("attack", "kill", "fight", "hit", "strike", "stab", "slash", "cut", "burn",
               "destroy", "swing", "smash", "throw"),
    "put": ("put", "place", "insert", "set", "fit", "install", "mount"),
    "use": ("use", "apply", "try"),
    "wait": ("wait", "rest", "pause", "stay"),
    "back": ("go back", "back up", "backtrack", "retreat", "turn around", "way i came"),
    "search": ("search", "loot", "rummage", "feel"),
    "status": ("status", "score", "health", "how am i", "doing"),
    "help": ("help", "commands", "hint", "instructions", "stuck"),
}

# Fixed scenery the player can talk about, per the rooms that have it.
SCENERY = {
    "statue": ("statue", "king", "crowned king", "socket", "hand", "figure"),
    "sarcophagus": ("sarcophagus", "coffin", "tomb", "casket", "lid"),
    "webs": ("web", "webs", "webbing", "cobweb", "cobwebs", "curtain"),
    "door": ("door", "iron door", "vault door", "gate"),
}

_NOUN_ALIASES = {}
for _i in ITEMS:
    for _a in _i.aliases:
        _NOUN_ALIASES[_a] = _i.key
for _m in MONSTERS:
    for _a in _m.aliases:
        _NOUN_ALIASES.setdefault(_a, _m.key)
for _k, _aliases in SCENERY.items():
    for _a in _aliases:
        _NOUN_ALIASES.setdefault(_a, _k)

# Longest aliases first, so "iron door" beats "door" and "brass key" beats "key".
_NOUN_ORDER = sorted(_NOUN_ALIASES, key=len, reverse=True)

_FILLER = re.compile(
    r"\b(the caller|the player|caller|player|user|wants? to|would like to|is asking to|"
    r"asks? to|requests? to|says? to|i want to|i would like to|i'd like to|let's|lets|"
    r"please|now|then|and then|i will|i'll|can i|could i|may i|i am going to|i'm going to)\b")


def normalize(text):
    text = (text or "").lower()
    text = text.replace("’", "'")
    text = _FILLER.sub(" ", text)
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _find_nouns(text):
    """Return the known nouns in the order they appear."""
    found = []
    consumed = [False] * len(text)
    for alias in _NOUN_ORDER:
        for m in re.finditer(r"\b" + re.escape(alias) + r"\b", text):
            if any(consumed[m.start():m.end()]):
                continue
            for i in range(m.start(), m.end()):
                consumed[i] = True
            found.append((m.start(), _NOUN_ALIASES[alias]))
    found.sort()
    out = []
    for _, key in found:
        if key not in out:
            out.append(key)
    return out


def _find_verb(text):
    """Earliest verb wins; on a tie the longer phrase wins, so "go back" beats "go"."""
    best = None
    for verb, words in VERBS.items():
        for w in words:
            m = re.search(r"\b" + re.escape(w) + r"\b", text)
            if m is None:
                continue
            rank = (m.start(), -len(w))
            if best is None or rank < best[0]:
                best = (rank, verb)
    return best[1] if best else None


def parse(text):
    """Parse one utterance. Returns (verb, noun, target) or None."""
    t = normalize(text)
    if not t:
        return None

    # A bare direction, or any sentence containing a compass word, is movement --
    # unless the sentence is clearly about an object ("take the sword to the north").
    words = t.split()
    verb = _find_verb(t)
    nouns = _find_nouns(t)

    direction = None
    for w in words:
        if w in DIRECTION_WORDS:
            # "up"/"down"/"back"/"left"/"right" are only directions when nothing
            # more specific is going on.
            if w in ("up", "down", "left", "right", "forward", "forwards"):
                if verb not in (None, "go"):
                    continue
            direction = DIRECTION_WORDS[w]
            break

    if direction and verb in (None, "go"):
        return ("go", direction, None)

    if verb is None:
        # No verb, but a noun we know: assume they want to look at it.
        if nouns:
            return ("examine", nouns[0], None)
        return None

    if verb == "back":
        return ("back", None, None)

    if verb == "go":
        if direction:
            return ("go", direction, None)
        return ("go", None, None)

    noun = nouns[0] if nouns else None
    target = nouns[1] if len(nouns) > 1 else None

    # "throw the acid at the webs" and "cut the webs with the sword" both mean
    # "use the tool on the barrier", whichever order they came in.
    if verb == "attack" and noun in ("acid", "sword") and target:
        return ("use", noun, target)
    if verb == "attack" and noun == "webs" and target in ("acid", "sword"):
        return ("use", target, "webs")
    if verb == "put" and noun and target:
        return ("put", noun, target)

    return (verb, noun, target)


def parse_dtmf(digit):
    """Parse a single keypad press."""
    if digit in DTMF_DIRECTIONS:
        return ("go", DTMF_DIRECTIONS[digit], None)
    return DTMF_VERBS.get(digit)


def describe(command):
    """A short human phrase for a parsed command, for the transcript and for
    the confirmation text Guava may read back to the caller."""
    verb, noun, target = command
    if verb == "go":
        return f"go {noun}" if noun else "move"
    if noun and target:
        return f"{verb} {noun.replace('_', ' ')} with {target.replace('_', ' ')}"
    if noun:
        return f"{verb} the {noun.replace('_', ' ')}"
    return verb
