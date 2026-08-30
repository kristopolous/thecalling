"""Sessions tie one browser tab to one phone call, and remember past runs.

A browser tab creates a session and shows its four digit code. The caller reads
or keys that code in, which binds the live call to the tab. From then on every
turn of the game is pushed to the tab over SSE.
"""

import json
import os
import queue
import random
import threading
import re
import time

from engine import GameState
from world import ROOMS_BY_KEY

RUNS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs.json")
SESSION_TTL = 60 * 60 * 3   # forget idle sessions after three hours
MAX_GHOSTS = 12


def last4(phone):
    """The last four digits of a phone number -- the key a session is filed under.

    A caller is recognised by their caller ID, so the code on screen is simply
    the tail of the number they will be calling from. Nothing to read out.
    """
    digits = re.sub(r"\D", "", str(phone or ""))
    return digits[-4:] if len(digits) >= 4 else None


class Session:
    def __init__(self, code):
        self.code = code            # the last four digits of the player's phone
        self.created = time.time()
        self.touched = time.time()
        self.player_name = None
        self.call_id = None
        self.phone = None           # what the player typed on the page
        self.game = None
        self.transcript = []        # [{"who": "player"|"dungeon", "text": ..., "t": ...}]
        self.narrator = None        # set while a call is up: speak an unprompted line
        self.ender = None           # set while a call is up: say a last line, then hang up
        self.turn = threading.Lock()  # the caller and the Wanderer both move the world
        self._subscribers = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------- lifecycle

    def start_game(self, player_name=None):
        if player_name:
            self.player_name = player_name
        self.game = GameState(self.player_name or "Someone")
        self.transcript = []
        self.touched = time.time()
        return self.game

    def bind_call(self, call_id):
        self.call_id = call_id
        self.touched = time.time()

    def unbind_call(self):
        self.call_id = None
        self.narrator = None
        self.ender = None
        self.touched = time.time()

    @property
    def connected(self):
        return self.call_id is not None

    # ------------------------------------------------------------ transcript

    def say(self, who, text):
        if not text:
            return
        self.transcript.append({"who": who, "text": text, "t": round(time.time(), 2)})
        del self.transcript[:-200]
        self.touched = time.time()

    # ---------------------------------------------------------- subscription

    def subscribe(self):
        q = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self):
        payload = json.dumps(self.state())
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass

    # ---------------------------------------------------------------- state

    def state(self):
        return {
            "code": self.code,
            "connected": self.connected,
            "player_name": self.player_name,
            "phone": self.phone,
            "transcript": self.transcript[-40:],
            "game": self.game.snapshot() if self.game else None,
        }


class SessionStore:
    def __init__(self):
        self._by_code = {}
        self._by_call = {}
        self._lock = threading.Lock()
        self.runs = self._load_runs()

    # -------------------------------------------------------------- sessions

    def create(self):
        with self._lock:
            self._reap()
            for _ in range(200):
                code = f"{random.randint(0, 9999):04d}"
                if code not in self._by_code:
                    break
            else:
                raise RuntimeError("no free session codes")
            session = Session(code)
            session.start_game()
            self._by_code[code] = session
            return session

    def claim(self, phone, name=None):
        """Reserve the session for a phone number. Returns (session, error)."""
        code = last4(phone)
        if code is None:
            return None, "That does not look like a phone number."
        with self._lock:
            self._reap()
            session = self._by_code.get(code)
            if session is None:
                session = Session(code)
                session.start_game()   # so the map is alive while they dial
                self._by_code[code] = session
            elif session.connected:
                # Someone is mid-call on this number; do not pull the rug out.
                return session, None
        session.phone = phone
        if name:
            session.player_name = name
        session.touched = time.time()
        return session, None

    def get(self, code):
        session = self._by_code.get((code or "").strip())
        if session:
            session.touched = time.time()
        return session

    def live_games(self):
        """Sessions with a run in progress -- the ones the Wanderer walks in."""
        with self._lock:
            sessions = list(self._by_code.values())
        return [s for s in sessions if s.game is not None and s.game.alive]

    def by_call(self, call_id):
        return self._by_call.get(call_id)

    def bind(self, code, call_id):
        session = self.get(code)
        if session is None:
            return None
        with self._lock:
            if session.call_id:
                self._by_call.pop(session.call_id, None)
            session.bind_call(call_id)
            self._by_call[call_id] = session
        return session

    def bind_caller(self, from_number, call_id):
        """Bind by caller ID -- the normal path. None if nobody claimed that number."""
        code = last4(from_number)
        return self.bind(code, call_id) if code else None

    def release(self, call_id):
        with self._lock:
            session = self._by_call.pop(call_id, None)
        if session:
            session.unbind_call()
            session.publish()
        return session

    def _reap(self):
        cutoff = time.time() - SESSION_TTL
        for code, session in list(self._by_code.items()):
            if session.touched < cutoff and not session.connected:
                del self._by_code[code]

    # ------------------------------------------------------------ past runs

    def _load_runs(self):
        try:
            with open(RUNS_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _save_runs(self):
        tmp = RUNS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.runs[-200:], f, indent=1)
        os.replace(tmp, RUNS_FILE)

    def record_run(self, session):
        """Save a finished (or abandoned) run so later players can race its ghost."""
        game = session.game
        if game is None or not game.path or game.moves == 0:
            # Sessions open a game on page load so the Wanderer has somewhere to
            # walk. A run nobody actually played does not belong on the board.
            return None
        deepest = game.room
        finished = time.time()
        run = {
            "id": f"{finished:.3f}-{session.code}",
            "name": session.player_name or f"Caller {session.code}",
            "outcome": game.outcome or "lost",
            "score": game.score(),
            "elapsed": round(game.elapsed, 1),
            "moves": game.moves,
            "rooms": len(game.visited),
            "deepest_room": deepest,
            "deepest_room_name": ROOMS_BY_KEY[deepest].name,
            "path": [[room, t] for room, t in game.path],
            "finished_at": finished,
        }
        with self._lock:
            # Re-read first: the test harness and the server are separate
            # processes, and each was otherwise rewriting the whole file from
            # its own in-memory copy, dropping the other's runs.
            on_disk = self._load_runs()
            known = {r.get("id") for r in self.runs}
            for r in on_disk:
                if self._identify(r)["id"] not in known:
                    self.runs.append(r)
            self.runs.sort(key=lambda r: r.get("finished_at", 0))
            self.runs.append(run)
            self._save_runs()
        return run

    def _identify(self, run):
        """Older saved runs predate run ids; give them one so colours stay stable."""
        if "id" not in run:
            run["id"] = f"{run.get('finished_at', 0):.3f}-{run.get('name', '?')}"
        return run

    def leaderboard(self):
        """Best runs first: escapes beat deaths, then score, then speed."""
        def rank(r):
            return (0 if r["outcome"] == "escaped" else 1, -r["score"], r["elapsed"])
        return [{k: v for k, v in self._identify(r).items() if k != "path"}
                for r in sorted(self.runs, key=rank)[:MAX_GHOSTS]]

    def summary(self):
        escaped = [r for r in self.runs if r["outcome"] == "escaped"]
        return {
            "runs": len(self.runs),
            "escaped": len(escaped),
            "best_time": min((r["elapsed"] for r in escaped), default=None),
        }

    def ghosts(self):
        """Trails to draw on the map: the most recent runs, plus the best one.

        These come from the raw run records, not from leaderboard(), which
        strips the path to keep the dashboard payload small.
        """
        def rank(r):
            return (0 if r["outcome"] == "escaped" else 1, -r["score"], r["elapsed"])
        recent = sorted(self.runs, key=lambda r: -r["finished_at"])[:6]
        best = sorted(self.runs, key=rank)[:1]
        seen, out = set(), []
        for r in best + recent:
            marker = self._identify(r)["id"]
            if marker in seen:
                continue
            seen.add(marker)
            out.append({
                "id": self._identify(r)["id"],
                "name": r["name"],
                "outcome": r["outcome"],
                "elapsed": r["elapsed"],
                "score": r["score"],
                "deepest_room": r["deepest_room"],
                "deepest_room_name": r["deepest_room_name"],
                "path": [p[0] for p in r["path"]],
            })
        return out


STORE = SessionStore()
