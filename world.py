"""The Vault of Kaldrath -- a small, hand-authored dungeon on a 5x5 grid.

The grid coordinates matter: the web map draws rooms at (x, y) and derives
compass directions from adjacency, so every connection below must join two
grid-neighbouring rooms.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Room:
    key: str
    name: str
    x: int
    y: int
    desc: str            # spoken on first visit
    brief: str           # spoken on every later visit
    dark: bool = False   # needs a light source
    heat: int = 0        # damage per turn spent here


@dataclass(frozen=True)
class Item:
    key: str
    name: str            # how the narrator says it
    aliases: tuple       # what the player might call it
    start: str | None    # room key, or None if it starts hidden
    desc: str
    treasure: int = 0    # points if carried out


@dataclass(frozen=True)
class Monster:
    key: str
    name: str
    aliases: tuple
    room: str
    beaten_by: tuple     # item keys that can kill it
    warded_by: tuple     # item keys that make it leave you alone
    damage: int          # HP lost per turn you share a room with it
    intro: str           # said when you enter and it is alive
    threat: str          # said each turn it hurts you
    death: str           # said when you kill it
    dormant: bool = False  # true if it only wakes on a trigger


@dataclass(frozen=True)
class Door:
    a: str
    b: str
    key: str | None = None       # item required to unlock
    secret: bool = False         # hidden until revealed
    blocked_by: str | None = None  # a barrier that must be cleared first
    locked_text: str = ""
    barrier_text: str = ""


ROOMS = [
    Room("entrance", "Entrance Hall", 0, 0,
         "You stand in a cracked marble hall, open to a sliver of grey sky. Rain has worn the faces "
         "off two guardian statues at the stair. Daylight and the world above lie behind you. A low "
         "corridor runs east, and worn steps drop away to the south.",
         "The Entrance Hall. Daylight leaks in from above."),
    Room("corridor", "Dust Corridor", 1, 0,
         "A narrow corridor, ankle deep in grey dust. Your footprints are the only ones in it. It runs "
         "west back to the light and east into the dark.",
         "The Dust Corridor."),
    Room("guardpost", "Guard Post", 2, 0,
         "A cramped guard post. A skeleton in rusted mail sits slumped against the wall with a ring of "
         "keys still hanging at its belt. A stair drops south, and the corridor continues east.",
         "The Guard Post."),
    Room("arch", "Collapsed Arch", 3, 0,
         "Half of this hall has come down. You pick your way over cut stone under an arch that is "
         "holding up more than it should. Ways west and east.",
         "The Collapsed Arch. Dust sifts down from the ceiling."),
    Room("warren", "Rat Warren", 4, 0,
         "The floor here is a mat of chewed bone and rag. Something has made a city of this room. In "
         "the corner a shaft drops straight down into blackness.",
         "The Rat Warren. The shaft drops away in the corner."),

    Room("cistern", "The Cistern", 0, 1,
         "A round brick cistern half full of black water. A coil of tarred rope hangs from an iron "
         "hook, left by someone who did not come back for it.",
         "The Cistern. Water slaps quietly at the brick."),
    Room("armory", "Armory", 2, 1,
         "Weapon racks, all empty but one. A single iron short sword is still clamped in its bracket, "
         "furred with rust but whole.",
         "The Armory. Empty racks line the walls."),
    Room("bonepit", "Bone Pit", 4, 1, dark=True,
         desc="You are at the bottom of the shaft, standing on a drift of bones that shifts under you "
              "like gravel. Something small and pale is threaded on a cord in the heap. A crawlway "
              "runs south.",
         brief="The Bone Pit. Bones shift underfoot."),

    Room("grotto", "Fungal Grotto", 0, 2,
         "A wide cave lit softly from below. Clutches of pale fungus grow out of the wet rock, each one "
         "glowing like a held breath.",
         "The Fungal Grotto, softly lit by the fungus."),
    Room("stream", "Underground Stream", 1, 2,
         "A fast, cold stream cuts across the floor and vanishes under the east wall. There is a plank "
         "laid over it. Ways west, east, and south along the bank.",
         "The Underground Stream. The water is very loud."),
    Room("junction", "The Junction", 2, 2,
         "Four ways meet under a vaulted ceiling. Someone long dead has scratched arrows into the "
         "stone, all of them pointing east.",
         "The Junction. The scratched arrows point east."),
    Room("gallery", "Statue Gallery", 3, 2,
         "A long gallery of kneeling stone figures, all facing a great statue of a crowned king. The "
         "king's outstretched hand holds an empty socket, about the size of a fist.",
         "The Statue Gallery. The crowned king waits with an empty hand."),
    Room("irondoor", "Iron Door Chamber", 4, 2,
         "A bare stone room. A heavy iron door fills the west wall, banded and bolted. Other ways lead "
         "north and south.",
         "The Iron Door Chamber."),

    Room("shrine", "Sunken Shrine", 1, 3,
         "A shrine drowned to the knee in still water. On the altar, above the waterline, a silver "
         "amulet lies exactly where it was set down.",
         "The Sunken Shrine. Still water, silver light."),
    Room("crypt", "Crypt of Kaldrath", 2, 3, dark=True,
         desc="A low crypt of black stone. A single sarcophagus stands open-lidded at the centre, and "
              "the air is so cold it aches in your teeth.",
         brief="The Crypt of Kaldrath. Bitterly cold."),
    Room("whispers", "Hall of Whispers", 3, 3,
         "A round hall where the echoes come back wrong, half a second late and in someone else's "
         "voice. Ways lead north, west, east and south.",
         "The Hall of Whispers. Your own footsteps answer you."),
    Room("lab", "Alchemist's Lab", 4, 3,
         "A workbench of cracked glass and dried residue. One vial has survived, stoppered, full of "
         "something green that is still eating its way through the glass.",
         "The Alchemist's Lab."),

    Room("nest", "Spider Nest", 0, 4,
         "A chamber roofed and floored in old web. Wrapped shapes hang from the ceiling like fruit. "
         "One of them has a gilded skull where its head should be.",
         "The Spider Nest. The wrapped shapes turn slowly."),
    Room("webtunnel", "Web Tunnel", 1, 4,
         "A tunnel choked with a curtain of grey web, thick as rope, sealing the way west. The way "
         "east is clear.",
         "The Web Tunnel."),
    Room("ossuary", "Ossuary", 2, 4, dark=True,
         desc="Every wall of this room is stacked, floor to ceiling, with sorted human bone. Skulls "
              "make the arches. Ways north, west and east.",
         brief="The Ossuary. Stacked bone on every side."),
    Room("sill", "Molten Sill", 3, 4, heat=12,
         desc="A ledge above a seam of moving rock, dull red and slowly turning over. The heat comes up "
              "at you in a solid wall. You cannot stand here long. A sealed door lies east.",
         brief="The Molten Sill. The heat is unbearable."),
    Room("vault", "The Vault", 4, 4, dark=True,
         desc="The vault of Kaldrath: a small cold room, absolutely silent, and in the middle of it, on "
              "a plinth of black glass, the Crown.",
         brief="The Vault. The plinth stands at the centre."),
]

ITEMS = [
    Item("rope", "coil of tarred rope", ("rope", "coil", "tarred rope", "cord"), "cistern",
         "Forty feet of tarred rope, stiff with age but sound."),
    Item("fungus", "clutch of glowing fungus", ("fungus", "mushroom", "mushrooms", "glowing fungus",
         "light", "lamp", "torch"), "grotto",
         "A handful of cold pale light. It will not go out."),
    Item("sword", "iron short sword", ("sword", "short sword", "blade", "iron sword"), "armory",
         "Rusted, but the edge is still an edge."),
    Item("keys", "ring of rusted keys", ("keys", "key ring", "rusted keys", "ring", "iron key",
         "rusted key"), "guardpost",
         "Three keys on a ring. Two are rust. One is not."),
    Item("charm", "bone charm", ("charm", "bone charm", "bone", "amulet of bone", "fist"), "bonepit",
         "A fist-sized knot of carved bone on a cord. It is warm.", treasure=100),
    Item("amulet", "silver amulet", ("amulet", "silver amulet", "necklace", "pendant"), "shrine",
         "Silver, untarnished, cut with a closed eye.", treasure=150),
    Item("acid", "vial of green acid", ("acid", "vial", "green acid", "potion", "flask"), "lab",
         "Stoppered glass. Whatever is in it is winning."),
    Item("brass_key", "small brass key", ("brass key", "small key", "brass"), None,
         "A brass key, bright as the day it was cut."),
    Item("skull", "gilded skull", ("skull", "gilded skull", "gold skull"), "nest",
         "A human skull under a skin of gold leaf.", treasure=300),
    Item("crown", "Crown of Kaldrath", ("crown", "crown of kaldrath", "the crown"), "vault",
         "A thin circle of dark metal. It is much heavier than it looks.", treasure=1000),
]

MONSTERS = [
    Monster("skeleton", "skeleton sentry", ("skeleton", "sentry", "guard", "bones"),
            "guardpost", beaten_by=("sword",), warded_by=(), damage=15, dormant=True,
            intro="The skeleton sentry is standing now, and it has noticed you.",
            threat="The sentry's rusted blade comes down on your shoulder.",
            death="You take the skeleton apart at the neck and it falls into a heap of mail and bone."),
    Monster("rats", "swarm of rats", ("rats", "rat", "swarm", "vermin"),
            "warren", beaten_by=("sword",), warded_by=("fungus",), damage=6,
            intro="The floor moves. Rats, hundreds of them, pouring off the walls toward you.",
            threat="The rats are on your boots and up your legs, biting.",
            death="You lay about you with the sword until the survivors break and pour away into the walls."),
    Monster("spider", "great grey spider", ("spider", "great spider", "grey spider"),
            "nest", beaten_by=("sword", "acid"), warded_by=(), damage=22,
            intro="Something the size of a dog drops out of the ceiling and lands between you and the door.",
            threat="The spider gets a leg around you and its jaws find your arm.",
            death="The spider curls up around the wound and stops moving."),
    Monster("wight", "wight of Kaldrath", ("wight", "ghost", "king", "corpse", "dead king"),
            "crypt", beaten_by=(), warded_by=("amulet",), damage=30,
            intro="The cold in the crypt gathers itself, stands up out of the sarcophagus, and looks at you.",
            threat="The wight lays a hand on your chest and the warmth goes out of you.",
            death="The wight comes apart like smoke in a draught."),
]

DOORS = [
    Door("entrance", "corridor"),
    Door("corridor", "guardpost"),
    Door("guardpost", "arch"),
    Door("arch", "warren"),
    Door("entrance", "cistern"),
    Door("cistern", "grotto"),
    Door("guardpost", "armory"),
    Door("warren", "bonepit", blocked_by="shaft",
         barrier_text="The shaft drops away into the dark. Without a rope you would break both legs."),
    Door("grotto", "stream"),
    Door("stream", "junction"),
    Door("armory", "junction"),
    Door("junction", "gallery"),
    Door("gallery", "irondoor", key="keys",
         locked_text="The iron door is locked, and it is not the kind of door you argue with."),
    Door("bonepit", "irondoor"),
    Door("stream", "shrine"),
    Door("gallery", "whispers", secret=True),
    Door("whispers", "crypt"),
    Door("whispers", "lab"),
    Door("whispers", "sill"),
    Door("irondoor", "lab"),
    Door("crypt", "ossuary"),
    Door("ossuary", "webtunnel"),
    Door("webtunnel", "nest", blocked_by="webs",
         barrier_text="The curtain of web seals the tunnel completely. Rope-thick and sticky."),
    Door("ossuary", "sill"),
    Door("sill", "vault", key="brass_key",
         locked_text="The vault door has no handle, only a small brass keyhole."),
]

START_ROOM = "entrance"
GOAL_ITEM = "crown"
START_HEALTH = 100

# Lookup tables built once at import.
ROOMS_BY_KEY = {r.key: r for r in ROOMS}
ITEMS_BY_KEY = {i.key: i for i in ITEMS}
MONSTERS_BY_KEY = {m.key: m for m in MONSTERS}
