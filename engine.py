"""The game engine: one GameState per player, driven by parsed commands.

Every public method returns narration text meant to be *spoken*, so it avoids
lists, symbols and anything else that reads badly through a phone.
"""

import time

from world import (
    DOORS, ITEMS, MONSTERS, ROOMS_BY_KEY, ITEMS_BY_KEY, MONSTERS_BY_KEY,
    START_ROOM, START_HEALTH, GOAL_ITEM,
)

DIRECTIONS = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}


def _direction(from_room, to_room):
    a, b = ROOMS_BY_KEY[from_room], ROOMS_BY_KEY[to_room]
    for name, (dx, dy) in DIRECTIONS.items():
        if (a.x + dx, a.y + dy) == (b.x, b.y):
            return name
    raise ValueError(f"{from_room} and {to_room} are not neighbours")


# Precompute, for every room, the doors leading out of it and their direction.
EXITS = {key: {} for key in ROOMS_BY_KEY}
for _d in DOORS:
    EXITS[_d.a][_direction(_d.a, _d.b)] = _d
    EXITS[_d.b][_direction(_d.b, _d.a)] = _d


def the(room_name):
    """Room names like "The Vault" already carry their article; don't double it."""
    return room_name if room_name.lower().startswith("the ") else f"the {room_name}"


def _listify(names):
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


class GameState:
    """A single run through the dungeon."""

    def __init__(self, player_name="Someone"):
        self.player_name = player_name
        self.room = START_ROOM
        self.health = START_HEALTH
        self.inventory = []
        self.visited = set()
        self.moves = 0
        self.started_at = time.time()
        self.ended_at = None
        self.outcome = None          # None | "escaped" | "dead"
        self.last_narration = ""
        self.path = []               # [(room_key, seconds_elapsed)]

        # Where every item currently is: room key, "player", or None once used up.
        self.item_room = {i.key: i.start for i in ITEMS}
        self.monsters_alive = {m.key: True for m in MONSTERS}
        self.monster_awake = {m.key: not m.dormant for m in MONSTERS}

        self.opened_secret = False
        self.opened_sarcophagus = False
        self.webs_cleared = False
        self.unlocked = set()        # door keys the player has opened
        self.dark_turns = 0          # consecutive turns fumbling in the dark

        self._record_path()

    # ---------------------------------------------------------------- helpers

    @property
    def elapsed(self):
        return (self.ended_at or time.time()) - self.started_at

    @property
    def alive(self):
        return self.outcome is None

    def _record_path(self):
        self.path.append((self.room, round(self.elapsed, 1)))

    def has(self, item_key):
        return item_key in self.inventory

    @property
    def has_light(self):
        return self.has("fungus")

    def _room(self):
        return ROOMS_BY_KEY[self.room]

    def items_here(self):
        return [i for i in ITEMS if self.item_room[i.key] == self.room]

    def monsters_here(self):
        return [m for m in MONSTERS
                if m.room == self.room and self.monsters_alive[m.key] and self.monster_awake[m.key]]

    def hostile_here(self):
        """Live monsters in this room that are not warded off by what we carry."""
        return [m for m in self.monsters_here()
                if not any(self.has(w) for w in m.warded_by)]

    def _door_key(self, door):
        return f"{door.a}:{door.b}"

    def _door_passable(self, door):
        """Return (ok, refusal_text)."""
        if door.secret and not self.opened_secret:
            return False, None  # the player does not even know it is there
        if door.blocked_by == "webs" and not self.webs_cleared:
            return False, door.barrier_text
        if door.blocked_by == "shaft" and not self.has("rope"):
            return False, door.barrier_text
        if door.key and self._door_key(door) not in self.unlocked:
            if self.has(door.key):
                return True, None  # unlocked on the way through
            return False, door.locked_text
        return True, None

    def visible_exits(self):
        """Directions the player can see a way out in, whether or not it opens."""
        out = []
        for direction, door in sorted(EXITS[self.room].items()):
            if door.secret and not self.opened_secret:
                continue
            out.append(direction)
        return out

    # ------------------------------------------------------------- description

    def describe_room(self, force_full=False):
        room = self._room()
        if room.dark and not self.has_light:
            return ("It is pitch black. You cannot see a thing, and you can hear something in here "
                    "with you, breathing.")

        first = room.key not in self.visited
        parts = [room.desc if (first or force_full) else room.brief]
        self.visited.add(room.key)

        items = [i.name for i in self.items_here()]
        if items:
            parts.append(f"You can see {_listify(items)} here.")

        for m in self.monsters_here():
            if any(self.has(w) for w in m.warded_by):
                parts.append(f"The {m.name} is here, but it keeps its distance from you.")
            else:
                parts.append(m.intro)

        exits = self.visible_exits()
        if exits:
            parts.append(f"Ways out: {_listify(exits)}.")
        else:
            parts.append("There is no way out of here that you can see.")
        return " ".join(parts)

    def status_line(self):
        carried = _listify([ITEMS_BY_KEY[k].name for k in self.inventory]) or "nothing"
        return (f"You are in {the(self._room().name)}, carrying {carried}, "
                f"with {self.health} health, after {int(self.elapsed)} seconds.")

    # ---------------------------------------------------------------- the turn

    def execute(self, verb, noun=None, target=None):
        """Run one command. Returns the narration to speak."""
        if not self.alive:
            return "Your run is over. " + {
                "escaped": "You made it out.",
                "dead": "You died down there.",
                "abandoned": "You hung up on it.",
            }.get(self.outcome, "")

        room = self._room()
        blind = room.dark and not self.has_light

        # In the dark you may only feel your way out, or produce a light.
        if blind and verb not in ("go", "back", "look", "inventory", "status", "help", "take"):
            return self._grue()

        handler = getattr(self, f"_do_{verb}", None)
        if handler is None:
            return "You cannot do that here."

        text = handler(noun, target)
        if not self.alive:
            return text

        # Everything that is not a pure query costs a turn in the world.
        if verb not in ("look", "inventory", "status", "help", "examine"):
            self.moves += 1
            after = self._world_turn()
            if after:
                text = f"{text} {after}"
        self.last_narration = text
        return text

    def _world_turn(self):
        """Monsters, heat and grues get their move."""
        parts = []
        room = self._room()

        if room.dark and not self.has_light:
            self.dark_turns += 1
            if self.dark_turns >= 2:
                return self._die("Something finds you in the dark. It is over very quickly.")
        else:
            self.dark_turns = 0

        if room.heat:
            self.health -= room.heat
            parts.append(f"The heat is cooking you. You lose {room.heat} health.")
            if self.health <= 0:
                return self._die("You go down on the hot stone and do not get up.")

        for m in self.hostile_here():
            self.health -= m.damage
            parts.append(f"{m.threat} You lose {m.damage} health.")
            if self.health <= 0:
                return self._die(f"The {m.name} finishes you.")

        if self.health <= 30 and self.alive:
            parts.append("You are badly hurt.")
        return " ".join(parts)

    def _grue(self):
        self.dark_turns += 1
        if self.dark_turns >= 2:
            return self._die("Something finds you in the dark. It is over very quickly.")
        return ("It is pitch black and you cannot see what you are doing. "
                "Get out, or find a light, quickly.")

    def abandon(self):
        """The player hung up. Freeze the run where it stands."""
        if not self.alive:
            return None
        self.outcome = "abandoned"
        self.ended_at = time.time()
        self._record_path()
        return (f"{self.player_name or 'The player'} hung up in {the(self._room().name)} "
                f"after {int(self.elapsed)} seconds.")

    def _die(self, text):
        self.outcome = "dead"
        self.ended_at = time.time()
        self.health = 0
        self._record_path()
        return (f"{text} You are dead. You got as far as {the(self._room().name)}, "
                f"in {int(self.elapsed)} seconds.")

    def _win(self):
        self.outcome = "escaped"
        self.ended_at = time.time()
        self._record_path()
        return (f"You come up the stair into the rain with the Crown of Kaldrath under your arm. "
                f"You are out, alive, in {int(self.elapsed)} seconds, with a score of {self.score()}. "
                f"Nobody has done it faster than they had to.")

    def score(self):
        pts = 50 * len(self.visited)
        for key in self.inventory:
            pts += ITEMS_BY_KEY[key].treasure
        if self.outcome == "escaped":
            pts += 500
        return pts

    # -------------------------------------------------------------- the verbs

    def _do_go(self, noun, target=None):
        direction = noun
        if direction not in DIRECTIONS:
            return "You can go north, south, east or west."

        door = EXITS[self.room].get(direction)
        if door is None:
            return f"There is nothing but solid rock to the {direction}."

        ok, refusal = self._door_passable(door)
        if not ok:
            return refusal or f"There is nothing but solid rock to the {direction}."

        other = door.b if door.a == self.room else door.a
        prefix = ""
        if door.key and self._door_key(door) not in self.unlocked:
            self.unlocked.add(self._door_key(door))
            prefix = f"You try the {ITEMS_BY_KEY[door.key].name} and it turns. "

        # Anything hostile gets a parting shot as you leave.
        parting = ""
        for m in self.hostile_here():
            self.health -= m.damage // 2
            parting = f"The {m.name} catches you on the way out for {m.damage // 2} health. "
            if self.health <= 0:
                return self._die(f"The {m.name} drags you down as you turn to run.")

        self.room = other
        self.dark_turns = 0
        self._record_path()

        if self.room == START_ROOM and self.has(GOAL_ITEM):
            return self._win()

        return prefix + parting + self.describe_room()

    def _do_back(self, noun=None, target=None):
        """Retreat to the room we came from."""
        previous = None
        for room_key, _ in reversed(self.path[:-1]):
            if room_key != self.room:
                previous = room_key
                break
        if previous is None:
            return "You have not come from anywhere yet."
        for direction, door in EXITS[self.room].items():
            other = door.b if door.a == self.room else door.a
            if other == previous:
                return self._do_go(direction)
        return "You cannot get back that way."

    def _do_look(self, noun=None, target=None):
        return self.describe_room(force_full=True)

    def _do_status(self, noun=None, target=None):
        return self.status_line()

    def _do_inventory(self, noun=None, target=None):
        if not self.inventory:
            return "You are carrying nothing at all."
        return "You are carrying " + _listify([ITEMS_BY_KEY[k].name for k in self.inventory]) + "."

    def _do_help(self, noun=None, target=None):
        return ("Say things like: go north. Take the sword. Look. What am I carrying. "
                "Examine the statue. Attack the skeleton. Open the sarcophagus. "
                "Or use the keypad: two for north, eight for south, six for east, four for west.")

    def _do_examine(self, noun, target=None):
        if noun is None:
            return self.describe_room(force_full=True)
        item = ITEMS_BY_KEY.get(noun)
        if item and (self.has(noun) or self.item_room[noun] == self.room):
            return item.desc
        monster = MONSTERS_BY_KEY.get(noun)
        if monster and monster.room == self.room and self.monsters_alive[noun]:
            return monster.intro
        if noun == "statue" and self.room == "gallery":
            if self.opened_secret:
                return ("The crowned king holds the bone charm in his fist, and the wall behind him "
                        "stands open.")
            return ("The king's hand is open, palm up, with a socket cut into it about the size of a "
                    "fist. Something is meant to sit there.")
        if noun == "sarcophagus" and self.room == "crypt":
            if self.opened_sarcophagus:
                return "The sarcophagus is open and empty, and colder inside than out."
            return "Black stone, lid ajar, heavy as a wall. You could get it open."
        if noun == "webs" and self.room == "webtunnel":
            if self.webs_cleared:
                return "The web hangs in cut ribbons. You can get past."
            return "Grey cable, layered a hundred deep. You would need to cut or burn your way through."
        return "You do not see that here."

    def _do_take(self, noun, target=None):
        if self._room().dark and not self.has_light:
            return self._grue()
        if noun is None:
            return "Take what?"
        item = ITEMS_BY_KEY.get(noun)
        if item is None or self.item_room.get(noun) != self.room:
            if item and self.has(noun):
                return f"You already have the {item.name}."
            return "You do not see that here."

        self.item_room[noun] = "player"
        self.inventory.append(noun)
        text = f"You take the {item.name}."

        if noun == "keys" and not self.monster_awake["skeleton"]:
            self.monster_awake["skeleton"] = True
            text += " The skeleton's hand closes on your wrist. It is standing up."
        if noun == "crown":
            text += (" The Crown of Kaldrath is yours. Now get it back to the Entrance Hall, "
                     "and out, before something down here takes it off you.")
        return text

    def _do_drop(self, noun, target=None):
        if noun is None or not self.has(noun):
            return "You are not carrying that."
        self.inventory.remove(noun)
        self.item_room[noun] = self.room
        return f"You drop the {ITEMS_BY_KEY[noun].name}."

    def _do_open(self, noun, target=None):
        if noun == "sarcophagus" and self.room == "crypt":
            if self.opened_sarcophagus:
                return "It is already open."
            self.opened_sarcophagus = True
            self.item_room["brass_key"] = "crypt"
            return ("You get your shoulder under the lid and walk it aside. Inside, on a bed of dust, "
                    "there is a small brass key.")
        if noun in ("door", "vault", "iron door", None):
            for direction, door in EXITS[self.room].items():
                if door.key and self._door_key(door) not in self.unlocked:
                    if self.has(door.key):
                        self.unlocked.add(self._door_key(door))
                        return (f"You unlock the door to the {direction} with the "
                                f"{ITEMS_BY_KEY[door.key].name}.")
                    return door.locked_text
            return "There is nothing here that needs opening."
        return "That does not open."

    _do_unlock = _do_open

    def _do_attack(self, noun, target=None):
        if noun == "webs" and self.room == "webtunnel":
            return self._clear_webs()

        candidates = [m for m in self.monsters_here() if noun in (None, m.key)]
        if not candidates:
            return "There is nothing here to fight."
        m = candidates[0]

        weapon = next((w for w in m.beaten_by if self.has(w)), None)
        if weapon is None:
            if m.warded_by and any(self.has(w) for w in m.warded_by):
                return f"The {m.name} will not come near you. Leave it be."
            if not m.beaten_by:
                return (f"You swing at the {m.name} and pass straight through it. Steel is no use "
                        f"here. Something else keeps it off you.")
            return f"You have nothing that could hurt the {m.name}."

        self.monsters_alive[m.key] = False
        return f"{m.death} You used the {ITEMS_BY_KEY[weapon].name}."

    def _clear_webs(self):
        if self.webs_cleared:
            return "The web is already cut through."
        if self.has("acid"):
            self.inventory.remove("acid")
            self.item_room["acid"] = None
            self.webs_cleared = True
            return ("You throw the acid into the web. It goes up in a sheet of grey smoke and eats a "
                    "hole clean through. The way west is open.")
        if self.has("sword"):
            self.webs_cleared = True
            return "You hack the web apart, strand by strand, until the tunnel is clear to the west."
        return "You claw at the web and only get stuck to it. You need to cut it, or burn it."

    def _do_put(self, noun, target=None):
        if noun == "charm" and self.room == "gallery" and self.has("charm"):
            if self.opened_secret:
                return "The charm is already in the king's hand."
            self.inventory.remove("charm")
            self.item_room["charm"] = "gallery"
            self.opened_secret = True
            return ("You set the bone charm into the socket in the king's hand. The fist closes on it. "
                    "Somewhere behind the statue a counterweight drops, and the south wall swings open "
                    "onto a round hall.")
        if noun and self.has(noun):
            return "Nothing happens."
        return "You are not carrying that."

    def _do_use(self, noun, target=None):
        if noun == "acid" and (target in ("webs", None)) and self.room == "webtunnel":
            return self._clear_webs()
        if noun == "sword" and target == "webs":
            return self._clear_webs()
        if noun == "charm":
            return self._do_put("charm")
        if noun == "rope" and self.room == "warren":
            return self._do_go("south")
        if noun == "keys" or noun == "brass_key":
            return self._do_open("door")
        if noun == "fungus":
            return "The fungus is already lighting your way."
        if noun and self.has(noun):
            return f"You cannot think what to do with the {ITEMS_BY_KEY[noun].name} here."
        return "You are not carrying that."

    def _do_wait(self, noun=None, target=None):
        return "You wait. The dungeon does not."

    def _do_search(self, noun=None, target=None):
        if self.room == "crypt" and not self.opened_sarcophagus:
            return "The sarcophagus lid is ajar. You could get it open."
        items = self.items_here()
        if items:
            return "You turn the place over and find " + _listify([i.name for i in items]) + "."
        return "You search, and find nothing you had not already seen."

    # ------------------------------------------------------------ web snapshot

    def snapshot(self):
        """Everything the browser needs to draw this run."""
        return {
            "room": self.room,
            "room_name": self._room().name,
            "health": max(0, self.health),
            "max_health": START_HEALTH,
            "inventory": [{"key": k, "name": ITEMS_BY_KEY[k].name} for k in self.inventory],
            "visited": sorted(self.visited),
            "path": [p[0] for p in self.path],
            "moves": self.moves,
            "elapsed": round(self.elapsed, 1),
            "outcome": self.outcome,
            "score": self.score(),
            "has_light": self.has_light,
            "secret_open": self.opened_secret,
            "webs_cleared": self.webs_cleared,
            "unlocked": sorted(self.unlocked),
            "monsters": [
                {"key": m.key, "room": m.room, "name": m.name}
                for m in MONSTERS
                if self.monsters_alive[m.key] and self.monster_awake[m.key]
            ],
            "items_on_floor": [
                {"key": i.key, "room": self.item_room[i.key], "name": i.name}
                for i in ITEMS
                if self.item_room[i.key] not in (None, "player")
                and self.item_room[i.key] in self.visited
            ],
        }
