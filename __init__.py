"""
Focus Friends
A little study companion who keeps you company: a daily-count mood ladder,
a buddy during reviews, run-across-screen at high moods, speech-bubble
dialogue, and a recall timer. The active voice is Kawaii.

See README.md for an overview and config.md for the settings reference.

Character animation strips are bundled under img/ as horizontal PNG and WebP
strips; the active profile selects the files and frame sizes used at runtime.
"""

import base64
import html
import json
import os
import random
import re
import time
from datetime import date

from aqt import mw, gui_hooks
from aqt.qt import (
    QAction,
    QButtonGroup,
    QCheckBox,
    QColor,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QIcon,
    QPixmap,
    QPushButton,
    QScrollArea,
    QSlider,
    QSize,
    QSpinBox,
    QTabWidget,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QPainter,
    QPen,
    QFont,
    QRectF,
    QWidget,
    Qt,
    sip,
)

ADDON_DIR = os.path.dirname(__file__)
USER_FILES = os.path.join(ADDON_DIR, "user_files")
STATE_PATH = os.path.join(USER_FILES, "state.json")
ADDON_NAME = "Focus Friends"
# Card templates may set a different page font. Keep buddy UI consistent with
# the system font used by the timer and the original appearance preview.
BUDDY_FONT_CSS = "font-family:-apple-system,BlinkMacSystemFont,sans-serif !important;"

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
FRAME_SECONDS = 0.16          # per sprite frame (Lumi cells are bigger, slightly slower feels better)
SAD_SPEED_FACTOR = 1.10       # make sad loops a little more measured for every buddy


def _sprite_frame_seconds(name: str) -> float:
    """Per-frame animation time, with a slightly slower beat for sad poses."""
    return FRAME_SECONDS * SAD_SPEED_FACTOR if name == "failed" else FRAME_SECONDS
SWAP_INTERVAL_MIN_MS = 5000
SWAP_INTERVAL_MAX_MS = 10000
REACTION_HOLD_MS = 2000
BUBBLE_MIN_MS = 3000     # minimum on-screen time for every speech bubble
# Home-screen run cycle: pose, then one leg of travel, turn, travel back, repeat.
RUN_TRAVEL_PX = 46       # how far they cover per leg
RUN_LEG_MS = 1700        # one leg's duration, so travel is smooth and readable
RUN_POSE_MS = 2600       # how long they hold a pose between runs
_POS_MSG_PREFIX = 'studybuddy_pos:'   # drag reports come back over Anki's pycmd bridge
_TIMER_POS_MSG_PREFIX = 'studybuddy_timer_pos:'
RECOVERY_HOLD_MS = 3000   # the 'they're okay again' celebration lingers

EASTER_CLICK_COUNT = 5
EASTER_CLICK_WINDOW_MS = 1500
EASTER_EXCITED_HOLD_MS = 2000
EASTER_HOLD_MS = 3000

# Lumi cells are 192x208 (not 32x32 like the cat).
FRAME_W, FRAME_H = 192, 208

def _qt_enum(group: str, name: str):
    """Qt6 scopes its enums (Qt.AlignmentFlag.AlignCenter) while Qt5 kept them
    flat. Resolve whichever this Anki's Qt exposes, so the add-on loads on both."""
    scoped = getattr(Qt, group, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)
    return getattr(Qt, name, None)


_ALIGN_CENTER = _qt_enum("AlignmentFlag", "AlignCenter")
_KEEP_ASPECT = _qt_enum("AspectRatioMode", "KeepAspectRatio")
_SMOOTH_TRANSFORM = _qt_enum("TransformationMode", "SmoothTransformation")

# Character preview playground in Settings -> General.
PREVIEW_W, PREVIEW_H = 176, 190
PREVIEW_MODES = (
    ("idle", "Idle"), ("review", "Thinking"), ("sad", "Sad"), ("jumping", "Jumping"),
    ("waving", "Waving"), ("running_left", "Run left"),
    ("running_right", "Run right"),
)

# Buddy on the cards screen (bottom-right corner while reviewing).
# Default display size; adjustable via mini_size in settings.
MINI_WIDTH = 180
_focus_seconds_left = 0
_focus_timer = None
_focus_waiting_to_begin = False
_TIMER_START_MSG = "studybuddy_timer_start"


def _mini_width() -> int:
    return int(get_config().get("mini_size", MINI_WIDTH))


def _focus_seconds() -> int:
    return max(1, int(get_config().get("focus_seconds", DEFAULT_CONFIG["focus_seconds"])))


def _recovery_reviews() -> int:
    return max(1, int(get_config().get("recovery_reviews", DEFAULT_CONFIG["recovery_reviews"])))


def _hardcore_misses() -> int:
    return max(1, int(get_config().get("hardcore_misses", DEFAULT_CONFIG["hardcore_misses"])))


def _hardcore_recovery() -> int:
    return max(1, int(get_config().get("hardcore_recovery", DEFAULT_CONFIG["hardcore_recovery"])))


def _hardcore_on() -> bool:
    return bool(get_config().get("hardcore_mode", DEFAULT_CONFIG["hardcore_mode"]))


def _bubble_font_size() -> int:
    return max(8, min(28, int(get_config().get("bubble_font_size", DEFAULT_CONFIG["bubble_font_size"]))))


def _chatter_chance() -> float:
    pct = max(0, min(100, int(get_config().get("chatter_percent", DEFAULT_CONFIG["chatter_percent"]))))
    # Older configs may contain arbitrary values, including 100. Keep runtime
    # behavior aligned with the Rarely/Sometimes/Often choices in Settings.
    return BUBBLE_FREQUENCIES[_nearest_frequency_key(pct)]["percent"] / 100.0


def _talk_style_key() -> str:
    return "kawaii"


def _talk_style() -> dict:
    """Return the only currently available dialogue pack."""
    return TALK_STYLES["kawaii"]


# Frequency applies to optional rating reactions, shown right after the rating.
# Greetings and recovery messages are not randomized by this setting.
BUBBLE_FREQUENCIES = {
    "rarely": {"label": "Rarely", "percent": 5, "rate": "about 1 message opportunity in 20"},
    "sometimes": {"label": "Sometimes  (recommended)", "percent": 30, "rate": "about 1 message opportunity in 3"},
    "often": {"label": "Often", "percent": 50, "rate": "about 1 message opportunity in 2"},
}


def _nearest_frequency_key(percent: int) -> str:
    """Map any stored percentage onto the closest named band, so an older config
    that saved an arbitrary number still lands somewhere sensible."""
    return min(BUBBLE_FREQUENCIES, key=lambda k: abs(BUBBLE_FREQUENCIES[k]["percent"] - percent))


def _bubble_frequency_key() -> str:
    return _nearest_frequency_key(
        int(get_config().get("chatter_percent", DEFAULT_CONFIG["chatter_percent"]))
    )


# ---------------------------------------------------------------------------
# Lumi sprite strips: name -> (basename, frame_count, loop)
# ---------------------------------------------------------------------------
LUMI_SPRITE_FILES = {
    "idle": ("LumiIdle", 7, True),
    "waiting": ("LumiWaiting", 6, True),
    "review": ("LumiReview", 6, True),
    "failed": ("LumiFailed", 8, True),
    "jumping": ("LumiJumping", 5, True),
    "waving": ("LumiWaving", 4, True),
    "running": ("LumiRunning", 6, True),
    "running_right": ("LumiRunningRight", 8, True),
    "running_left": ("LumiRunningLeft", 8, True),
    "look_a": ("LumiLookA", 8, True),
    "look_b": ("LumiLookB", 8, True),
}

# Yuuhi's included atlas is 8 columns by 9 rows, with the same 192x208
# cells as Lumi. The rows are split into small PNG strips in img/yuuhi.
PET_PROFILES = {
    "lumi": {
        "label": "Lumi",
        "default_name": "Lumi",
        "sprites": LUMI_SPRITE_FILES,
    },
    "yuuhi": {
        "label": "Yui",
        "default_name": "Yui",
        "sprites": {
            "idle": ("YuuhiIdle", 6, True),
            "waiting": ("YuuhiWaiting", 6, True),
            "review": ("YuuhiReview", 6, True),
            "failed": ("YuuhiFailed", 8, True),
            "jumping": ("YuuhiJumping", 5, True),
            "waving": ("YuuhiWave", 4, True),
            "running": ("YuuhiRunRight", 8, True),
            "running_right": ("YuuhiRunRight", 8, True),
            "running_left": ("YuuhiRunLeft", 8, True),
            "look_a": ("YuuhiIdleAltA", 6, True),
            "look_b": ("YuuhiIdleAltB", 6, True),
        },
    },
    "yuuhi_sailor": {
        "label": "Yuzu",
        "default_name": "Yuzu",
        "frame_size": (384, 416),
        "sprites": {
            "idle": ("pet_yuuhi_sailor_idle", 6, True),
            "waiting": ("pet_yuuhi_sailor_waiting", 6, True),
            "review": ("pet_yuuhi_sailor_review", 6, True),
            "failed": ("pet_yuuhi_sailor_sad", 8, True),
            "jumping": ("pet_yuuhi_sailor_jump", 5, True),
            "waving": ("pet_yuuhi_sailor_wave", 4, True),
            "running": ("pet_yuuhi_sailor_run", 8, True),
            "running_right": ("pet_yuuhi_sailor_run", 8, True),
            "running_left": ("pet_yuuhi_sailor_runleft", 8, True),
            "look_a": ("pet_yuuhi_sailor_look_a", 6, True),
            "look_b": ("pet_yuuhi_sailor_look_b", 6, True),
        },
    },
}

# The additional character sheets share an 8-column, 192x208-cell layout.
# Their active animation rows are bundled as transparent WebP strips in
# img/pets so review cards only embed the frames they use.
STANDARD_PET_NAMES = {
    "rin": "Kano",
    "chitose": "Sakia",
    "eru": "Momo",
    "firefly": "Kokona",
    "hatsune": "Soyo",
    "kurumi": "Suzuka",
    "mizuno": "Yume",
    "nezuko": "Demon Girl",
    "shinobu": "Butterfly Girl",
    "tifa": "Fighter Girl",
    "yanami": "Megumi",
}


def _standard_pet_sprites(slug: str) -> dict:
    extended = slug in {"tifa", "kurumi", "hatsune"}
    seven_idle = slug in {"tifa", "hatsune"}
    sprites = {
        "idle": (f"pet_{slug}_idle", 7 if seven_idle else 6, True),
        "waiting": (f"pet_{slug}_waiting", 6, True),
        "review": (f"pet_{slug}_review", 6, True),
        "failed": (f"pet_{slug}_sad", 8, True),
        "jumping": (f"pet_{slug}_jump", 5, True),
        "waving": (f"pet_{slug}_wave", 4, True),
        "running": (f"pet_{slug}_run", 8, True),
        "running_right": (f"pet_{slug}_run", 8, True),
        "running_left": (f"pet_{slug}_runleft", 8, True),
        "look_a": (f"pet_{slug}_look_a", 8, True) if extended else (f"pet_{slug}_waiting", 6, True),
        "look_b": (f"pet_{slug}_look_b", 8, True) if extended else (f"pet_{slug}_look", 6, True),
    }
    if slug == "nezuko":
        # The updated Demon Girl sheet has a separate six-frame side-running row.
        sprites["running"] = ("pet_nezuko_run_alt", 6, True)
    elif slug == "kurumi":
        # The replacement sheet uses five sad frames and eight thinking
        # frames, plus six frames for each alternate look animation.
        sprites["failed"] = ("pet_kurumi_sad", 5, True)
        sprites["review"] = ("pet_kurumi_review", 8, True)
        sprites["look_a"] = ("pet_kurumi_look_a", 6, True)
        sprites["look_b"] = ("pet_kurumi_look_b", 6, True)
    return sprites


for _pet_slug, _pet_name in STANDARD_PET_NAMES.items():
    PET_PROFILES[_pet_slug] = {
        "label": _pet_name,
        "default_name": _pet_name,
        "sprites": _standard_pet_sprites(_pet_slug),
    }


PET_PROFILES["maid"] = {
    "label": "Miku",
    "default_name": "Miku",
    "sprites": {
        "idle": ("pet_maid_idle", 7, True),
        "waiting": ("pet_maid_waiting", 6, True),
        "review": ("pet_maid_review", 6, True),
        "failed": ("pet_maid_sad", 8, True),
        "jumping": ("pet_maid_jump", 5, True),
        "waving": ("pet_maid_wave", 4, True),
        "running": ("pet_maid_run", 8, True),
        "running_right": ("pet_maid_run", 8, True),
        "running_left": ("pet_maid_runleft", 8, True),
        "look_a": ("pet_maid_look_a", 8, True),
        "look_b": ("pet_maid_look_b", 8, True),
    },
}


# Picking a character switches to its matching voice, so the two never drift
# apart. Kawaii is the only active voice for every buddy.
def _pet_profile(character: str = None) -> dict:
    """`character` overrides the saved choice, so the settings preview can show a
    character the user has not saved yet."""
    key = character if character is not None else get_config().get("character", "lumi")
    return PET_PROFILES.get(key, PET_PROFILES["lumi"])


def _pet_frame_size(character: str = None) -> tuple:
    """Return the source cell dimensions for this character's animation strips."""
    profile = PET_PROFILES.get(character, PET_PROFILES["lumi"]) if character else _pet_profile()
    return profile.get("frame_size", (FRAME_W, FRAME_H))


def _sprite_spec(name: str) -> tuple:
    return _pet_profile()["sprites"][name]

ANIMATION_CATEGORIES = {
    "neutral": ["idle", "waiting", "review"],
    "sad": ["failed"],
    "happy": ["jumping", "waving"],
    "actions": ["running", "look_a", "look_b"],
    "run": ["running_right", "running_left", "running"],
}


def _animations(*categories: str) -> list:
    names = []
    for cat in categories:
        names.extend(ANIMATION_CATEGORIES[cat])
    return names


MINI_IDLE_POOL = _animations("neutral")
REACTION_POOL_GOOD = _animations("happy")
_last_celebration = {}


def _pick_celebration(include_run=True) -> str:
    key = get_config().get("character", "lumi")
    moves = ["jumping", "waving"] + (["run_around"] if include_run else [])
    available = [move for move in moves if move != _last_celebration.get(key)]
    move = random.choice(available or moves)
    _last_celebration[key] = move
    return move

# Idle weighting: they stand calm (idle) most of the time, with occasional
# waiting/review/look-around. Weights double as deck-browser rotation odds
# (via repetition) and mini idle picks.
IDLE_WEIGHTS = {"idle": 7, "waiting": 1, "review": 1, "look_a": 1, "look_b": 1}


def _pick_weighted(names: list, weights: list) -> str:
    return random.choices(names, weights=weights, k=1)[0]


def _pick_idle() -> str:
    names = list(IDLE_WEIGHTS)
    return _pick_weighted(names, [IDLE_WEIGHTS[n] for n in names])


# Look-around poses play through their cycle this many times, then they go
# back to calm idle (never loops non-stop).
LOOK_POSES = ("look_a", "look_b")
LOOK_CYCLES = 2
def _look_hold_ms(name="look_a") -> int:
    return int(round(LOOK_CYCLES * _sprite_spec(name)[1] * FRAME_SECONDS * 1000))

# ---------------------------------------------------------------------------
# Talking styles: a "little witch" set and a softer, themed-free "kawaii"
# rewrite of the same pools. Both are selectable from Tools → Settings.
# ---------------------------------------------------------------------------
KAWAII_ENCOURAGEMENT_LINES = [
    "Eep, this little card slipped away! We'll catch it next time, okay? 🥺💕",
    "It's okay! One teeny-tiny try is still a try 🌸",
    "This card needs one more visit—and maybe a tiny snack 🍓",
    "That answer went on a little walk. We'll meet it again! 🐾",
    "Oopsie-daisy! Let's tuck this one into our practice pile 🎀",
    "Not quite yet, but you're still doing lovely work! ✨",
    "One more peek next time, and we'll be even closer 💖",
    "That was a tricky bean! 🫘",
    "Every little try helps this memory find its way home 🏡💕",
    "That card is playing hide-and-seek. We'll find it! 🙈",
    "Fresh try next time! Your brain's still collecting sparkles 🌟",
    "That's okay! Practice tiny steps (in a cute outfit) 🌷",
    "One tiny stumble, zero reason to worry 🐣",
    "We'll give this wiggly little memory another chance 💗",
]

KAWAII_REVIEW_LINES = [
    "You remembered! My tiniest happy dance is for you! 💃💕",
    "Yay! A little memory popped right into place ✨",
    "I'm so proud of you! Pocket-sized sparkle delivery! 🌟",
    "That answer was hiding, and you found it! 🔎💖",
    "A perfect little brain-sparkle! Please keep it ✨",
    "Look at you go, you brilliant little star! ⭐",
    "That deserves one teeny-tiny round of applause 👏🌸",
    "Memory found! Sending it home with a ribbon 🎀",
    "You did it! My heart just went boop! 💗",
    "One more lovely answer tucked into your brain basket 🧺💕",
    "A little victory, wrapped up with a bow 🎁",
    "Your brain brought that one back so nicely! 🧠✨",
    "Yippee! The happy wiggle has been activated! 🐣",
    "That was as lovely as a strawberry cupcake 🍓",
    "You remembered! Please accept this sparkly gold star 🌟",
    "A sweet little success! Let's put it on the shelf 💖",
    "Boop! You knew that one right away! ☝️💗",
    "Look at you go, little superstar! 🌟",
    "That answer was already snuggled up in your brain 💤💞",
    "Easy-peasy! Your memory had its shoes on and ready 👟✨",
    "You knew it before the little card could blink! 😉💕",
    "A smooth little answer, delivered with a bow 🎀",
    "Your brain said, ‘Oh, this one? Got it!’ 🧠🌸",
    "That one came right home to your memory 🏡💖",
    "So quick! I barely had time to do my happy wiggle 🐣",
    "A familiar little friend, remembered perfectly 🌷",
    "You made that look as easy as picking a flower 🌼",
    "Your memory is wearing its sparkliest socks today 🧦✨",
]

KAWAII_HARD_LINES = [
    "Ooh, that one was slippery! You still caught it! 🐾💕",
    "A tricky little bean, but you brought it back! 🫘✨",
    "That took extra brain sparkle. You did it! 🧠🌟",
    "Phew! That answer needed its tiny hiking boots 🥾💖",
    "A wobbly win is still a wonderful win 🌷",
    "You worked so hard for that one—gold star for you! ⭐",
    "That memory was playing hide-and-seek. Found it! 🙈",
    "A little tricky, a little triumphant, very much you 💕",
    "You untangled that answer like a clever kitten 🐱✨",
    "That one took courage and a sprinkle of brain power 🌸",
    "Hard-earned answer! Let's tuck it into the treasure box 💎",
    "Your brain did a brave little stretch for that one 🧠💗",
]

KAWAII_DIALOGUE = {
    "drained": [
        "Hiii. I saved you the softest little study spot 🧸",
        "We can start tiny. One card is a lovely start 🌱",
        "I'll keep you company while your brain wakes up ☀️💕",
        "No rush, sweet pea. I'm happy you're here 🌸",
        "A cozy hello and one little card? 🐣",
    ],
    "sad": [
        "Let's warm up with one teeny-tiny win 🌷",
        "I'm right here, cheering in a very small voice 💕",
        "One little card can brighten the whole pile ✨",
        "We can find our rhythm together, nice and easy 🎶",
        "Sending your brain a gentle pep-pat 🐾💖",
    ],
    "neutral": [
        "A little rhythm, a little sparkle, a lovely start 🌸",
        "Look at us, collecting tiny memories together 🧺💕",
        "Your brain is doing its best little dance 🧠💃",
        "One card at a time, one star at a time ⭐",
        "I'm practicing my most encouraging nod. How's this? 😊",
    ],
    "happy": [
        "Your progress is blooming like a little flower 🌼💕",
        "I can barely contain my happy wiggles! 🐣✨",
        "Look at all those memories finding their way home 🏡",
        "Today's study pile is getting a sprinkle of magic 🌟",
        "You showed up for yourself, and that's lovely 💖",
    ],
    "excited": [
        "So many wins! My heart is doing zoomies! 💗🐾",
        "A whole sky full of tiny study stars! 🌟🌟🌟",
        "Your progress needs its own little celebration parade 🎉",
        "I am your very proud Focus Friend 🥹💕",
        "Sparkles everywhere! We did such lovely work ✨🌸",
    ],
}

# A soft, playful little witch. Lines are selected by review event.
LITTLE_WITCH_GREETING = [
    "there you are~ i warmed up the cauldron. 🌙",
    "hat on, spellbook open. shall we?",
    "a little memory magic together? ✨",
    "i saved you the comfy seat by the spellbook.",
    "hi hi~ let's see which spells we remember. ♡",
    "one small spell to start us off?",
    "wand ready! mostly pointing the right way.",
    "come along~ our little lesson is waiting. 🌷",
    "i brought the stardust. you bring the remembering~",
    "okay~ first page, fresh little spell.",
]

LITTLE_WITCH_REVEAL = [
    "spellbook says... this one! 🌙",
    "a little reveal~ did it match your thought?",
    "peek beneath the sparkles. how close were you? ✨",
    "there's the answer~ shall we check your spell?",
    "hmm~ does that incantation look familiar?",
    "one small peek inside the grimoire. ♡",
    "the answer has emerged from the cauldron~",
    "let's compare our notes before the next spell.",
    "a page turned~ what do you think? 🌷",
    "no crystal ball needed. just a little look~",
    "there it is~ remembered, or worth another visit?",
    "the spellbook is open. take a moment, little scholar.",
]

LITTLE_WITCH_HAPPY = [
    "a little spell, neatly cast! ✨",
    "hehe~ that's a keeper for our spellbook.",
    "my wand did a tiny happy wiggle. ♡",
    "one more memory in the potion jar~",
    "ooh~ you remembered the incantation!",
    "a gold star, straight from my hat. ⭐",
    "that deserves a very small broomstick dance.",
    "another little spark caught safely~",
    "spell successful. hat still attached!",
    "a pinch of practice, a little bit of magic. 🌷",
    "nicely remembered~ the cauldron approves.",
    "i'll mark that page with a tiny moon. 🌙",
    "one more for our growing grimoire~",
    "hehe~ a tidy little bit of witchcraft.",
    "please accept this pocket-sized sparkle. ✨",
    "that memory came when you called it~",
]

LITTLE_WITCH_HARD = [
    "a tricky incantation~ but you found it. 🌙",
    "that spell needed a little extra stirring.",
    "a wobbly little spark is still a spark. ♡",
    "phew~ that page made us work for it.",
    "not quite a comfy spell yet. we'll practise~",
    "a little more rehearsal for this incantation.",
    "you untangled that one~ nicely done. ✨",
    "a hard-earned little star for the spellbook.",
]

LITTLE_WITCH_EASY = [
    "ohh~ that spell knows its way home. ✨",
    "you hardly needed the spellbook for that one~",
    "a familiar little incantation. ♡",
    "that one practically hopped onto your wand!",
    "a comfy spell, like your favourite slippers.",
    "hehe~ this page has been well practised. 🌙",
    "a smooth little swish of the wand~",
    "a lovely familiar spell. shall we turn the page?",
]

LITTLE_WITCH_FAILURE = [
    "a little fizzle~ shall we try that spell again? 🌷",
    "oops~ this page needs another visit.",
    "even little witches rehearse their spells. ♡",
    "that incantation got its shoelaces tangled.",
    "back into the practice cauldron with this one~",
    "a tiny poof. nothing a little practice can't help.",
    "let's give that page a little bookmark. 🌙",
    "hmm~ another stir, another try.",
    "the spellbook is allowed to have margin notes~",
    "this spell really likes an encore. ✨",
    "we'll get better acquainted, mysterious little card.",
    "a fresh little try when this one comes back~",
]

LITTLE_WITCH_STRICT = [
    "a few tangled spells~ let's start with just one. 🌙",
    "set the cauldron down. one little breath first~",
    "a tiny pause, then a fresh incantation. ♡",
    "quite a tricky chapter we've found.",
    "let's turn the next page a little more carefully~",
    "smaller spells for a moment. we can do those. 🌷",
]

LITTLE_WITCH_RECOVERY = [
    "all five hearts~ my wand is twinkling again! ✨",
    "there we are~ back to our little spellbook.",
    "hearts full. hat straight. ready! ♡",
    "a little practice brought the sparkle back.",
    "my happy dance has been re-enchanted~",
    "the cauldron's making happy little bubbles. 🌙",
    "a tiny recovery spell, one review at a time.",
    "all bright again~ shall we turn the page?",
    "wand recharged! please stand clear of tiny sparkles. ✨",
    "a full little heart bar. that's my favourite charm~",
]

LITTLE_WITCH_DIALOGUE = {
    "drained": [
        "the spellbook is open whenever you're ready. 🌙",
        "i kept a little candle burning for our lesson.",
        "one small spell would be a lovely start~",
        "a comfy seat and a curious little page. ♡",
    ],
    "sad": [
        "the cauldron's just warming up~",
        "little spells count too. 🌷",
        "we can begin with a single little spark.",
        "hat a little crooked. still ready to practise~",
    ],
    "neutral": [
        "our little spellbook is getting some use~",
        "a page at a time, a little magic at a time. ✨",
        "i've been practising my scholarly little nod.",
        "look at the sparks we've gathered. ♡",
    ],
    "happy": [
        "the cauldron's bubbling quite happily today. 🌙",
        "a lovely little collection of practised spells.",
        "i may need a bigger jar for these sparkles~",
        "a tiny broomstick dance seems appropriate. ✨",
    ],
    "excited": [
        "so many pages practised~ my hat nearly did a flip!",
        "our little grimoire has had quite a day. 🌟",
        "the happy-dance spell is getting lots of practice~",
        "a whole constellation of little victories. ♡",
    ],
}

LITTLE_WITCH_SPELL_TEXT = {
    "drained": "",
    "sad": "warming the little cauldron~",
    "neutral": "one page, one little spark ♡",
    "happy": "collecting pocket-sized magic ✨",
    "excited": "tiny celebration spell~",
}

KAWAII_STRICT_LINES = [
    "Oh, a few wobbly cards! Let's do one teeny step at a time, okay? 🥺🌷",
    "Tiny pause, big cozy breath. I'm right here with you 💕",
    "We can make this pile feel smaller—one little card at a time 🐣",
    "Let's give your brain a soft little reset and start fresh 🌸",
    "No need to rush, sweet pea. One card is plenty for right now 🍓",
    "Sending you a pocket-sized dose of courage 💌✨",
    "A tricky patch can't stop our tiny steps forward 💗",
    "Let's make the next step gentle and doable 🧸",
    "You deserve a kind little pause. Breathe with me? 🌷",
    "We can find our rhythm again, one cozy card at a time 🎶💕",
]

KAWAII_GREETING_LINES = [
    "Hiiii! I saved you the coziest little study spot! 🧸💕",
    "You're here! My heart just did a tiny flip! 💗",
    "Welcome back! Let's make some teeny-tiny progress 🌸",
    "Yay, it's study time! I brought my happy face ✨",
    "I've missed our little study dates! Ready when you are 🎀",
    "Your cards are ready, and so am I! 🌷",
    "Hello, sunshine! Let's collect a few little victories ☀️💕",
    "I made us a pretend cupcake for good luck 🧁",
    "Hiii! One cozy card at a time, together 🐣",
    "Welcome, welcome! Your Focus Friend is all ears 💖",
    "Let's open the card pile and sprinkle it with stardust 🌟",
    "There you are! I saved you a little spot beside me 🌸",
]

KAWAII_RECOVERY_LINES = [
    "My hearts are full again! I'm doing a sparkly wiggle! 💖✨",
    "You brought all my little hearts back! Thank youuu! 🥹💕",
    "All better! Come here for a tiny celebration hug! 🧸💗",
    "My heart-meter is glowing like a little night-light 🌙💖",
    "We did it! Time for the tiniest victory parade 🎉🐣",
    "All my hearts are home again, safe and snuggly 🏡💕",
    "I'm feeling bright as a bowl of strawberries 🍓✨",
    "Recovery complete! Please admire my happy wiggle 💃🌸",
    "You helped me feel all sparkly again. Thank you! 🌟",
    "Hearts: full! Smile: extra big! Ready: absolutely! 💗",
    "A little patience brought all my sparkle back 🎀✨",
    "We made it through together—I'm so happy! 🥹🌷",
    "You recovered me! My little heart is all yours again! 💗🥹",
    "I'm okay again because you came back for me! Thank youuu! 🧸💕",
    "My hearts are back, and I get to stay with you! Yayyy! 🌸💖",
    "You did it! You made me feel safe and sparkly again! ✨🥹",
    "I'm all better! Please accept one enormous tiny hug! 🤗💕",
    "You brought me back to happy! I could do a thousand heart-wiggles! 💞🐣",
    "We're together again, and my heart is doing happy little flips! 💗🎀",
    "You came back for me! I'm going to treasure this teeny victory! 🥹🌷",
    "All five little hearts are home! I missed being okay with you! 🏡💕",
]

KAWAII_TIMEOUT_LINES = [
    "Eep, time ran away! I'm down for a tiny rest, but I'm still with you 🥺🌸",
    "Oh! The timer went beep-beep! I need a little heart-rest now 💗⏰",
    "I got a teensy bit sleepy when the timer ran out… let's try again together 🥺💤",
    "Time's up! I'll be right here while my hearts refill 🌷💕",
    "Whoopsie, the seconds zoomed away! I'm okay—just need a little care 🐣💖",
    "The timer scooted past us! Let's bring my little hearts back together ⏰💞",
    "I tumbled into a tiny nap! A few cozy reviews will wake me up 🌙🧸",
    "B-bye for a little nap… I'll be cheering quietly while I recover 🥺🌸",
    "My timer bell rang! I'm a little wobbly, but we can do this together 🔔💕",
    "Oh no, the last second booped by! I'll feel better as we keep studying 💗✨",
    "I need a little heart recharge now! One card at a time, okay? 🔋💖",
    "Time got the zoomies! I'll rest here until you help me feel better 🐾💕",
]

KAWAII_SPELL_TEXT = {
    "drained": "",
    "sad": "one cozy card at a time 💕",
    "neutral": "tiny steps, growing smiles 🌱",
    "happy": "collecting little victories 🎀",
    "excited": "sparkle parade in progress ✨",
}

_sprite_data_uri_cache = {}


def _sprite_data_uri(path: str) -> str:
    if path not in _sprite_data_uri_cache:
        with open(path, "rb") as f:
            mime = "image/webp" if path.lower().endswith(".webp") else "image/png"
            _sprite_data_uri_cache[path] = f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")
    return _sprite_data_uri_cache[path]


def _sprite_path(basename: str) -> str:
    if basename.startswith("Yuuhi"):
        return os.path.join(ADDON_DIR, "img", "yuuhi", f"{basename}.png")
    if basename.startswith("pet_"):
        return os.path.join(ADDON_DIR, "img", "pets", f"{basename}.webp")
    return os.path.join(ADDON_DIR, "img", f"{basename}.png")


def sprite_html(name: str, width: int = 140, character: str = None) -> str:
    """Render one Lumi strip animation at the given display width."""
    basename, frames, loop = _pet_profile(character)["sprites"][name]
    frame_w, frame_h = _pet_frame_size(character)
    path = _sprite_path(basename)
    scale = width / frame_w
    height = frame_h * scale
    base_style = (
        f"width:{width}px; height:{height}px; margin:0 auto; "
        f"background-image:url({_sprite_data_uri(path)}); "
        f"background-repeat:no-repeat; image-rendering:auto;"
    )
    if frames <= 1:
        return f'<div style="{base_style} background-size:{width}px {height}px; background-position:0 0;"></div>'

    sheet_width = frame_w * frames * scale
    duration = round(frames * _sprite_frame_seconds(name), 2)
    anim_mode = "infinite" if loop else "1 forwards"
    keyframe_name = f"lumibuddySprite_{name}"
    return f"""
<div style="{base_style} background-size:{sheet_width}px {height}px;
            animation:{keyframe_name} {duration}s steps({frames}) {anim_mode};"></div>
<style>
@keyframes {keyframe_name} {{
  from {{ background-position: 0 0; }}
  to {{ background-position: -{sheet_width}px 0; }}
}}
</style>"""


# ---------------------------------------------------------------------------
# Mood ladder + dialogue / spell text
# ---------------------------------------------------------------------------
def _all_mood_tiers(cfg: dict) -> list:
    neutral_at = max(1, int(cfg.get("mood_neutral_at", DEFAULT_CONFIG["mood_neutral_at"])))
    happy_at = max(neutral_at + 1, int(cfg.get("mood_happy_at", DEFAULT_CONFIG["mood_happy_at"])))
    excited_at = max(happy_at + 1, int(cfg.get("mood_excited_at", DEFAULT_CONFIG["mood_excited_at"])))
    neutral_names = list(IDLE_WEIGHTS)
    neutral_weights = [IDLE_WEIGHTS[n] for n in neutral_names]
    style_names = MOOD_TIER_NAMES.get(_talk_style_key(), MOOD_TIER_NAMES["kawaii"])
    tier_names = style_names["tiers"]
    return [
        {"min": 0, "max": 1, "key": "drained", "label": tier_names["drained"][0], "emoji": tier_names["drained"][1], "color": "#7F8C8D", "pct": (0, 0), "pool": neutral_names, "weights": neutral_weights},
        {"min": 1, "max": neutral_at + 1, "key": "sad", "label": tier_names["sad"][0], "emoji": tier_names["sad"][1], "color": "#E74C3C", "pct": (5, 30), "pool": _animations("sad"), "weights": [1]},
        {"min": neutral_at + 1, "max": happy_at + 1, "key": "neutral", "label": tier_names["neutral"][0], "emoji": tier_names["neutral"][1], "color": "#3498DB", "pct": (30, 60), "pool": neutral_names, "weights": neutral_weights},
        {"min": happy_at + 1, "max": excited_at + 1, "key": "happy", "label": tier_names["happy"][0], "emoji": tier_names["happy"][1], "color": "#2ECC71", "pct": (60, 90), "pool": neutral_names + ["running"], "weights": neutral_weights + [2]},
        {"min": excited_at + 1, "max": None, "key": "excited", "label": tier_names["excited"][0], "emoji": tier_names["excited"][1], "color": "#F1C40F", "pct": (100, 100), "pool": _animations("happy"), "weights": [1, 1]},
    ]


def _current_mood_tier(cfg: dict, reviews: int) -> dict:
    tiers = _all_mood_tiers(cfg)
    for t in tiers:
        if (t["max"] is None or reviews < t["max"]) and reviews >= t["min"]:
            return t
    return tiers[-1]


def _mood_bar_percent(tier: dict, reviews: int) -> int:
    lo, hi = tier["pct"]
    if tier["max"] is None or lo == hi:
        return hi
    span = tier["max"] - tier["min"]
    frac = max(0.0, min(1.0, (reviews - tier["min"]) / span)) if span else 0.0
    return int(lo + (hi - lo) * frac)


# Said when a hardcore miss streak puts them out of sorts.
# Said once, on the first card when a review session opens.
# Said once, on the review that brings them back to okay after a timeout.
# Both styles share one lookup. Adding another is just another entry here.
# Mood tier names and the word on the progress bar change with the talking
# style, so the home screen never says "Spellcasting" while you have Kawaii on.
MOOD_TIER_NAMES = {
    "kawaii": {
        "tiers": {
            "drained": ("Sleepy", "😴"),
            "sad": ("Sad", "🥺"),
            "neutral": ("Studying", "📖"),
            "happy": ("Happy!", "💗"),
            "excited": ("Superstar!", "🌈"),
        },
        "bar_word": "sparkles",
    },
    "little_witch": {
        "tiers": {
            "drained": ("Drained", "🌙"),
            "sad": ("Sleepy", "🥱"),
            "neutral": ("Focused", "✨"),
            "happy": ("Sparkly", "⭐"),
            "excited": ("Full Magic!", "🌟"),
        },
        "bar_word": "magic",
    },
}

TALK_STYLES = {
    "little_witch": {
        "label": "Little witch",
        "encouragement": LITTLE_WITCH_FAILURE,
        "strict": LITTLE_WITCH_STRICT,
        "greeting": LITTLE_WITCH_GREETING,
        "recovery": LITTLE_WITCH_RECOVERY,
        "review": LITTLE_WITCH_HAPPY,
        "reveal": LITTLE_WITCH_REVEAL,
        "hard": LITTLE_WITCH_HARD,
        "easy": LITTLE_WITCH_EASY,
        "dialogue": LITTLE_WITCH_DIALOGUE,
        "spell": LITTLE_WITCH_SPELL_TEXT,
    },
    "kawaii": {
        "label": "Kawaii",
        "encouragement": KAWAII_ENCOURAGEMENT_LINES,
        "strict": KAWAII_STRICT_LINES,
        "greeting": KAWAII_GREETING_LINES,
        "recovery": KAWAII_RECOVERY_LINES,
        "timeout": KAWAII_TIMEOUT_LINES,
        "review": KAWAII_REVIEW_LINES,
        "hard": KAWAII_HARD_LINES,
        "dialogue": KAWAII_DIALOGUE,
        "spell": KAWAII_SPELL_TEXT,
    },
}


DEFAULT_CONFIG = {
    "character": "yuuhi_sailor",
    "pet_name": "Yuzu",
    "talking_style": "kawaii",
    "mood_neutral_at": 50,
    "mood_happy_at": 100,
    "mood_excited_at": 200,
    "sprite_size": 170,
    "mini_size": 180,
    "show_during_review": True,
    "show_chatter": True,
    "show_rating_messages": True,
    "custom_messages_enabled": True,
    "custom_messages": {},
    "bubble_font_size": 12,
    "chatter_percent": 30,
    "mini_position": "last",
    "mini_pos_xy": None,
    "mini_pos_by_deck": {},
    "show_mood_bar": True,
    "show_dialogue": True,
    "run_across": True,
    "side_panel": True,
    "focus_seconds": 10,
    "show_focus_timer": True,
    "recovery_reviews": 5,
    "recovery_timeout_behavior": "reset",
    "timer_position": "last",
    "timer_pos_xy": None,
    "timer_pos_by_deck": {},
    "timer_style": "pulse",
    "timer_opacity": 38,
    "timer_size": 100,
    "color_theme": "sakura",
    "recovery_display": "hearts",
    "show_recovery_counter": True,
    "counter_style": "solid",
    "hardcore_mode": False,
    "hardcore_misses": 3,
    "hardcore_recovery": 5,
}


# ---------------------------------------------------------------------------
# Config + daily review state
# ---------------------------------------------------------------------------
def get_config() -> dict:
    cfg = mw.addonManager.getConfig(__name__) or {}
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    # Reveal bubbles and rating reactions share the same chance and spacing rule.
    # Older builds used 15% for Sometimes and 25% for Often. Keep existing
    # settings aligned with the clearer 30% / 50% choices.
    legacy_frequency = {15: 30, 25: 50}.get(cfg.get("chatter_percent"))
    if legacy_frequency is not None:
        merged["chatter_percent"] = legacy_frequency
        cfg["chatter_percent"] = legacy_frequency
        mw.addonManager.writeConfig(__name__, cfg)
    # Older installs persisted a scaled 216 px default. Normalize that stale
    # default so it cannot override the intended 180 px starting size.
    if merged.get("mini_size") == 216:
        merged["mini_size"] = MINI_WIDTH
        cfg["mini_size"] = MINI_WIDTH
        mw.addonManager.writeConfig(__name__, cfg)
    # Keep existing installs' timer selections when replacing the two older styles.
    merged["timer_style"] = {"minimal": "pulse", "classic": "tab"}.get(
        merged.get("timer_style"), merged.get("timer_style", "pulse")
    )
    if not isinstance(merged.get("mini_pos_by_deck"), dict):
        merged["mini_pos_by_deck"] = {}
    if not isinstance(merged.get("timer_pos_by_deck"), dict):
        merged["timer_pos_by_deck"] = {}
    # Ignore any Little Witch value saved by an older add-on version.
    merged["talking_style"] = "kawaii"
    # Carry the previous default name forward without overwriting a custom name.
    if merged.get("character") == "yuuhi" and merged.get("pet_name") == "Yuuhi":
        merged["pet_name"] = "Yui"
    # Migrate old default pet names when a character's display name changes,
    # while preserving any name the user chose themselves.
    old_default_names = {
        "rin": ("Rin", "Kano"),
        "chitose": ("Chitose", "Sakia"),
        "eru": ("Eru", "Momo"),
        "firefly": ("Firefly", "Kokona"),
        "hatsune": ("Hatsune", "Soyo"),
        "kurumi": ("Kurumi", "Suzuka"),
        "mizuno": ("Mizuno", "Yume"),
        "maid": ("Maid", "Miku"),
        "yanami": ("Yanami", "Megumi"),
        "tifa": ("Tifa", "Fighter Girl"),
        "nezuko": ("Nezuko", "Demon Girl"),
        "shinobu": ("Shinobu", "Butterfly Girl"),
    }
    old_name = old_default_names.get(merged.get("character"))
    if old_name and merged.get("pet_name") == old_name[0]:
        merged["pet_name"] = old_name[1]
    removed_character_names = {"bella": "Bella", "yukina": "Yukina"}
    if merged.get("character") in removed_character_names:
        if merged.get("pet_name") == removed_character_names[merged["character"]]:
            merged["pet_name"] = PET_PROFILES["yuuhi_sailor"]["default_name"]
        merged["character"] = "yuuhi_sailor"
    if merged.get("character") not in PET_PROFILES:
        merged["character"] = "lumi"
    # Preserve positions remembered by versions that saved drags for every preset.
    if merged.get("timer_pos_xy") is not None:
        merged["timer_position"] = "last"
    return merged


def save_config(cfg: dict) -> None:
    mw.addonManager.writeConfig(__name__, cfg)


COLOR_THEMES = {
    "sakura": {"label": "Sakura", "accent": "#f29bb9", "surface": "#2d202b", "bubble": "#fff0f6", "ink": "#532c42"},
    "lavender": {"label": "Lavender", "accent": "#b9a7f7", "surface": "#252033", "bubble": "#f3efff", "ink": "#41335f"},
    "mint": {"label": "Mint", "accent": "#83d5b9", "surface": "#192e28", "bubble": "#edfff6", "ink": "#245344"},
    "sky": {"label": "Sky", "accent": "#8cc9f5", "surface": "#1d2936", "bubble": "#edf7ff", "ink": "#2a4d68"},
    "amber": {"label": "Amber", "accent": "#efc07d", "surface": "#30271e", "bubble": "#fff7e8", "ink": "#654923"},
}
TIMER_STYLES = {
    "glass": "Glass", "pulse": "Pulse Bar", "ring": "Ring",
    "kawaii": "Kawaii", "tab": "Floating Tab",
}
RECOVERY_DISPLAYS = {"hearts": "Five hearts", "hearts_text": "Hearts + remaining reviews", "text": "Text counter"}


def _theme(cfg=None) -> dict:
    cfg = get_config() if cfg is None else cfg
    return COLOR_THEMES.get(cfg.get("color_theme"), COLOR_THEMES["sakura"])


def _rgba(hex_color: str, alpha: float) -> str:
    values = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    return f"rgba({values[0]},{values[1]},{values[2]},{alpha:.2f})"


def _today() -> dict:
    try:
        if mw.col is not None:
            return {"scheme": "anki", "num": int(mw.col.sched.today)}
    except Exception:
        pass
    return {"scheme": "cal", "num": date.today().toordinal()}


def _count_todays_reviews_from_history() -> dict:
    empty = {"reviews": 0, "correct": 0, "streak": 0, "best_streak": 0}
    try:
        if mw.col is None:
            return empty
        cutoff = int(mw.col.sched.day_cutoff)
        start_ms = (cutoff - 86400) * 1000
        end_ms = cutoff * 1000
        eases = mw.col.db.list(
            "select ease from revlog where id >= ? and id < ? and ease > 0 order by id asc",
            start_ms, end_ms,
        )
    except Exception:
        return empty

    correct = streak = best_streak = 0
    for ease in eases:
        if ease == 1:
            streak = 0
        else:
            correct += 1
            streak += 1
            best_streak = max(best_streak, streak)
    return {"reviews": len(eases), "correct": correct, "streak": streak, "best_streak": best_streak}


def _reconcile_today_after_sync() -> None:
    try:
        if mw.col is None:
            return
        state = load_state()
        if state.get("day") != _today():
            return
        backfill = _count_todays_reviews_from_history()
        if backfill["reviews"] <= int(state.get("reviews", 0)):
            return
        state["reviews"] = backfill["reviews"]
        state["correct"] = backfill["correct"]
        state["streak"] = backfill["streak"]
        state["best_streak"] = max(int(state.get("best_streak", 0)), backfill["best_streak"])
        save_state(state)
        if mw.state == "deckBrowser":
            mw.deckBrowser.refresh()
    except Exception:
        pass


def _fresh_state() -> dict:
    today = _today()
    backfill = _count_todays_reviews_from_history()
    return {
        "day": today,
        "reviews": backfill["reviews"],
        "correct": backfill["correct"],
        "streak": backfill["streak"],
        "best_streak": backfill["best_streak"],
        "sad_reviews_remaining": 0,
        "timed_out_current": False,
    }


_STATE_DEFAULTS = {
    "reviews": 0,
    "correct": 0,
    "streak": 0,
    "best_streak": 0,
    "sad_reviews_remaining": 0,
    "timed_out_current": False,
    "consecutive_misses": 0,
    "hardcore_sad_remaining": 0,
    "sad_reviews_total": 0,
    "hardcore_sad_total": 0,
}


def load_state() -> dict:
    state = {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}

    today = _today()
    old_day = state.get("day")

    if not isinstance(old_day, dict) or old_day != today:
        consequence = {
            key: state.get(key, default)
            for key, default in (("sad_reviews_remaining", 0), ("sad_reviews_total", 0), ("timed_out_current", False))
        }
        state = _fresh_state()
        state.update(consequence)
        save_state(state)
        return state

    for k, v in _STATE_DEFAULTS.items():
        state.setdefault(k, v)
    state.setdefault("day", today)
    return state


def save_state(state: dict) -> None:
    os.makedirs(USER_FILES, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


# Anki's undo history lives for the current collection session. Match snapshots
# to revlog IDs instead of treating every Undo (e.g. a note edit) as a review.
_review_journal = []
_journal_collection = None


def _remember_review(card, before: dict, after: dict) -> None:
    global _journal_collection
    if mw.col is not _journal_collection:
        _review_journal.clear()
        _journal_collection = mw.col
    review_id = mw.col.db.scalar(
        "select id from revlog where cid = ? and ease > 0 order by id desc limit 1", card.id
    )
    if review_id is None:
        return
    # A new answer discards the old redo branch, just as Anki does.
    _review_journal[:] = [entry for entry in _review_journal
                          if entry["applied"] and entry["day"] == after["day"]]
    _review_journal.append({
        "id": int(review_id), "day": dict(after["day"]), "applied": True,
        "before": {key: before.get(key, default) for key, default in _STATE_DEFAULTS.items()},
        "after": {key: after.get(key, default) for key, default in _STATE_DEFAULTS.items()},
    })


def _sync_review_undo(*_args) -> None:
    """Restore review counters only when a tracked revlog row disappears/reappears.

    The operation hook also catches Redo, for which Anki has no dedicated hook.
    Reading revlog never changes Anki's own undo stack or collection data.
    """
    if mw.col is not _journal_collection or not _review_journal:
        return
    entries = [entry for entry in _review_journal if entry["day"] == _today()]
    if not entries:
        return
    review_ids = [entry["id"] for entry in entries]
    present = set(mw.col.db.list(
        "select id from revlog where id >= ? and id <= ?", min(review_ids), max(review_ids)
    ))
    undone = [entry for entry in reversed(entries) if entry["applied"] and entry["id"] not in present]
    redone = [entry for entry in entries if not entry["applied"] and entry["id"] in present]
    if not undone and not redone:
        return
    state = load_state()
    for entry in undone:
        state.update(entry["before"])
        entry["applied"] = False
    for entry in redone:
        state.update(entry["after"])
        entry["applied"] = True
    # Modes explicitly turned off should stay off even after restoring history.
    if not get_config().get("show_focus_timer", True):
        state.update(sad_reviews_remaining=0, sad_reviews_total=0, timed_out_current=False)
    if not _hardcore_on():
        state.update(hardcore_sad_remaining=0, hardcore_sad_total=0, consecutive_misses=0)
    save_state(state)
    global _mini_reaction_until, _greeting_shown
    _mini_reaction_until = 0.0
    _greeting_shown = False
    _stop_focus_timer()
    _eval_in_reviewer("window.lumiBuddyToken=(window.lumiBuddyToken||0)+1;")
    QTimer.singleShot(0, _refresh_after_review_undo)


def _refresh_after_review_undo() -> None:
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()
    elif _mini_pet_active():
        show_idle_pet()
    if mw.state == "review" and getattr(mw.reviewer, "state", None) == "question":
        _start_focus_timer()


def _clear_review_journal(*_args) -> None:
    global _journal_collection
    _review_journal.clear()
    _journal_collection = None


# ---------------------------------------------------------------------------
# Deck browser rendering
# ---------------------------------------------------------------------------
def _bar_word() -> str:
    return MOOD_TIER_NAMES.get(_talk_style_key(), MOOD_TIER_NAMES["kawaii"])["bar_word"]


def render_pet_html() -> str:
    cfg = get_config()
    theme = _theme(cfg)
    state = load_state()
    name = cfg["pet_name"]
    r = int(state["reviews"])
    size = int(cfg.get("sprite_size", DEFAULT_CONFIG["sprite_size"]))

    tier = _current_mood_tier(cfg, r)
    label, emoji, bar_color = tier["label"], tier["emoji"], theme["accent"]
    pct = _mood_bar_percent(tier, r)
    candidates = tier["pool"]
    weights = tier.get("weights", [1] * len(candidates))
    # Rotation pool expands by weight (lively switching), while the rendered
    # variant divs stay deduplicated.
    rotation = []
    for _name, _w in zip(candidates, weights):
        rotation.extend([_name] * _w)

    mood = f"{emoji} {name}'s mood: {label}"
    initial = _pick_weighted(candidates, weights)
    box_id = f"lumibuddy-pet-{random.randint(0, 10**9)}"

    # Keep easter-egg poses available even outside the mood pool.
    extra_names = [n for n in ("jumping", "waiting", "running_left", "running_right") if n not in candidates]
    all_names = candidates + extra_names
    variants = "".join(
        f'<div class="lumibuddy-variant" data-name="{nm}" style="display:{"block" if nm == initial else "none"}">'
        f'{sprite_html(nm, width=size)}</div>'
        for nm in all_names
    )

    mood_names_json = json.dumps(rotation)
    run_mode_js = "true" if (cfg.get("run_across", True) and tier["key"] in ("happy", "excited")) else "false"
    cycle_script = f"""
<script>
(function(){{
  var box = document.getElementById('{box_id}');
  if (!box) return;
  var variants = {{}};
  box.querySelectorAll('.lumibuddy-variant').forEach(function(v){{ variants[v.dataset.name] = v; }});
  var moodNames = {mood_names_json};
  var runMode = {run_mode_js};
  var current = '{initial}';
  var token = 0;

  function show(name){{
    Object.keys(variants).forEach(function(k){{ variants[k].style.display = (k === name) ? 'block' : 'none'; }});
    current = name;
  }}

  function gapFor(name){{
    if (name === 'look_a') return {_look_hold_ms('look_a')};
    if (name === 'look_b') return {_look_hold_ms('look_b')};
    return {SWAP_INTERVAL_MIN_MS} + Math.random() * {SWAP_INTERVAL_MAX_MS - SWAP_INTERVAL_MIN_MS};
  }}

  function scheduleTick(delay){{
    var myToken = ++token;
    setTimeout(function(){{
      if (myToken !== token) return;
      var pool = moodNames.filter(function(n){{
        if (n === current) return false;
        if ((current === 'look_a' || current === 'look_b') && (n === 'look_a' || n === 'look_b')) return false;
        return true;
      }});
      var next = pool.length ? pool[Math.floor(Math.random() * pool.length)] : moodNames[0];
      show(next);
      scheduleTick(gapFor(next));
    }}, delay);
  }}
  if (moodNames.length > 1 && !runMode) scheduleTick(gapFor(current));

  function resumeMood(){{
    ++token;
    var pick = moodNames[Math.floor(Math.random() * moodNames.length)];
    show(pick);
    if (!runMode) scheduleTick(gapFor(pick));
  }}

  // --- run back and forth ---
  // One character, no second sprite: they pose, sprint one way, turns, sprints
  // back, then settles on a different pose and goes again. The sprite swaps to
  // running_left / running_right to match the direction of travel.
  var RUN_TRAVEL = {RUN_TRAVEL_PX};
  var RUN_LEG_MS = {RUN_LEG_MS};
  var POSE_MS = {RUN_POSE_MS};
  var x = 0, dir = 1, runTimer = null;
  function clearRun(){{
    if (runTimer) {{ clearTimeout(runTimer); runTimer = null; }}
    box.style.transition = 'none';
    box.style.transform = '';
  }}
  function poseThenRun(){{
    ++token;
    var poses = moodNames.filter(function(n){{
      return n !== 'running_left' && n !== 'running_right' && n !== current;
    }});
    if (!poses.length) poses = moodNames.filter(function(n){{
      return n !== 'running_left' && n !== 'running_right';
    }});
    var pose = poses.length ? poses[Math.floor(Math.random() * poses.length)] : current;
    clearRun();
    show(pose);
    runTimer = setTimeout(runLeg, POSE_MS);
  }}
  function runLeg(){{
    if (runMode !== {run_mode_js}) return;
    show(dir > 0 ? 'running_right' : 'running_left');
    x += dir * RUN_TRAVEL;
    box.style.transition = 'transform ' + RUN_LEG_MS + 'ms linear';
    box.style.transform = 'translateX(' + x + 'px)';
    runTimer = setTimeout(function(){{
      if (runMode !== {run_mode_js}) return;
      dir = -dir;                 // turn around, sprite flips on the next leg
      runLeg();
    }}, RUN_LEG_MS);
  }}
  if (runMode) poseThenRun();

  var clickTimes = [];
  box.addEventListener('click', function(){{
    var now = Date.now();
    clickTimes.push(now);
    clickTimes = clickTimes.filter(function(t){{ return now - t <= {EASTER_CLICK_WINDOW_MS}; }});
    if (clickTimes.length >= {EASTER_CLICK_COUNT}) {{
      clickTimes = [];
      ++token;
      show('jumping');
      var myToken = token;
      setTimeout(function(){{ if (myToken === token) resumeMood(); }}, {EASTER_EXCITED_HOLD_MS});
    }}
  }});

  var holding = false;
  var pressTimer = null;
  box.addEventListener('mousedown', function(){{
    holding = false;
    pressTimer = setTimeout(function(){{
      holding = true;
      ++token;
      show('waiting');
    }}, {EASTER_HOLD_MS});
  }});
  function endPress(){{
    clearTimeout(pressTimer);
    if (holding) {{ holding = false; resumeMood(); }}
  }}
  box.addEventListener('mouseup', endPress);
  box.addEventListener('mouseleave', endPress);
}})();
</script>"""

    # --- dialogue bubble ---
    dialogue_block = ""
    if cfg.get("show_dialogue", True):
        style = _talk_style()
        dialogue_lines = style["dialogue"].get(tier["key"], style["dialogue"]["neutral"])
        line = random.choice(_message_lines("dialogue", dialogue_lines, cfg))
        line = line.replace("Lumi", name).replace("{name}", name)
        line = _clean_message(line)
        spell = style["spell"].get(tier["key"], "")
        spell = spell.replace("Lumi", name).replace("{name}", name)
        spell = _clean_message(spell)
        spell_html = f'<div style="font-size:11px; color:{theme["ink"]}; opacity:.8; margin-top:2px;">{spell}</div>' if spell else ""
        bubble_size = _bubble_font_size()
        dialogue_block = f"""
  <div style="display:inline-block; background:{theme['bubble']}; color:{theme['ink']};
              border-radius:12px; padding:6px 10px; font-size:{bubble_size}px; margin-bottom:6px;
              border:1px solid {_rgba(theme['accent'], 0.5)}; max-width:{max(260, bubble_size * 22)}px;">{line}{spell_html}</div><br>"""

    mood_block = ""
    if cfg.get("show_mood_bar", True):
        mood_block = f"""
  <div style="font-size:12px; margin:2px 0 6px;">{mood}</div>
  <div style="background:rgba(127,127,127,0.25); border-radius:6px; height:9px; overflow:hidden;">
    <div style="width:{pct}%; height:100%; background:{bar_color}; transition:width 0.4s ease;"></div>
  </div>
  <div style="font-size:10px; margin-top:4px; opacity:0.8;">{r} cards today · {tier["emoji"]} {_bar_word()} {min(100, pct)}%</div>"""

    box_width = max(size, 160) + 40
    # Side panel: on wide windows they dock to the right of the deck list
    # (fixed position); on narrow windows they stay below the decks as before.
    side_css = ""
    if cfg.get("side_panel", True):
        side_css = """
<style>
@media (min-width: 1220px) {
  .lumibuddy-side {
    position: fixed !important;
    right: 18px;
    top: 50%;
    transform: translateY(-50%);
    margin: 0 !important;
    z-index: 10;
  }
}
</style>"""
    return f"""
<div class="lumibuddy-side" style="text-align:center; margin:12px auto 6px; max-width:{box_width}px; padding:10px 12px;
            border-radius:12px; background:transparent;{BUDDY_FONT_CSS}">
  {dialogue_block}
  <div id="{box_id}">{variants}</div>
  {cycle_script}
  {mood_block}
</div>{side_css}"""


def on_deck_browser_render(deck_browser, content) -> None:
    # Reaching the home screen ends the review session, so arm the greeting again.
    global _review_greeted
    _review_greeted = False
    content.stats += render_pet_html()


# ---------------------------------------------------------------------------
# Buddy shown during reviews
# ---------------------------------------------------------------------------
_mini_reaction_until = 0.0
_review_greeted = False   # one wave per review session, re-armed on the home screen
_greeting_shown = False  # the opening wave holds until the first card is answered


# Four looks for the "Okay again in N reviews" chip.
RECOVERY_COUNTER_STYLES = {
    "solid": "Solid",
    "transparent": "Transparent",
    "simple": "Plain text",
    "kawaii": "Kawaii",
}


def _counter_html(remaining: int, kind: str, cfg=None) -> str:
    cfg = get_config() if cfg is None else cfg
    lead = "Recover in " if kind == "hardcore" else "Okay again in "
    label = lead + f"{remaining} review{'s' if remaining != 1 else ''}"
    look = cfg.get("counter_style", DEFAULT_CONFIG["counter_style"])
    base = BUDDY_FONT_CSS + "margin-top:-5px;font-size:11px;white-space:nowrap;"
    theme = _theme(cfg)
    accent, surface = theme["accent"], _rgba(theme["surface"], 0.88)
    if look == "simple":
        return f'<div style="{base}color:{accent};text-shadow:0 1px 3px #222;">{label}</div>'
    if look == "transparent":
        return (
            f'<div style="{base}color:rgba(255,255,255,0.92);'
            f'background:{_rgba(theme["surface"], 0.22)};border-radius:8px;padding:3px 7px;'
            f'border:1px solid rgba(255,255,255,0.18);">{label}</div>'
        )
    if look == "kawaii":
        return (
            f'<div style="{base}color:{theme["ink"]};background:{accent};'
            f'border-radius:999px;padding:4px 11px;font-weight:600;'
            f'box-shadow:0 2px 8px {_rgba(accent, 0.25)};'
            f'border:1px solid rgba(255,255,255,0.5);">&#9829; {label} &#9829;</div>'
        )
    return (
        f'<div style="{base}color:{accent};background:{surface};'
        f'border-radius:8px;padding:3px 7px;">{label}</div>'
    )


def _recovery_html(state: dict, sad: bool, remaining: int, kind: str, cfg=None) -> str:
    cfg = get_config() if cfg is None else cfg
    display = cfg.get("recovery_display", "hearts")
    if display == "text":
        return _counter_html(remaining, kind, cfg) if sad and remaining else ""
    theme = _theme(cfg)
    total_key = "hardcore_sad_total" if kind == "hardcore" else "sad_reviews_total"
    fallback = max(1, int(cfg.get("hardcore_recovery" if kind == "hardcore" else "recovery_reviews", 5)))
    total = max(1, remaining, int(state.get(total_key, 0)) or fallback)
    progress = max(0.0, min(1.0, 1 - remaining / total)) if sad else 1.0
    label = f"{remaining} review{'s' if remaining != 1 else ''} until recovered" if sad else "Recovered — all hearts full"
    path = "M12 21s-9-5.8-9-12a5 5 0 0 1 9-3 5 5 0 0 1 9 3c0 6.2-9 12-9 12Z"
    hearts = []
    for index in range(5):
        fill = max(0.0, min(1.0, progress * 5 - index)) * 100
        # Inline !important beats card templates with global path fill/stroke rules.
        empty = (f'<svg width="14.4" height="15.3" viewBox="0 0 24 24" aria-hidden="true">'
                 f'<path d="{path}" fill="{_rgba(theme["accent"], 0.12)}" '
                 f'stroke="{_rgba(theme["accent"], 0.65)}" stroke-width="1.4" '
                 f'style="fill:{_rgba(theme["accent"], 0.12)} !important;'
                 f'stroke:{_rgba(theme["accent"], 0.65)} !important;stroke-width:1.4 !important;"/></svg>')
        full = (f'<svg width="14.4" height="15.3" viewBox="0 0 24 24" aria-hidden="true">'
                f'<path d="{path}" fill="{theme["accent"]}" '
                f'style="fill:{theme["accent"]} !important;stroke:none !important;stroke-width:0 !important;"/></svg>')
        hearts.append(f'<span style="display:inline-block;position:relative;width:14.4px;height:15.3px;">{empty}'
                      f'<span style="position:absolute;left:0;top:0;width:{fill:.2f}%;height:15.3px;overflow:hidden;">'
                      f'{full}</span></span>')
    caption = f'<div style="font-size:10px;margin-top:3px;color:{theme["accent"]};">{label}</div>' if display == "hearts_text" and sad else ""
    return (f'<div class="lumi-recovery-hearts" title="{html.escape(label)}" role="img" '
            f'aria-label="{html.escape(label)}" data-progress="{progress:.4f}" '
            f'style="{BUDDY_FONT_CSS}display:inline-block;margin-top:0;padding:5.4px 8.1px 3.6px;border-radius:10.8px;'
            f'background:{_rgba(theme["surface"], 0.62)};border:1px solid {_rgba(theme["accent"], 0.2)};">'
            f'<div style="display:flex;gap:3.6px;justify-content:center;">{"".join(hearts)}</div>{caption}</div>')


def _penalty(state: dict) -> tuple:
    """How sad they are right now: (is_sad, remaining, kind).

    Two independent penalties can be active at once - a recall timeout and a
    hardcore miss streak - so the larger counter wins the label."""
    timeout_left = max(0, int(state.get("sad_reviews_remaining", 0)))
    hardcore_left = max(0, int(state.get("hardcore_sad_remaining", 0)))
    if timeout_left >= hardcore_left:
        kind = "timeout"
        remaining = timeout_left
    else:
        kind = "hardcore"
        remaining = hardcore_left
    return bool(state.get("timed_out_current")) or remaining > 0, remaining, kind


def _mini_html(force_name: str = None, ignore_sad: bool = False) -> str:
    """Sprite only — kept byte-identical to the long-working plain push.
    Speech bubbles live in a separate #lumibuddy-bubble element so caption
    updates can never disturb the sprite.

    `ignore_sad` lets an event force its own pose (the greeting wave) while a
    recovery penalty is still running; the remaining-reviews counter still shows."""
    state = load_state()
    sad, remaining, kind = _penalty(state)
    name = ("failed" if sad and not ignore_sad else (force_name or _pick_idle()))
    counter = ""
    if get_config().get("show_recovery_counter", True):
        counter = _recovery_html(state, sad, remaining, kind)
    return f"<div>{sprite_html(name, width=_mini_width())}{counter}</div>"


_review_position_deck_key = None


def _current_deck_position_key() -> str:
    """Remember the deck opened for this session, including its subdeck cards."""
    global _review_position_deck_key
    if getattr(mw, "state", None) != "review":
        return "default"
    if _review_position_deck_key is not None:
        return _review_position_deck_key
    try:
        deck_id = int(mw.col.decks.get_current_id())
    except (AttributeError, TypeError, ValueError, OverflowError):
        deck_id = 0
    _review_position_deck_key = str(deck_id) if deck_id > 0 else "default"
    return _review_position_deck_key


def _position_for_deck(cfg: dict, map_key: str, legacy_key: str):
    """Return a deck's saved (left, top), falling back to the older global value."""
    positions = cfg.get(map_key, {})
    xy = positions.get(_current_deck_position_key()) if isinstance(positions, dict) else None
    if xy is None:
        xy = cfg.get(legacy_key)
    try:
        return (max(0, int(xy[0])), max(0, int(xy[1])))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _save_position_for_deck(cfg: dict, map_key: str, legacy_key: str, xy=None) -> None:
    positions = cfg.get(map_key)
    if not isinstance(positions, dict):
        positions = {}
    key = _current_deck_position_key()
    if xy is None:
        positions.pop(key, None)
    else:
        positions[key] = [max(0, int(xy[0])), max(0, int(xy[1]))]
    cfg[map_key] = positions
    # Keep legacy/global values as a fallback for decks without their own saved spot.
    cfg[legacy_key] = list(xy) if xy is not None else None


# Where the recall timer docks. Like the buddy it is draggable anywhere
# (remembered per deck); double-click snaps it back to the chosen preset.
TIMER_POSITIONS = {
    "last": "position:fixed;top:72px;left:50%;transform:translateX(-50%);",
    "top": "position:fixed;top:72px;left:50%;transform:translateX(-50%);",
    "top_left": "position:fixed;top:72px;left:14px;",
    "top_right": "position:fixed;top:72px;right:14px;",
    "bottom": "position:fixed;bottom:14px;left:50%;transform:translateX(-50%);",
}
TIMER_POSITION_LABELS = {
    "last": "Same as last time",
    "top": "Top center",
    "top_left": "Top left",
    "top_right": "Top right",
    "bottom": "Bottom center",
}

# Drag wiring is installed once per page load and keeps its own drag state, so
# grabbing the timer never disturbs the buddy (and vice versa).
TIMER_DRAG_STATIC_JS = """
if(!window._lumiWireTimer){
  window._lumiWireTimer=function(t){
    if(t.dataset.dragwired) return;
    t.dataset.dragwired='1';
    t.addEventListener('mousedown',function(e){e.preventDefault();
      var r=t.getBoundingClientRect();
      window._lumiTimerDrag={dx:e.clientX-r.left,dy:e.clientY-r.top};
      t.style.cursor='grabbing';});
    t.addEventListener('dblclick',function(){
      t.style.cssText=t.dataset.resetCss||t.dataset.baseCss||'';
      if(typeof pycmd==='function')pycmd('studybuddy_timer_pos:clear');});
  };
  window._lumiClampTimer=function(){
    var t=document.getElementById('lumibuddy-focus-timer');
    if(!t||t.style.display==='none')return;
    var r=t.getBoundingClientRect();
    var x=Math.max(0,Math.min(r.left,Math.max(0,window.innerWidth-r.width)));
    var y=Math.max(0,Math.min(r.top,Math.max(0,window.innerHeight-r.height)));
    if(x!==r.left||y!==r.top){
      t.style.left=x+'px';t.style.top=y+'px';t.style.right='auto';
      t.style.bottom='auto';t.style.transform='none';}
  };
  document.addEventListener('mousemove',function(e){
    var d=window._lumiTimerDrag;if(!d)return;
    var x=document.getElementById('lumibuddy-focus-timer');if(!x)return;
    x.style.left=(e.clientX-d.dx)+'px';x.style.top=(e.clientY-d.dy)+'px';
    x.style.right='auto';x.style.bottom='auto';x.style.transform='none';});
  document.addEventListener('mouseup',function(){
    var dragged=window._lumiTimerDrag;window._lumiTimerDrag=null;
    var x=document.getElementById('lumibuddy-focus-timer');if(!x)return;
    x.style.cursor='grab';
    if(dragged){window._lumiClampTimer();var r=x.getBoundingClientRect();
      if(typeof pycmd==='function')pycmd('studybuddy_timer_pos:set:'+Math.round(r.left)+','+Math.round(r.top));}
  });
  window.addEventListener('resize',window._lumiClampTimer);
}"""


def _timer_appearance(cfg=None) -> tuple:
    cfg = get_config() if cfg is None else cfg
    theme = _theme(cfg)
    style = cfg.get("timer_style", "pulse")
    if style not in TIMER_STYLES:
        style = "glass"
    accent = theme["accent"]
    common = (
        "z-index:10000;text-align:center;cursor:grab;user-select:none;box-sizing:border-box;"
        "font:600 13px -apple-system,BlinkMacSystemFont,sans-serif;color:#fff;"
    )
    if style == "glass":
        alpha = max(0, min(100, int(cfg.get("timer_opacity", 38)))) / 100
        panel = (f"min-width:112px;padding:9px 13px;border-radius:15px;background:{_rgba(theme['surface'], alpha)};"
                 f"border:1px solid {_rgba(accent, 0.3)};backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);"
                 "box-shadow:0 5px 22px rgba(0,0,0,.16);text-shadow:0 1px 4px rgba(0,0,0,.55);")
    elif style == "pulse":
        panel = (f"width:154px;min-width:154px;padding:5px 9px;border-radius:999px;"
                 f"background:{_rgba(theme['surface'], 0.86)};border:1px solid {_rgba(accent, 0.55)};"
                 f"box-shadow:0 3px 12px {_rgba(accent, 0.15)};")
    elif style == "ring":
        panel = (f"min-width:88px;padding:7px 10px 9px;border-radius:20px;background:{_rgba(theme['surface'], 0.55)};"
                 f"border:1px solid {_rgba(accent, 0.22)};")
    elif style == "kawaii":
        panel = (f"min-width:112px;padding:8px 18px 10px;border-radius:28px;background:{theme['bubble']};color:{theme['ink']};"
                 f"border:1px solid {_rgba(accent, 0.6)};box-shadow:0 3px 14px {_rgba(accent, 0.18)};")
    elif style == "tab":
        panel = "width:154px;min-width:154px;padding:0;background:transparent;border:0;box-shadow:none;"
    else:
        panel = (f"min-width:112px;padding:7px 12px 8px;border-radius:12px;background:{_rgba(theme['surface'], 0.88)};"
                 "box-shadow:0 2px 12px rgba(0,0,0,.25);")
    title = '<div class="lumi-focus-title" style="font-size:9px;letter-spacing:.7px;line-height:1.5;text-transform:uppercase;opacity:.85;"></div>'
    count = '<div class="lumi-focus-count" style="font-size:24px;line-height:1.2;font-variant-numeric:tabular-nums;"></div>'
    if style == "ring":
        markup = (
            '<div style="position:relative;width:64px;height:64px;margin:auto;">'
            '<svg viewBox="0 0 64 64" width="64" height="64" aria-hidden="true">'
            f'<circle cx="32" cy="32" r="28" fill="none" stroke="{_rgba(accent, 0.18)}" stroke-width="3.5" '
            f'style="fill:none !important;stroke:{_rgba(accent, 0.18)} !important;stroke-width:3.5 !important;"/>'
            '<circle class="lumi-focus-ring" cx="32" cy="32" r="28" fill="none" '
            f'stroke="{accent}" stroke-width="3.5" stroke-linecap="round" pathLength="100" '
            'stroke-dasharray="100 100" transform="rotate(-90 32 32)" '
            f'style="fill:none !important;stroke:{accent} !important;stroke-width:3.5 !important;transition:stroke-dashoffset .25s ease;"/></svg>'
            f'<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;">{count}</div></div>{title}'
        )
    elif style in {"pulse", "tab"}:
        track = _rgba(accent, 0.2)
        count_style = (f"display:grid;place-items:center;min-width:20px;height:22px;padding:0 2px;"
                       f"color:{'#fff' if style == 'pulse' else theme['ink']};"
                       "font-size:11px;line-height:1;font-variant-numeric:tabular-nums;")
        if style == "tab":
            count_style += f"border-radius:8px;background:{theme['bubble']};padding:0 4px;"
        markup = (
            '<div style="display:flex;align-items:center;gap:8px;width:100%;">'
            f'<div style="height:5px;flex:1;background:{track};border-radius:2px;overflow:hidden;">'
            '<div class="lumi-focus-bar" style="height:100%;width:63%;border-radius:2px;transition:width .25s ease;"></div></div>'
            f'<div class="lumi-focus-count" style="{count_style}">8</div></div>'
        )
        if style == "tab":
            # Option C: a hairline bar and a separate little countdown tab.
            markup = markup.replace('height:5px;flex:1;', 'height:4px;flex:1;')
    else:
        track = _rgba(theme["ink"] if style == "kawaii" else accent, 0.18)
        markup = (f'{title}{count}<div style="height:3px;background:{track};border-radius:4px;overflow:hidden;margin-top:5px;">'
                  '<div class="lumi-focus-bar" style="height:100%;border-radius:4px;transition:width .25s ease;"></div></div>')
    markup += (f'<div class="lumi-focus-start" role="button" tabindex="0" '
               f'style="display:none;margin-top:5px;font-size:11px;line-height:1.3;color:{theme["ink"] if style == "kawaii" else "#fff"};'
               'cursor:pointer;text-decoration:underline;text-underline-offset:2px;">Click to begin</div>')
    scale = max(60, min(180, int(cfg.get("timer_size", 100)))) / 100
    if scale != 1:
        def pixels(match):
            return f"{float(match.group(1)) * scale:g}px"
        panel_css = re.sub(r"(\d*\.?\d+)px", pixels, common + panel)
        markup = re.sub(r"(\d*\.?\d+)px", pixels, markup)
        markup = markup.replace('width="64" height="64"', f'width="{64 * scale:g}" height="{64 * scale:g}"')
    else:
        panel_css = common + panel
    return style, panel_css, markup


def _focus_timer_js(seconds_left: int, expired: bool = False, cfg=None, waiting: bool = False) -> str:
    cfg = get_config() if cfg is None else cfg
    left = max(0, int(seconds_left))
    total = max(1, int(cfg.get("focus_seconds", 10)))
    title = "Time's up" if expired else "Recall"
    warn_at = max(1, int(round(total * 0.3)))
    color = "#e86b78" if expired else ("#e5a84b" if left <= warn_at else _theme(cfg)["accent"])
    pct = max(0, min(100, int(round(left * 100 / total)))) if total else 0
    position = cfg.get("timer_position", DEFAULT_CONFIG["timer_position"])
    style, panel_css, markup = _timer_appearance(cfg)
    appearance = json.dumps([style, cfg.get("color_theme"), cfg.get("timer_opacity", 38), cfg.get("timer_size", 100)])
    base = TIMER_POSITIONS.get(position, TIMER_POSITIONS["top"]) + panel_css
    deck_key = _current_deck_position_key()
    preset_token = f"{position}:{deck_key}" if position == "last" else position
    saved_xy = _position_for_deck(cfg, "timer_pos_by_deck", "timer_pos_xy") if position == "last" else None
    reset_base = (TIMER_POSITIONS["top"] + panel_css) if position == "last" else base
    saved_css = base
    if isinstance(saved_xy, (list, tuple)) and len(saved_xy) == 2:
        try:
            x, y = (max(0, int(value)) for value in saved_xy)
            saved_css += f"left:{x}px;top:{y}px;right:auto;bottom:auto;transform:none;"
        except (ValueError, TypeError, OverflowError):
            pass
    return f"""
(function(){{
  {TIMER_DRAG_STATIC_JS}
  var box=document.getElementById('lumibuddy-focus-timer');
  if(!box){{box=document.createElement('div');box.id='lumibuddy-focus-timer';
    box.setAttribute('role','timer');document.body.appendChild(box);}}
  var newPosition=!box.dataset.baseCss||window._lumiTimerPreset!=={json.dumps(preset_token)};
  var newAppearance=box.dataset.appearance!=={json.dumps(appearance)};
  if(newPosition){{box.style.cssText={json.dumps(saved_css)};}}
  else if(newAppearance){{
    var anchor={{}};['left','top','right','bottom','transform'].forEach(function(p){{anchor[p]=box.style[p];}});
    box.style.cssText={json.dumps(base)};
    Object.keys(anchor).forEach(function(p){{box.style[p]=anchor[p];}});
  }}
  if(newAppearance){{box.innerHTML={json.dumps(markup)};box.dataset.appearance={json.dumps(appearance)};}}
  window._lumiTimerPreset={json.dumps(preset_token)};
  box.dataset.baseCss={json.dumps(base)};
  box.dataset.resetCss={json.dumps(reset_base)};
  window._lumiWireTimer(box);
  box.title='Drag to move. Double-click to reset. Appearance options are in Focus Friends settings.';
  var titleNode=box.querySelector('.lumi-focus-title');if(titleNode)titleNode.textContent={json.dumps(title)};
  var countNode=box.querySelector('.lumi-focus-count');if(countNode)countNode.textContent={json.dumps(str(left) if not expired else '—')};
  var start=box.querySelector('.lumi-focus-start');
  if(start){{
    start.style.display={json.dumps('block' if waiting and not expired else 'none')};
    start.onclick=function(e){{e.preventDefault();e.stopPropagation();if(typeof pycmd==='function')pycmd({_TIMER_START_MSG!r});}};
    start.onmousedown=function(e){{e.preventDefault();e.stopPropagation();}};
    start.onkeydown=function(e){{if(e.key==='Enter'||e.key===' '){{e.preventDefault();e.stopPropagation();if(typeof pycmd==='function')pycmd({_TIMER_START_MSG!r});}}}};
  }}
  var bar=box.querySelector('.lumi-focus-bar');
  if(bar){{bar.style.width='{pct}%';bar.style.background='{color}';}}
  var ring=box.querySelector('.lumi-focus-ring');
  if(ring){{ring.style.strokeDashoffset='{100 - pct}';ring.style.setProperty('stroke','{color}','important');}}
  box.style.display='block';
  box.style.opacity='1';
  window._lumiClampTimer();
}})();"""


def _hide_focus_timer() -> None:
    _eval_in_reviewer("(function(){var b=document.getElementById('lumibuddy-focus-timer');if(b)b.style.display='none';})();")


def _pause_focus_timer_after_reveal() -> None:
    """Freeze the revealed card's countdown in place and soften the timer."""
    if _focus_timer is not None:
        _focus_timer.stop()
    _eval_in_reviewer(
        "(function(){var b=document.getElementById('lumibuddy-focus-timer');"
        "if(b){b.style.display='block';b.style.opacity='0.5';}})();"
    )


def _forgive_recovery_penalty(timeout: bool = True, hardcore: bool = True) -> None:
    """Clear any in-progress penalty so they are back to normal. Turning a mode off
    forgives what it started - they are not being pushed around any more."""
    state = load_state()
    if timeout:
        state["sad_reviews_remaining"] = 0
        state["sad_reviews_total"] = 0
        state["timed_out_current"] = False
    if hardcore:
        state["hardcore_sad_remaining"] = 0
        state["hardcore_sad_total"] = 0
        state["consecutive_misses"] = 0
    save_state(state)
    if _mini_pet_active():
        js = """
(function(){
  %s
  window.lumiBuddyToken = (window.lumiBuddyToken || 0) + 1;
  el.innerHTML = %s;
  %s
})();
""" % (_ensure_mini_el_js(), json.dumps(_mini_html()), _bubble_apply_js(None))
        _eval_in_reviewer(js)
        _hide_focus_timer()


def _refresh_sad_pet() -> None:
    if not _mini_pet_active():
        return
    js = """
(function(){
  %s
  window.lumiBuddyToken=(window.lumiBuddyToken||0)+1;
  el.innerHTML=%s;
  %s
})();
""" % (
        _ensure_mini_el_js(),
        json.dumps(_mini_html(force_name="failed")),
        _bubble_apply_js(None),
    )
    _eval_in_reviewer(js)


def _focus_timer_tick() -> None:
    global _focus_seconds_left
    _focus_seconds_left -= 1
    if _focus_seconds_left <= 0:
        _focus_seconds_left = 0
        _focus_timer.stop()
        state = load_state()
        if (get_config().get("recovery_timeout_behavior", "reset") != "hold"
                or int(state.get("sad_reviews_remaining", 0)) <= 0):
            state["sad_reviews_remaining"] = _recovery_reviews()
            state["sad_reviews_total"] = _recovery_reviews()
        state["timed_out_current"] = True
        save_state(state)
        _eval_in_reviewer(_focus_timer_js(0, expired=True))
        _refresh_sad_pet()
        timeout_caption = _event_caption("timeout", always=True, force=True)
        _eval_in_reviewer(_bubble_js(timeout_caption))
    else:
        _eval_in_reviewer(_focus_timer_js(_focus_seconds_left))


def _start_focus_timer() -> None:
    global _focus_seconds_left
    if not get_config().get("show_focus_timer", True):
        return
    if mw.state != "review" or not getattr(mw, "reviewer", None) or _focus_timer is None:
        return
    _focus_timer.stop()
    _focus_seconds_left = _focus_seconds()
    if _focus_waiting_to_begin:
        _eval_in_reviewer(_focus_timer_js(_focus_seconds_left, waiting=True))
        return
    _eval_in_reviewer(_focus_timer_js(_focus_seconds_left))
    _focus_timer.start(1000)


def _stop_focus_timer() -> None:
    if _focus_timer is not None:
        _focus_timer.stop()
    _hide_focus_timer()


BUBBLE_ENTRANCE_JS = """
window._lumiBubbleEnter=function(b){
  var content=b&&b.firstElementChild;
  var reduced=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(content&&content.animate&&!reduced){
    content.animate([{opacity:0,transform:'translateY(4px)'},{opacity:1,transform:'translateY(0)'}],
      {duration:180,easing:'cubic-bezier(.2,.7,.3,1)'});
  }
};
"""


def _bubble_html(text: str, cfg=None) -> str:
    cfg = get_config() if cfg is None else cfg
    text = _clean_message(text)
    size = max(8, min(28, int(cfg.get("bubble_font_size", 12))))
    theme = _theme(cfg)
    return (
        f'<div class="lumi-bubble-content" style="{BUDDY_FONT_CSS}background:{theme["bubble"]};color:{theme["ink"]};border-radius:12px;'
        f'border:1px solid {_rgba(theme["accent"], 0.5)};'
        f"padding:4px 10px;font-size:{size}px;line-height:1.35;max-width:{max(200, size * 17)}px;"
        f'text-align:center;box-shadow:0 2px 10px rgba(0,0,0,0.25);">{html.escape(text)}</div>'
    )


def _clean_message(text: str) -> str:
    """Normalize message punctuation and capitalize sentence starts for display."""
    text = str(text or "").replace("~", "")
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    text = re.sub(r"([,.!?]){2,}", lambda m: m.group(0)[0], text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # Skip leading emoji/quotes and capitalize the first actual letter, then
    # capitalize letters following sentence-ending punctuation.
    text = re.sub(r"(^|[.!?]\s+)([^A-Za-z]*)([a-z])",
                  lambda m: m.group(1) + m.group(2) + m.group(3).upper(), text)
    return text


def _bubble_ensure_js() -> str:
    """Define the bubble positioner once + make sure the element exists."""
    return (
        BUBBLE_ENTRANCE_JS +
        "if(!window._lumiPositionBubble){window._lumiPositionBubble=function(){"
        "var m2=document.getElementById('lumibuddy-mini');"
        "var b2=document.getElementById('lumibuddy-bubble');if(!m2||!b2)return;"
        "var r=m2.getBoundingClientRect();"
        "b2.style.left=(r.left+r.width/2)+'px';b2.style.top=(r.top-8)+'px';"
        "b2.style.transform='translate(-50%,-100%)';};}"
        "var b=document.getElementById('lumibuddy-bubble');"
        "if(!b){b=document.createElement('div');b.id='lumibuddy-bubble';"
        "b.style.cssText='position:fixed;z-index:1000;pointer-events:none;display:none;';"
        "document.body.appendChild(b);}"
    )


def _bubble_apply_js(text: str = None, immediate: bool = False) -> str:
    """Show (or hide, when None) the bubble. Assumes _bubble_ensure_js ran.

    A bubble that has only just appeared is not yanked away: hiding is deferred
    until it has been up for BUBBLE_MIN_MS, so hitting Next quickly does not make
    it flash and vanish."""
    if text is None and immediate:
        return (
            "clearTimeout(window._lumiHideTid);"
            "var b=document.getElementById('lumibuddy-bubble');if(b)b.style.display='none';"
            "window._lumiBubbleOn=false;window._lumiBubbleAt=0;"
        )
    if text is None:
        return (
            "var b=document.getElementById('lumibuddy-bubble');"
            "window._lumiHideBubble=function(){var h=document.getElementById('lumibuddy-bubble');"
            "if(h){h.style.display='none';}window._lumiBubbleOn=false;window._lumiBubbleAt=0;};"
            "if(!b||!window._lumiBubbleAt){window._lumiHideBubble();}"
            "else{var left=%d-(Date.now()-window._lumiBubbleAt);"
            "clearTimeout(window._lumiHideTid);"
            "window._lumiHideTid=setTimeout(window._lumiHideBubble,left>0?left:0);}"
        ) % BUBBLE_MIN_MS
    return (
        "clearTimeout(window._lumiHideTid);"
        "var b=document.getElementById('lumibuddy-bubble');if(b){"
        "window._lumiPositionBubble();b.innerHTML=" + json.dumps(_bubble_html(text)) +
        ";b.style.display='block';window._lumiPositionBubble();window._lumiBubbleEnter(b);}"
        "window._lumiBubbleOn=true;window._lumiBubbleAt=Date.now();"
    )


def _bubble_js(text: str = None, immediate: bool = False) -> str:
    return "(function(){" + _bubble_ensure_js() + _bubble_apply_js(text, immediate=immediate) + "})();"


# Where the buddy docks. They are also draggable: grab them to put them
# anywhere (position lasts the session); double-click snaps them back here.
MINI_POSITIONS = {
    "last": "position:fixed;bottom:6px;right:10px;",
    "right": "position:fixed;bottom:6px;right:10px;",
    "center": "position:fixed;bottom:6px;left:50%;transform:translateX(-50%);",
    "middle": "position:fixed;top:42%;left:50%;transform:translate(-50%,-50%);",
}
MINI_POSITION_LABELS = {
    "last": "Same as last time",
    "right": "Bottom-right",
    "center": "Bottom-center",
    "middle": "Middle of the screen",
}
MINI_BASE_EXTRA = (
    BUDDY_FONT_CSS + "z-index:999;text-align:center;opacity:0.9;pointer-events:auto;"
    "font-size:11px;line-height:1.2;cursor:grab;"
)


def _saved_mini_xy():
    """Where the user last dragged them, as (left, top) px, or None."""
    return _position_for_deck(get_config(), "mini_pos_by_deck", "mini_pos_xy")


def _save_mini_xy(xy=None) -> None:
    cfg = get_config()
    _save_position_for_deck(cfg, "mini_pos_by_deck", "mini_pos_xy", xy)
    save_config(cfg)


def _mini_base_css(position: str = None) -> str:
    """The cssText they start from. With "last" this is wherever they were dragged
    to previously, falling back to the bottom-right corner until they are dragged."""
    position = position or get_config().get("mini_position", DEFAULT_CONFIG["mini_position"])
    if position == "last":
        xy = _saved_mini_xy()
        if xy:
            css = f"position:fixed;bottom:auto;right:auto;left:{xy[0]}px;top:{xy[1]}px;"
            return css + MINI_BASE_EXTRA
        position = "right"
    return MINI_POSITIONS.get(position, MINI_POSITIONS["right"]) + MINI_BASE_EXTRA


def _ensure_mini_el_js(position: str = None) -> str:
    position = position or get_config().get("mini_position", DEFAULT_CONFIG["mini_position"])
    base = _mini_base_css(position)
    reset_base = (MINI_POSITIONS["right"] + MINI_BASE_EXTRA) if position == "last" else base
    preset_token = f"{position}:{_current_deck_position_key()}" if position == "last" else position
    return (
        "var el = document.getElementById('lumibuddy-mini');"
        "if(!el){el = document.createElement('div');el.id = 'lumibuddy-mini';"
        "el.title = 'Drag me anywhere! Double-click to snap back.';"
        "document.body.appendChild(el);}"
        "el.dataset.resetCss=" + json.dumps(reset_base) + ";"
        "if(el.dataset.positionKey!==" + json.dumps(preset_token) + "){"
        "el.dataset.positionKey=" + json.dumps(preset_token) + ";"
        "el.style.cssText=" + json.dumps(base) + ";"
        "el.dataset.baseCss=" + json.dumps(base) + ";}"
        "if(!el.dataset.dragwired){el.dataset.dragwired='1';"
        "el.addEventListener('mousedown',function(e){if(e.button!==0)return;e.preventDefault();"
        "window._lumiDrag={dx:e.clientX-el.getBoundingClientRect().left,"
        "dy:e.clientY-el.getBoundingClientRect().top};el.style.cursor='grabbing';});"
        "el.addEventListener('dblclick',function(){el.style.cssText=el.dataset.resetCss||el.dataset.baseCss;"
        "if(window._lumiBubbleOn&&window._lumiPositionBubble){window._lumiPositionBubble();}"
        "if(typeof pycmd==='function'){pycmd('" + _POS_MSG_PREFIX + "clear');}});}"
        "if(!window._lumiDocWired){window._lumiDocWired=true;"
        "document.addEventListener('mousemove',function(e){var d=window._lumiDrag;if(!d)return;"
        "var m=document.getElementById('lumibuddy-mini');if(!m)return;"
        "m.style.left=(e.clientX-d.dx)+'px';m.style.top=(e.clientY-d.dy)+'px';"
        "m.style.right='auto';m.style.bottom='auto';m.style.transform='none';"
        "if(window._lumiBubbleOn&&window._lumiPositionBubble){window._lumiPositionBubble();}});"
        "document.addEventListener('mouseup',function(){"
        "if(window._lumiDrag&&window._lumiReportPos)window._lumiReportPos();"
        "window._lumiDrag=null;"
        "var m=document.getElementById('lumibuddy-mini');if(m)m.style.cursor='grab';});}"
        "window._lumiReportPos=function(){"
        "var m=document.getElementById('lumibuddy-mini');"
        "if(!m||typeof pycmd!=='function')return;"
        "var r=m.getBoundingClientRect();"
        "pycmd('" + _POS_MSG_PREFIX + "set:'+Math.round(r.left)+','+Math.round(r.top));};"
    )


def _eval_in_reviewer(js: str) -> None:
    try:
        mw.reviewer.web.eval(js)
    except Exception:
        pass


def _mini_pet_active() -> bool:
    if not get_config().get("show_during_review", True):
        return False
    return mw.state == "review" and bool(getattr(mw, "reviewer", None))


def greet_pet() -> None:
    """Wave and say hello. Unlike a reaction this has no timeout - it holds until
    the first card is answered (dismissed from on_show_answer)."""
    global _greeting_shown
    if not _mini_pet_active():
        return
    _greeting_shown = True
    # Deliberately ignores show_chatter: the greeting is part of the hello, not chatter.
    caption = _event_caption("greeting", always=True)
    js = """
(function(){
  %s
  %s
  window.lumiBuddyToken = (window.lumiBuddyToken || 0) + 1;
  el.innerHTML = %s;
  %s
})();
""" % (
        _ensure_mini_el_js(),
        _bubble_ensure_js(),
        json.dumps(_mini_html(force_name="waving", ignore_sad=True)),
        _bubble_apply_js(caption),
    )
    _eval_in_reviewer(js)


def dismiss_greeting() -> None:
    """Put them back to idle and drop the bubble once the opening card is done."""
    global _greeting_shown
    if not _greeting_shown or not _mini_pet_active():
        _greeting_shown = False
        return
    _greeting_shown = False
    js = """
(function(){
  %s
  window.lumiBuddyToken = (window.lumiBuddyToken || 0) + 1;
  el.innerHTML = %s;
  %s
})();
""" % (
        _ensure_mini_el_js(),
        json.dumps(_mini_html(force_name="idle")),
        _bubble_apply_js(None),
    )
    _eval_in_reviewer(js)


def show_idle_pet() -> None:
    if not _mini_pet_active():
        return
    global _mini_reaction_until
    _mini_reaction_until = 0.0
    mood = load_state()
    if mood.get("timed_out_current") or int(mood.get("sad_reviews_remaining", 0)) > 0:
        _refresh_sad_pet()
        return
    name = _pick_idle()
    if name in LOOK_POSES:
        # Look through the cycle twice, then back to calm idle.
        js = """
(function(){
  %s
  %s
  window.lumiBuddyToken = (window.lumiBuddyToken || 0) + 1;
  var myToken = window.lumiBuddyToken;
  el.innerHTML = %s;
  %s
  setTimeout(function(){
    if (window.lumiBuddyToken === myToken) { el.innerHTML = %s; }
  }, %d);
})();
""" % (
            _ensure_mini_el_js(),
            _bubble_ensure_js(),
            json.dumps(_mini_html(force_name=name)),
            _bubble_apply_js(None),
            json.dumps(_mini_html(force_name="idle")),
            _look_hold_ms(name),
        )
    else:
        js = """
(function(){
  %s
  window.lumiBuddyToken = (window.lumiBuddyToken || 0) + 1;
  el.innerHTML = %s;
})();
""" % (_ensure_mini_el_js(), json.dumps(_mini_html(force_name=name)))
    _eval_in_reviewer(js)


_message_history = {}
_last_bubble_review_number = None


def _bubble_review_number(event: str):
    """Return (study day, card number) for a bubble's event."""
    state = load_state()
    day = state.get("day", {})
    day_key = (day.get("scheme"), day.get("num"))
    reviews = int(state.get("reviews", 0))
    # Greetings and timeouts happen before the current card is rated and counted.
    return day_key, reviews + 1 if event in ("greeting", "timeout") else reviews


def _custom_message_lines(event: str, cfg: dict = None) -> list:
    """Return clean, non-empty user lines for an event, if custom lines are enabled."""
    cfg = get_config() if cfg is None else cfg
    if not cfg.get("custom_messages_enabled", True):
        return []
    saved = cfg.get("custom_messages", {})
    if not isinstance(saved, dict):
        return []
    lines = saved.get(event, [])
    if not isinstance(lines, (list, tuple)):
        return []
    clean = []
    seen = set()
    for line in lines[:30]:
        if not isinstance(line, str):
            continue
        line = line.strip()[:240]
        if not line:
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        clean.append(line)
    return clean


def _message_lines(event: str, built_in: list, cfg: dict = None) -> list:
    """Mix a category's custom lines with its built-in lines."""
    built_in = list(built_in or [])
    existing = {line.casefold() for line in built_in if isinstance(line, str)}
    return built_in + [
        line for line in _custom_message_lines(event, cfg)
        if line.casefold() not in existing
    ]


def _event_caption(event: str, chance: float = 1.0, always: bool = False, force: bool = False):
    """Choose an event-appropriate line without repeating recent messages."""
    global _last_bubble_review_number
    if not always and not get_config().get("show_chatter", True):
        return None

    review_number = _bubble_review_number(event)
    # Optional chatter respects spacing and its chance. Timeout/recovery
    # messages are guaranteed event feedback, so they bypass both filters.
    if not force and _last_bubble_review_number is not None:
        if review_number[0] != _last_bubble_review_number[0]:
            # A new Anki study day starts a fresh spacing sequence.
            _last_bubble_review_number = None
        elif review_number[1] - _last_bubble_review_number[1] < 2:
            return None
    if not force and chance < 1 and random.random() >= chance:
        return None
    style = _talk_style()
    lines = style.get(event, style.get("review", []) if event in ("hard", "easy") else [])
    lines = _message_lines(event, lines)
    if not lines:
        return None
    key = (_talk_style_key(), event)
    recent = _message_history.get(key, [])
    choices = [line for line in lines if line not in recent]
    if not choices:
        choices = [line for line in lines if not recent or line != recent[-1]] or lines
    line = random.choice(choices)
    _message_history[key] = (recent + [line])[-3:]
    _last_bubble_review_number = review_number
    return _clean_message(line)


def animate_reaction(name: str, min_duration_ms: int, caption: str = None) -> None:
    if not _mini_pet_active():
        return

    global _mini_reaction_until
    frames = _sprite_spec(name)[1]
    natural_ms = int(round(frames * _sprite_frame_seconds(name) * 1000)) + 50
    duration_ms = max(natural_ms, min_duration_ms)
    _mini_reaction_until = time.time() + duration_ms / 1000.0

    html_now = _mini_html(force_name=name)
    js = """
(function(){
  %s
  %s
  window.lumiBuddyToken = (window.lumiBuddyToken || 0) + 1;
  var myToken = window.lumiBuddyToken;
  el.innerHTML = %s;
  %s
  setTimeout(function(){
    if (window.lumiBuddyToken === myToken) { el.innerHTML = %s; %s }
  }, %d);
})();
""" % (
        _ensure_mini_el_js(),
        _bubble_ensure_js(),
        json.dumps(html_now),
        _bubble_apply_js(caption),
        json.dumps(_mini_html()),
        _bubble_apply_js(None),
        duration_ms,
    )
    _eval_in_reviewer(js)


def animate_run_around(caption: str = None) -> None:
    """Celebration variant: they run left, then run back right to where they
    started, then settles back into calm idle."""
    if not _mini_pet_active():
        return

    global _mini_reaction_until
    left_ms = int(round(_sprite_spec("running_left")[1] * FRAME_SECONDS * 1000)) + 50
    right_ms = int(round(_sprite_spec("running_right")[1] * FRAME_SECONDS * 1000)) + 50
    _mini_reaction_until = time.time() + (left_ms + right_ms) / 1000.0

    html_left = _mini_html(force_name="running_left")
    html_right = _mini_html(force_name="running_right")
    html_idle = _mini_html(force_name="idle")
    js = """
(function(){
  %s
  %s
  window.lumiBuddyToken = (window.lumiBuddyToken || 0) + 1;
  var myToken = window.lumiBuddyToken;
  el.innerHTML = %s;
  %s
  setTimeout(function(){
    if (window.lumiBuddyToken !== myToken) return;
    el.innerHTML = %s;
    setTimeout(function(){
      if (window.lumiBuddyToken === myToken) { el.innerHTML = %s; %s }
    }, %d);
  }, %d);
})();
""" % (
        _ensure_mini_el_js(),
        _bubble_ensure_js(),
        json.dumps(html_left),
        _bubble_apply_js(caption),
        json.dumps(html_right),
        json.dumps(html_idle),
        _bubble_apply_js(None),
        right_ms,
        left_ms,
    )
    _eval_in_reviewer(js)


def on_show_question(card) -> None:
    global _review_greeted, _focus_waiting_to_begin
    if not _review_greeted:
        _focus_waiting_to_begin = True
    _start_focus_timer()
    if not _review_greeted:
        _review_greeted = True
        greet_pet()
        return
    # The greeting owns the pose until the first card is answered, so a repeat
    # question event must not knock them back to idle.
    if _greeting_shown or time.time() < _mini_reaction_until:
        return
    # Keep a recent rating bubble visible for its minimum display time.
    _eval_in_reviewer(_bubble_js(None))
    show_idle_pet()


def on_show_answer(*_args) -> None:
    global _focus_waiting_to_begin
    # Recall time ends as soon as the answer is revealed.
    _focus_waiting_to_begin = False
    _pause_focus_timer_after_reveal()
    dismiss_greeting()
    if not _mini_pet_active():
        return
    # Revealing an answer ends the previous pose's delayed callback.
    _eval_in_reviewer("window.lumiBuddyToken=(window.lumiBuddyToken||0)+1;")
    show_idle_pet()


def on_reviewer_will_end(*_args) -> None:
    global _review_greeted, _greeting_shown, _focus_waiting_to_begin, _review_position_deck_key
    # Leaving review should not let an old question time out in the background.
    _stop_focus_timer()
    _review_greeted = False
    _greeting_shown = False
    _focus_waiting_to_begin = False
    _review_position_deck_key = None


# ---------------------------------------------------------------------------
# Review hook: Good -> jumping/waving/run-around, Again -> calm idle. A recall
# timeout separately triggers the sad pose and five-review recovery counter.
# ---------------------------------------------------------------------------
def on_answer(reviewer, card, ease: int) -> None:
    cfg = get_config()
    state = load_state()
    before_review = dict(state)
    show_review_cat = cfg.get("show_during_review", True)
    _stop_focus_timer()

    state["reviews"] += 1
    if ease == 1:
        state["streak"] = 0
    else:
        state["correct"] = int(state.get("correct", 0)) + 1
        state["streak"] = int(state.get("streak", 0)) + 1
        state["best_streak"] = max(state["best_streak"], state["streak"])

    was_sad = _penalty(state)[0]

    # --- recall-timeout penalty burns down ---
    if bool(state.get("timed_out_current")):
        # The timed-out card does not consume one of the later recovery reviews.
        state["timed_out_current"] = False
    elif int(state.get("sad_reviews_remaining", 0)) > 0:
        state["sad_reviews_remaining"] = max(0, int(state["sad_reviews_remaining"]) - 1)

    # --- hardcore: N misses in a row puts them out of sorts ---
    triggered_hardcore = False
    if _hardcore_on():
        if ease == 1:
            state["consecutive_misses"] = int(state.get("consecutive_misses", 0)) + 1
            if state["consecutive_misses"] >= _hardcore_misses():
                state["consecutive_misses"] = 0
                state["hardcore_sad_remaining"] = _hardcore_recovery()
                state["hardcore_sad_total"] = _hardcore_recovery()
                triggered_hardcore = True
        else:
            state["consecutive_misses"] = 0
        # The card that tipped them over does not also count as recovery.
        if int(state.get("hardcore_sad_remaining", 0)) > 0 and not triggered_hardcore:
            state["hardcore_sad_remaining"] = max(0, int(state["hardcore_sad_remaining"]) - 1)

    still_sad = _penalty(state)[0]
    just_recovered = was_sad and not still_sad

    save_state(state)
    _remember_review(card, before_review, state)
    if show_review_cat:
        rating_caption = None
        if not triggered_hardcore and not just_recovered and cfg.get("show_rating_messages", True):
            # Good and Easy both use the same general praise pool.
            event = {1: "encouragement", 2: "hard", 3: "review", 4: "review"}.get(ease, "review")
            rating_caption = _event_caption(event, chance=_chatter_chance())
        if triggered_hardcore:
            strict_caption = _event_caption("strict")
            animate_reaction("failed", REACTION_HOLD_MS, caption=strict_caption)
        elif just_recovered:
            # The last recovery review landed — celebrate instead of the usual reaction.
            recovery_caption = _event_caption("recovery", always=True, force=True)
            animate_reaction(
                _pick_celebration(include_run=False), RECOVERY_HOLD_MS, caption=recovery_caption
            )
        elif still_sad:
            _refresh_sad_pet()
            _eval_in_reviewer(_bubble_js(rating_caption))
        elif ease == 1:
            animate_reaction("idle", REACTION_HOLD_MS, caption=rating_caption)
        else:
            # Review reactions must stay anchored to the user's chosen position.
            # The run-around animation is reserved for the home screen.
            move = _pick_celebration(include_run=False)
            animate_reaction(move, REACTION_HOLD_MS, caption=rating_caption)

# ---------------------------------------------------------------------------
# Character gallery and settings
# ---------------------------------------------------------------------------
class CharacterGallery(QDialog):
    """Animated character picker; changes remain pending until settings are saved."""

    def __init__(self, selected_key: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose your Focus Friend")
        self.selected_key = selected_key
        self._frame_index = 0
        self._cards = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        grid = QGridLayout()
        grid.setSpacing(10)
        character_keys = sorted(PET_PROFILES, key=lambda key: PET_PROFILES[key]["label"].casefold())
        for index, key in enumerate(character_keys):
            profile = PET_PROFILES[key]
            button = QToolButton()
            button.setText(profile["label"])
            button.setToolTip(f"Choose {profile['label']}")
            button.setAccessibleName(f"Choose {profile['label']}")
            button.setCheckable(True)
            button.setFixedSize(118, 136)
            button.setIconSize(QSize(86, 94))
            button.setToolButtonStyle(_qt_enum("ToolButtonStyle", "ToolButtonTextUnderIcon"))
            button.setStyleSheet(
                "QToolButton { border:2px solid transparent; border-radius:12px; padding:5px; }"
                "QToolButton:hover { background:palette(alternate-base); }"
                "QToolButton:checked { border-color:palette(highlight); background:palette(alternate-base); }"
            )
            self._group.addButton(button, index)
            button.setChecked(key == selected_key)
            button.clicked.connect(lambda _checked=False, k=key: self._choose(k))
            basename, count, _loop = profile["sprites"]["idle"]
            frame_w, frame_h = _pet_frame_size(key)
            strip = QPixmap(_sprite_path(basename))
            frames = []
            if not strip.isNull():
                for frame_index in range(count):
                    frame = strip.copy(frame_index * frame_w, 0, frame_w, frame_h)
                    frames.append(QIcon(frame.scaled(86, 94, _KEEP_ASPECT, _SMOOTH_TRANSFORM)))
            if frames:
                button.setIcon(frames[0])
            self._cards.append((button, frames))
            grid.addWidget(button, index // 4, index % 4)

        content = QWidget()
        content.setLayout(grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setMinimumSize(550, 440)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Choose character")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        note = QLabel("Pick a buddy, then try their moods in the settings preview.")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(scroll)
        layout.addWidget(buttons)
        self.resize(580, 580)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(int(FRAME_SECONDS * 1000))

    def _choose(self, key: str) -> None:
        self.selected_key = key

    def _advance(self) -> None:
        self._frame_index += 1
        for button, frames in self._cards:
            if frames:
                button.setIcon(frames[self._frame_index % len(frames)])

    def done(self, result):
        self._timer.stop()
        super().done(result)


class AppearancePreview(QWidget):
    """Small, native Qt sample. Never opens a browser or touches review state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(340, 420)
        self.cfg = None
        self.frames = []
        self.sprite_key = None
        self.started = self.bubble_started = time.monotonic()
        self.animation = QTimer(self)
        self.animation.timeout.connect(self.update)

    def set_sample(self, cfg, seconds, remaining, dark, replay=False):
        self.cfg = cfg
        self.seconds, self.remaining, self.dark = seconds, remaining, dark
        sprite = "failed" if remaining else "jumping"
        key = (cfg["character"], sprite)
        if key != self.sprite_key:
            spec = _pet_profile(cfg["character"])["sprites"][sprite]
            frame_w, frame_h = _pet_frame_size(cfg["character"])
            strip = QPixmap(_sprite_path(spec[0]))
            self.frames = [strip.copy(i * frame_w, 0, frame_w, frame_h).scaled(
                85, 92, _KEEP_ASPECT, _SMOOTH_TRANSFORM) for i in range(spec[1])] if not strip.isNull() else []
            self.sprite_key = key
            self.started = time.monotonic()
        bubble_key = (cfg["talking_style"], cfg["bubble_font_size"], cfg["color_theme"], bool(remaining))
        if replay or bubble_key != getattr(self, "bubble_key", None):
            self.bubble_started = time.monotonic()
        self.bubble_key = bubble_key
        self.update()

    def set_active(self, active):
        if active:
            self.animation.start(40)
        else:
            self.animation.stop()

    def paintEvent(self, event):
        if self.cfg is None:
            return
        cfg = self.cfg
        theme = _theme(cfg)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#202124" if self.dark else "#f6f3f8"))
        dot = QColor("#ffffff" if self.dark else "#5a466e")
        dot.setAlpha(16 if self.dark else 23)
        painter.setPen(QPen(dot, 1))
        for x in range(8, self.width(), 16):
            for y in range(8, self.height(), 16):
                painter.drawPoint(x, y)
        center = self.width() / 2
        flags = int(_ALIGN_CENTER) | int(_qt_enum("TextFlag", "TextWordWrap"))

        def font(size, bold=False):
            f = QFont(self.font())
            f.setPixelSize(max(1, round(size)))
            f.setBold(bold)
            painter.setFont(f)

        def panel(rect, fill, edge, radius):
            painter.setPen(QPen(edge, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, radius, radius)

        scale = max(60, min(180, cfg["timer_size"])) / 100
        style = cfg["timer_style"]
        ring = style == "ring"
        compact = style in {"pulse", "tab"}
        tw, th = ((88, 102) if ring else (154, 34) if compact else (112, 73))
        rect = QRectF(center - tw * scale / 2, (180 - th * scale) / 2, tw * scale, th * scale)
        accent = QColor(theme["accent"])
        fill = QColor(theme["bubble"] if style == "kawaii" else theme["surface"])
        fill.setAlphaF(cfg["timer_opacity"] / 100 if style == "glass" else .55 if ring else .88)
        if style == "kawaii":
            fill.setAlpha(255)
        edge = QColor(accent)
        edge.setAlphaF(.6 if style == "kawaii" else .3)
        if style != "tab":
            panel(rect, fill, edge, (28 if style == "kawaii" else 20 if ring else 15) * scale)
        ink = QColor(theme["ink"] if style in {"kawaii", "tab"} else "#ffffff")
        total = max(1, cfg["focus_seconds"])
        portion = max(0, min(1, self.seconds / total))
        progress = QColor("#e86b78" if not self.seconds else "#e5a84b" if self.seconds <= max(1, round(total * .3)) else theme["accent"])
        if ring:
            circle = QRectF(center - 28 * scale, rect.top() + 11 * scale, 56 * scale, 56 * scale)
            painter.setBrush(_qt_enum("BrushStyle", "NoBrush"))
            track = QColor(accent); track.setAlphaF(.18)
            painter.setPen(QPen(track, 3.5 * scale))
            painter.drawEllipse(circle)
            painter.setPen(QPen(progress, 3.5 * scale))
            painter.drawArc(circle, 90 * 16, -round(360 * 16 * portion))
            count_rect = circle
            title_rect = QRectF(rect.left(), rect.bottom() - 22 * scale, rect.width(), 16 * scale)
        elif compact:
            bar_height = (4 if style == "tab" else 5) * scale
            bar = QRectF(rect.left() + 8 * scale, rect.center().y() - bar_height / 2,
                         rect.width() - 42 * scale, bar_height)
            track = QColor(accent)
            track.setAlphaF(.2)
            painter.setPen(_qt_enum("PenStyle", "NoPen"))
            painter.setBrush(track)
            painter.drawRoundedRect(bar, bar_height / 2, bar_height / 2)
            filled_bar = QRectF(bar.left(), bar.top(), bar.width() * portion, bar.height())
            painter.setBrush(progress)
            painter.drawRoundedRect(filled_bar, bar_height / 2, bar_height / 2)
            count_rect = QRectF(rect.right() - 31 * scale, rect.top() + 6 * scale,
                                25 * scale, 22 * scale)
            if style == "tab":
                painter.setPen(QPen(edge, 1))
                painter.setBrush(QColor(theme["bubble"]))
                painter.drawRoundedRect(count_rect, 7 * scale, 7 * scale)
        else:
            title_rect = QRectF(rect.left(), rect.top() + 6 * scale, rect.width(), 14 * scale)
            count_rect = QRectF(rect.left(), rect.top() + 20 * scale, rect.width(), 32 * scale)
            track = QColor(ink if style == "kawaii" else accent); track.setAlphaF(.18)
            bar = QRectF(rect.left() + 12 * scale, rect.bottom() - 11 * scale, rect.width() - 24 * scale, 3 * scale)
            painter.fillRect(bar, track)
            painter.fillRect(QRectF(bar.left(), bar.top(), bar.width() * portion, bar.height()), progress)
        painter.setPen(ink)
        if not compact:
            font(9 * scale, True)
            painter.drawText(title_rect, flags, "TIME'S UP" if not self.seconds else "RECALL")
        font((11 if compact else 24) * scale, True)
        painter.drawText(count_rect, flags, str(self.seconds) if self.seconds else "—")

        # Match the review bubble's soft fade and four-pixel rise.
        elapsed = min(1, (time.monotonic() - self.bubble_started) / .18)
        painter.save()
        painter.setOpacity(elapsed)
        bubble = QRectF(12, 188 + 4 * (1 - elapsed), self.width() - 24, 74)
        panel(bubble, QColor(theme["bubble"]), accent, 13)
        painter.setPen(QColor(theme["ink"]))
        font(cfg["bubble_font_size"])
        voice = TALK_STYLES[cfg["talking_style"]]
        caption = voice["review" if self.remaining else "recovery"][0]
        caption = _clean_message(caption)
        painter.drawText(bubble.adjusted(10, 6, -10, -6), flags, caption)
        painter.restore()
        if self.frames:
            frame_seconds = _sprite_frame_seconds(self.sprite_key[1])
            frame = self.frames[int((time.monotonic() - self.started) / frame_seconds) % len(self.frames)]
            painter.drawPixmap(round(center - frame.width() / 2), 272, frame)
        if cfg["show_recovery_counter"]:
            display = cfg["recovery_display"]
            total_recovery = max(1, cfg["recovery_reviews"])
            filled = 5 * (1 - self.remaining / total_recovery)
            painter.setPen(accent)
            if display != "text":
                font(16)
                for i in range(5):
                    heart = QRectF(center - 50 + i * 20, 366, 20, 21)
                    painter.drawText(heart, flags, "♡")
                    painter.save()
                    painter.setClipRect(QRectF(heart.left(), heart.top(), heart.width() * max(0, min(1, filled - i)), heart.height()))
                    painter.drawText(heart, flags, "♥")
                    painter.restore()
            if display != "hearts":
                font(11)
                text = (f"Okay again in {self.remaining} review{'s' if self.remaining != 1 else ''}"
                        if self.remaining else "All better!")
                counter = QRectF(16, 386 if display == "hearts_text" else 366, self.width() - 32, 26)
                look = cfg["counter_style"]
                if display == "text" and look != "simple":
                    background = QColor(theme["accent"] if look == "kawaii" else theme["surface"])
                    background.setAlphaF(.22 if look == "transparent" else 1 if look == "kawaii" else .88)
                    panel(counter, background, accent, 13 if look == "kawaii" else 8)
                    painter.setPen(QColor(theme["ink"]) if look == "kawaii" else accent)
                painter.drawText(counter, flags, text)
        painter.end()


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(ADDON_NAME)
        cfg = get_config()

        def with_reset(widget, default_label, reset_fn):
            btn = QPushButton(f"Reset ({default_label})")
            btn.clicked.connect(reset_fn)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(widget)
            row.addWidget(btn)
            container = QWidget()
            container.setLayout(row)
            return container

        def spin_row(lo, hi, val, default):
            box = QSpinBox()
            box.setRange(lo, hi)
            box.setValue(int(val))
            row = with_reset(box, str(default), lambda: box.setValue(default))
            return box, row

        def slider_spin_row(lo, hi, val, default, suffix=" px"):
            """Compact slider plus editable numeric value and reset button."""
            box = QSpinBox()
            box.setRange(lo, hi)
            box.setSuffix(suffix)
            box.setValue(int(val))
            slider = QSlider(_qt_enum("Orientation", "Horizontal"))
            slider.setRange(lo, hi)
            slider.setValue(int(val))
            slider.setMinimumWidth(170)
            slider.valueChanged.connect(box.setValue)
            box.valueChanged.connect(slider.setValue)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(slider, 1)
            row.addWidget(box)
            reset = QPushButton(f"Reset ({default})")
            reset.clicked.connect(lambda: box.setValue(default))
            row.addWidget(reset)
            container = QWidget()
            container.setLayout(row)
            return box, container

        def section(title, form, explanation, note_min_height=0):
            box = QGroupBox(title)
            box.setStyleSheet("QGroupBox { font-weight: 700; font-size: 14px; }")
            inner = QVBoxLayout(box)
            inner.setSpacing(8)
            note = QLabel(explanation)
            note.setWordWrap(True)
            if note_min_height:
                note.setMinimumHeight(note_min_height)
                note.setAlignment(
                    _qt_enum("AlignmentFlag", "AlignTop")
                    | _qt_enum("AlignmentFlag", "AlignLeft")
                )
            inner.addWidget(note)
            inner.addLayout(form)
            return box

        self.name_edit = QLineEdit(cfg["pet_name"])
        self.character_combo = QComboBox()
        self._character_keys = sorted(PET_PROFILES, key=lambda key: PET_PROFILES[key]["label"].casefold())
        for key in self._character_keys:
            self.character_combo.addItem(PET_PROFILES[key]["label"])
        selected_character = cfg.get("character", "lumi")
        if selected_character not in self._character_keys:
            selected_character = "lumi"
        self.character_combo.setCurrentIndex(self._character_keys.index(selected_character))
        self.character_combo.currentIndexChanged.connect(self._character_changed)
        self.character_label = QLabel(PET_PROFILES[selected_character]["label"])
        self.character_combo.hide()
        self.gallery_button = QPushButton("Choose character…")
        self.gallery_button.clicked.connect(self._open_gallery)
        character_row = QHBoxLayout()
        character_row.setContentsMargins(0, 0, 0, 0)
        character_row.addWidget(self.character_label)
        character_row.addStretch()
        character_row.addWidget(self.gallery_button)
        self.character_picker = QWidget()
        self.character_picker.setLayout(character_row)

        self.neutral_spin, neutral_row = spin_row(2, 100000, cfg["mood_neutral_at"], DEFAULT_CONFIG["mood_neutral_at"])
        self.happy_spin, happy_row = spin_row(3, 200000, cfg["mood_happy_at"], DEFAULT_CONFIG["mood_happy_at"])
        self.excited_spin, excited_row = spin_row(4, 300000, cfg["mood_excited_at"], DEFAULT_CONFIG["mood_excited_at"])
        self.size_spin, size_row = slider_spin_row(
            60, 300, cfg["sprite_size"], DEFAULT_CONFIG["sprite_size"]
        )
        self.mini_size_spin, mini_size_row = slider_spin_row(
            100, 400, cfg.get("mini_size", DEFAULT_CONFIG["mini_size"]), DEFAULT_CONFIG["mini_size"]
        )

        self.focus_spin, focus_row = spin_row(
            1, 600, cfg.get("focus_seconds", DEFAULT_CONFIG["focus_seconds"]), DEFAULT_CONFIG["focus_seconds"]
        )
        self.focus_spin.setToolTip(
            "How many seconds you have to recall each card before the buddy looks worried.\n\n"
            f"Recommended: {DEFAULT_CONFIG['focus_seconds']} seconds. "
            "Higher is more forgiving; lower is stricter. Does not affect Anki's scheduling."
        )
        self.recovery_spin, recovery_row = spin_row(
            1, 100, cfg.get("recovery_reviews", DEFAULT_CONFIG["recovery_reviews"]), DEFAULT_CONFIG["recovery_reviews"]
        )
        self.recovery_spin.setToolTip(
            "How many completed reviews before the buddy is okay again after you run out of time.\n\n"
            f"Recommended: {DEFAULT_CONFIG['recovery_reviews']}. "
            "Lower is a quicker recovery, higher keeps them sad for longer."
        )

        self.mini_check = QCheckBox("Show buddy during reviews")
        self.mini_check.setChecked(bool(cfg["show_during_review"]))

        self.chatter_check = QCheckBox("Show review messages")
        self.chatter_check.setChecked(bool(cfg.get("show_chatter", True)))
        self.chatter_check.setToolTip("Show optional message bubbles after you rate a card. Timeout and recovery messages always appear when those events happen; the session greeting appears once at the start.")
        self.rating_messages_check = QCheckBox("Sometimes react to Again, Hard, Good, or Easy")
        self.rating_messages_check.setChecked(bool(cfg.get("show_rating_messages", True)))
        self.rating_messages_check.setToolTip(
            "Choose occasional praise or encouragement after you rate a card. "
            "Messages appear after your rating. Set the chance using Optional message frequency below."
        )
        self.freq_combo = QComboBox()
        self._freq_keys = list(BUBBLE_FREQUENCIES)
        for key in self._freq_keys:
            self.freq_combo.addItem(BUBBLE_FREQUENCIES[key]["label"])
        saved_percent = int(cfg.get("chatter_percent", DEFAULT_CONFIG["chatter_percent"]))
        self.freq_combo.setCurrentIndex(self._freq_keys.index(_nearest_frequency_key(saved_percent)))
        self.freq_combo.setToolTip(
            "This chance is checked for each enabled rating event. "
            "Optional bubbles are skipped on the same card and the card right after another bubble. "
            "Timeout and recovery messages are guaranteed and can appear back-to-back.\n\n"
            + "\n".join(
                f"{BUBBLE_FREQUENCIES[k]['label'].replace('  (recommended)', '')}"
                f" — {BUBBLE_FREQUENCIES[k]['rate']}"
                for k in self._freq_keys
            )
            + "\n\nSometimes is the recommended setting."
        )
        self.bubble_size_spin, self.bubble_size_row = slider_spin_row(
            8, 28, cfg.get("bubble_font_size", DEFAULT_CONFIG["bubble_font_size"]),
            DEFAULT_CONFIG["bubble_font_size"],
        )
        self.bubble_size_spin.setToolTip(
            "How big the text in their speech bubbles is.\n\n"
            f"Recommended: {DEFAULT_CONFIG['bubble_font_size']}. Larger text also widens "
            "the bubble so longer lines still fit."
        )

        self.freq_row = QWidget()
        freq_layout = QHBoxLayout()
        freq_layout.setContentsMargins(0, 0, 0, 0)
        freq_layout.addWidget(self.freq_combo)
        self.freq_row.setLayout(freq_layout)
        self.chatter_check.toggled.connect(self._update_message_controls)
        self.rating_messages_check.toggled.connect(self._update_message_controls)
        self._update_message_controls()

        self.pos_combo = QComboBox()
        self._pos_keys = list(MINI_POSITION_LABELS)
        for key in self._pos_keys:
            self.pos_combo.addItem(MINI_POSITION_LABELS[key])
        saved_pos = cfg.get("mini_position", DEFAULT_CONFIG["mini_position"])
        if saved_pos not in self._pos_keys:
            saved_pos = DEFAULT_CONFIG["mini_position"]
        self.pos_combo.setCurrentIndex(self._pos_keys.index(saved_pos))
        self.pos_combo.setToolTip(
            "Where they start each review.\n\n"
            "Same as last time remembers a separate spot for each deck. A deck you have not "
            "moved them in yet uses the last saved spot. Double-click them to reset that deck's spot."
        )

        self.timer_pos_combo = QComboBox()
        self._timer_pos_keys = list(TIMER_POSITION_LABELS)
        for key in self._timer_pos_keys:
            self.timer_pos_combo.addItem(TIMER_POSITION_LABELS[key])
        saved_timer_pos = cfg.get("timer_position", DEFAULT_CONFIG["timer_position"])
        # Existing versions remembered drags for every preset. Keep those locations.
        if cfg.get("timer_pos_xy") is not None:
            saved_timer_pos = "last"
        if saved_timer_pos not in self._timer_pos_keys:
            saved_timer_pos = DEFAULT_CONFIG["timer_position"]
        self.timer_pos_combo.setCurrentIndex(self._timer_pos_keys.index(saved_timer_pos))
        self.timer_pos_combo.setToolTip(
            "Same as last time remembers a separate spot for each deck, including after restarting Anki. "
            "A deck you have not moved the timer in yet uses the last saved spot. "
            "Other choices start each card at that preset. Double-click resets the position."
        )

        self.recovery_behavior_combo = QComboBox()
        self.recovery_behavior_combo.addItem("Reset the recovery counter", "reset")
        self.recovery_behavior_combo.addItem("Hold the remaining reviews steady", "hold")
        self.recovery_behavior_combo.setCurrentIndex(
            1 if cfg.get("recovery_timeout_behavior") == "hold" else 0
        )
        self.recovery_behavior_combo.setToolTip(
            "If another card times out while they are recovering: reset starts the full "
            "recovery again; hold keeps the remaining count. A timed-out card never "
            "counts toward recovery. The first timeout starts recovery in either mode."
        )

        self.focus_check = QCheckBox("Show thinking countdown timer and enable timeout recovery")
        self.focus_check.setChecked(bool(cfg.get("show_focus_timer", True)))
        self.focus_check.setToolTip(
            "Uncheck to remove the countdown timer entirely.\n\n"
            "Turning this off clears timeout recovery. Hardcore mode has its own "
            "independent recovery setting."
        )
        self.focus_row = QWidget()
        focus_layout = QHBoxLayout()
        focus_layout.setContentsMargins(0, 0, 0, 0)
        focus_layout.addWidget(focus_row)
        self.focus_row.setLayout(focus_layout)
        self.focus_row.setEnabled(bool(cfg.get("show_focus_timer", True)))
        self.focus_check.toggled.connect(self.focus_row.setEnabled)

        self.recovery_counter_check = QCheckBox("Show recovery hearts / counter")
        self.recovery_counter_check.setChecked(bool(cfg.get("show_recovery_counter", True)))
        self.recovery_counter_check.setToolTip(
            "Show recovery progress below the buddy. Hearts refill as you finish reviews.\n"
            "Choose hearts or a text counter in Appearance. Turning this off hides the display."
        )

        self.hardcore_check = QCheckBox("HARDCORE MODE")
        self.hardcore_check.setChecked(bool(cfg.get("hardcore_mode", DEFAULT_CONFIG["hardcore_mode"])))
        self.hardcore_check.setToolTip(
            "Miss too many cards in a row and they get upset.\n\n"
            "They then stay out of sorts for a set number of reviews, whatever you "
            "answer - you have to earn it back. Off by default."
        )
        self.hardcore_misses_spin, self.hardcore_misses_row = spin_row(
            1, 100, cfg.get("hardcore_misses", DEFAULT_CONFIG["hardcore_misses"]),
            DEFAULT_CONFIG["hardcore_misses"],
        )
        self.hardcore_misses_spin.setToolTip(
            "How many Again answers in a row upset them.\n\n"
            f"Recommended: {DEFAULT_CONFIG['hardcore_misses']}. A correct answer at any "
            "point resets the run to zero."
        )
        self.hardcore_recovery_spin, self.hardcore_recovery_row = spin_row(
            1, 100, cfg.get("hardcore_recovery", DEFAULT_CONFIG["hardcore_recovery"]),
            DEFAULT_CONFIG["hardcore_recovery"],
        )
        self.hardcore_recovery_spin.setToolTip(
            "How many reviews they stay out of sorts for.\n\n"
            f"Recommended: {DEFAULT_CONFIG['hardcore_recovery']}. Higher is a longer "
            "penalty; they celebrate on the review that clears it."
        )
        self.hardcore_note = QLabel(
            "Miss the run → they get sad. Finish the recovery run → they celebrate."
        )
        self.hardcore_note.setWordWrap(True)
        self.hardcore_note.setStyleSheet("font-size:11px;")
        for row in (self.hardcore_misses_row, self.hardcore_recovery_row):
            row.setEnabled(bool(cfg.get("hardcore_mode", False)))
        self.hardcore_check.toggled.connect(self.hardcore_misses_row.setEnabled)
        self.hardcore_check.toggled.connect(self.hardcore_recovery_row.setEnabled)

        self.custom_message_categories = [
            ("Greeting", "greeting"),
            ("Again encouragement", "encouragement"),
            ("Hard reaction", "hard"),
            ("Good / Easy praise", "review"),
            ("Timeout", "timeout"),
            ("Recovery", "recovery"),
            ("Hardcore", "strict"),
            ("Home-screen dialogue", "dialogue"),
        ]
        stored_custom = cfg.get("custom_messages", {})
        self._custom_message_drafts = {}
        for _label, key in self.custom_message_categories:
            value = stored_custom.get(key, []) if isinstance(stored_custom, dict) else []
            self._custom_message_drafts[key] = list(value) if isinstance(value, list) else []
        self._current_custom_event = "greeting"
        self._custom_preview_index = 0

        self.custom_messages_check = QCheckBox("Use my messages alongside the built-in messages")
        self.custom_messages_check.setChecked(bool(cfg.get("custom_messages_enabled", True)))
        self.custom_messages_check.setToolTip(
            "When enabled, your lines are mixed into the selected categories with the built-in lines."
        )
        self.custom_event_combo = QComboBox()
        for label, key in self.custom_message_categories:
            self.custom_event_combo.addItem(label, key)
        self.custom_message_edit = QPlainTextEdit()
        self.custom_message_edit.setPlaceholderText("Type one message per line…")
        self.custom_message_edit.setMinimumHeight(190)
        self.custom_message_edit.setPlainText("\n".join(self._custom_message_drafts["greeting"]))
        self.custom_message_note = QLabel(
            "One message per line. Up to 30 lines per category; each line is limited to 240 characters. "
            "Optional reactions still use the frequency and spacing selected on Message Bubbles."
        )
        self.custom_message_note.setWordWrap(True)
        self.custom_preview_button = QPushButton("Preview a line")
        self.custom_clear_button = QPushButton("Clear this category")
        self.custom_restore_button = QPushButton("Restore built-in messages")
        self.custom_preview_text = QLabel("Your preview will appear here.")
        self.custom_preview_text.setWordWrap(True)
        self.custom_preview_text.setAlignment(_ALIGN_CENTER)
        self.custom_preview_text.setMinimumHeight(48)
        self.custom_preview_text.setStyleSheet(
            "padding:8px; border:1px solid #999; border-radius:12px;"
        )
        custom_actions = QHBoxLayout()
        custom_actions.addWidget(self.custom_preview_button)
        custom_actions.addWidget(self.custom_clear_button)
        custom_actions.addWidget(self.custom_restore_button)
        custom_actions.addStretch()
        custom_messages = QVBoxLayout()
        custom_settings_form = QFormLayout()
        custom_settings_form.addRow(self.custom_messages_check)
        custom_messages.addWidget(section(
            "Write your own lines",
            custom_settings_form,
            "Your messages join the built-in Kawaii lines for the event you choose. No messages are shown while you recall or reveal an answer. "
            "Good and Easy share one category; timeout and recovery messages still appear whenever those events happen.",
        ))
        custom_editor_form = QFormLayout()
        custom_editor_form.addRow("Message category:", self.custom_event_combo)
        custom_editor_form.addRow(self.custom_message_edit)
        custom_messages.addWidget(section("Message editor", custom_editor_form, self.custom_message_note))
        custom_messages.addLayout(custom_actions)
        custom_messages.addWidget(self.custom_preview_text)
        self.custom_event_combo.currentIndexChanged.connect(self._custom_category_changed)
        self.custom_message_edit.textChanged.connect(self._custom_editor_changed)
        self.custom_messages_check.toggled.connect(self._update_custom_message_controls)
        self.custom_preview_button.clicked.connect(self._preview_custom_message)
        self.custom_clear_button.clicked.connect(self.custom_message_edit.clear)
        self.custom_restore_button.clicked.connect(self._restore_builtin_messages)
        self._update_custom_message_controls()

        self.counter_style_combo = QComboBox()
        self._counter_style_keys = list(RECOVERY_COUNTER_STYLES)
        for key in self._counter_style_keys:
            self.counter_style_combo.addItem(RECOVERY_COUNTER_STYLES[key])
        saved_look = cfg.get("counter_style", DEFAULT_CONFIG["counter_style"])
        if saved_look not in self._counter_style_keys:
            saved_look = DEFAULT_CONFIG["counter_style"]
        self.counter_style_combo.setCurrentIndex(self._counter_style_keys.index(saved_look))
        self.counter_style_combo.setToolTip(
            "How the \"Okay again in N reviews\" box looks.\n\n"
            "Solid is the plain dark chip, Transparent is see-through, "
            "Plain text has no background at all, Kawaii is a pink lozenge."
        )

        self.mood_bar_check = QCheckBox("Show mood label, progress bar, and card count")
        self.mood_bar_check.setChecked(bool(cfg["show_mood_bar"]))

        self.dialogue_check = QCheckBox("Show dialogue bubble + spell text")
        self.dialogue_check.setChecked(bool(cfg.get("show_dialogue", True)))

        self.run_check = QCheckBox("Buddy runs across the deck browser at high moods")
        self.run_check.setChecked(bool(cfg.get("run_across", True)))

        self.side_check = QCheckBox("Dock buddy to the right side on wide windows")
        self.side_check.setChecked(bool(cfg.get("side_panel", True)))

        # A one-line nudge under the review-size field. The sprite is rebuilt when
        # the next question appears, so that is when the new size lands.
        self.mini_size_note = QLabel(
            "Changed here? The new size shows up on your next card."
        )
        self.mini_size_note.setStyleSheet("color:#8a8a8a; font-size:11px;")
        self.mini_size_note.setWordWrap(True)
        self.mini_size_note.setVisible(False)
        self._saved_mini_size = int(cfg.get("mini_size", DEFAULT_CONFIG["mini_size"]))
        self.mini_size_spin.valueChanged.connect(self._note_mini_size_change)

        self.theme_combo = QComboBox()
        for key, theme in COLOR_THEMES.items():
            self.theme_combo.addItem(theme["label"], key)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(cfg.get("color_theme", "sakura"))))
        self.timer_style_combo = QComboBox()
        for key, label in TIMER_STYLES.items():
            self.timer_style_combo.addItem(label, key)
        self.timer_style_combo.setCurrentIndex(max(0, self.timer_style_combo.findData(cfg.get("timer_style", "pulse"))))
        self.timer_opacity_slider = QSlider(_qt_enum("Orientation", "Horizontal"))
        self.timer_opacity_slider.setRange(0, 100)
        self.timer_opacity_slider.setValue(int(cfg.get("timer_opacity", 38)))
        self.timer_opacity_label = QLabel(f"{self.timer_opacity_slider.value()}%")
        self.timer_opacity_label.setMinimumWidth(36)
        opacity_layout = QHBoxLayout()
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.addWidget(self.timer_opacity_slider)
        opacity_layout.addWidget(self.timer_opacity_label)
        self.timer_opacity_row = QWidget()
        self.timer_opacity_row.setLayout(opacity_layout)
        self.timer_size_slider = QSlider(_qt_enum("Orientation", "Horizontal"))
        self.timer_size_slider.setRange(60, 180)
        self.timer_size_slider.setSingleStep(5)
        self.timer_size_slider.setValue(int(cfg.get("timer_size", 100)))
        self.timer_size_label = QLabel(f"{self.timer_size_slider.value()}%")
        self.timer_size_label.setMinimumWidth(36)
        timer_size_layout = QHBoxLayout()
        timer_size_layout.setContentsMargins(0, 0, 0, 0)
        timer_size_layout.addWidget(self.timer_size_slider)
        timer_size_layout.addWidget(self.timer_size_label)
        self.timer_size_row = QWidget()
        self.timer_size_row.setLayout(timer_size_layout)
        self.recovery_display_combo = QComboBox()
        for key, label in RECOVERY_DISPLAYS.items():
            self.recovery_display_combo.addItem(label, key)
        self.recovery_display_combo.setCurrentIndex(max(0, self.recovery_display_combo.findData(cfg.get("recovery_display", "hearts"))))
        self.timer_style_note = QLabel()
        self.timer_style_note.setWordWrap(True)
        self.timer_style_note.setMinimumHeight(54)
        self.timer_style_note.setAlignment(
            _qt_enum("AlignmentFlag", "AlignTop")
            | _qt_enum("AlignmentFlag", "AlignLeft")
        )
        self.appearance_swatch = QLabel()
        self.appearance_swatch.setAlignment(_ALIGN_CENTER)
        self.appearance_swatch.setMinimumHeight(44)
        self.theme_combo.currentIndexChanged.connect(self._update_appearance_controls)
        self.timer_style_combo.currentIndexChanged.connect(self._update_appearance_controls)
        self.recovery_display_combo.currentIndexChanged.connect(self._update_appearance_controls)
        self.timer_opacity_slider.valueChanged.connect(self._update_appearance_controls)
        self.timer_size_slider.valueChanged.connect(self._update_appearance_controls)
        self._update_appearance_controls()
        self._build_preview()
        self.theme_combo.currentIndexChanged.connect(lambda _i: self._render_preview())
        self.recovery_display_combo.currentIndexChanged.connect(lambda _i: self._render_preview())
        self.recovery_spin.valueChanged.connect(lambda _i: self._render_preview())
        self.bubble_size_spin.valueChanged.connect(lambda _i: self._render_preview())

        identity = QFormLayout()
        identity.addRow("Character:", self.character_picker)
        identity.addRow("Buddy's name:", self.name_edit)
        general = QVBoxLayout()
        rules_box = QGroupBox("HOW TO BE WITH YOUR BUDDY")
        rules_layout = QVBoxLayout(rules_box)
        rules_text = QLabel(
            "<ol style='margin: 0; padding-left: 22px;'>"
            "<li>Choose your Focus Friend.</li>"
            "<li>You can move the timer and character anywhere.</li>"
            "<li>Don't let the time run out.</li>"
            "<li>If it does, review 5 cards within the time limit to help your buddy feel happy again!</li>"
            "<li>Learn and have fun.</li></ol>"
            "<p>Explore the menu to see all the different ways to change the look and mechanics of the add-on.</p>"
        )
        rules_text.setWordWrap(True)
        rules_layout.addWidget(rules_text)
        general.addWidget(rules_box)
        general.addWidget(section("Your Focus Friend", identity,
            "Choose your character and what to call them. All buddies use the Kawaii message style."))
        self.preview_box.setTitle("Try the animations")
        general.addWidget(self.preview_box)
        general.addStretch()

        goals = QFormLayout()
        self._mood_row_labels = [QLabel(""), QLabel(""), QLabel("")]
        goals.addRow(self._mood_row_labels[0], neutral_row)
        goals.addRow(self._mood_row_labels[1], happy_row)
        goals.addRow(self._mood_row_labels[2], excited_row)
        home_display = QFormLayout()
        home_size_label = QLabel("Home Screen Buddy Size")
        home_size_label.setStyleSheet("font-weight:700; font-size:13px;")
        home_display.addRow(home_size_label, size_row)
        home_display.addRow(self.mood_bar_check)
        home_display.addRow(self.dialogue_check)
        home_display.addRow(self.run_check)
        home_display.addRow(self.side_check)
        home = QVBoxLayout()
        home.addWidget(section("Daily Mood Goals", goals,
            "Their home-screen mood brightens as your review count grows today. Set the review counts for each new mood; Anki's new study day resets this progress."))
        home.addWidget(section("Home-screen display", home_display,
            "These options affect the deck list. Side docking places them beside the decks when the window is wide enough."))
        home.addStretch()

        focus_form = QFormLayout()
        focus_form.addRow(self.focus_check)
        focus_form.addRow("Seconds to recall:", self.focus_row)
        focus_form.addRow("Timer starts at:", self.timer_pos_combo)
        recovery_form = QFormLayout()
        recovery_form.addRow("Reviews to recover:", recovery_row)
        recovery_form.addRow("If another card times out:", self.recovery_behavior_combo)
        recovery_form.addRow(self.recovery_counter_check)
        buddy_form = QFormLayout()
        buddy_form.addRow(self.mini_check)
        review_size_label = QLabel("Buddy size during reviews")
        review_size_label.setStyleSheet("font-weight:700;")
        buddy_form.addRow(review_size_label, mini_size_row)
        buddy_form.addRow(self.mini_size_note)
        buddy_form.addRow("Starting position:", self.pos_combo)
        reviews = QVBoxLayout()
        reviews.addWidget(section("Thinking Countdown Timer", focus_form,
            "The countdown starts with each question. Revealing the answer pauses it in place and dims it to 50%; the next question starts a fresh countdown. Same as last time remembers a separate timer position for each deck across cards and Anki restarts. Other positions use the selected preset. Double-click resets the current deck's saved spot. Running out of time starts cosmetic recovery; your card schedule is unchanged."))
        reviews.addWidget(section("Buddy During Review", buddy_form,
            "Choose their size and starting spot on cards. Same as last time remembers a separate character position for each deck. Timer style, heart style, and colors are in Appearance."))
        reviews.addWidget(section("Hearts and recovery", recovery_form,
            "Complete this many later reviews to refill their hearts. The card that timed out does not count. Reset starts the full recovery again after another timeout; Hold keeps the reviews still remaining."))
        reviews.addStretch()

        message_events = QFormLayout()
        message_events.addRow(self.chatter_check)
        message_events.addRow(self.rating_messages_check)
        message_events.addRow("Optional message frequency:", self.freq_row)
        message_text = QFormLayout()
        bubble_size_label = QLabel("Bubble text size")
        bubble_size_label.setStyleSheet("font-weight:700; font-size:13px;")
        message_text.addRow(bubble_size_label, self.bubble_size_row)
        messages = QVBoxLayout()
        messages.addWidget(section("When they talk", message_events,
            "Choose whether you want occasional reactions after Again, Hard, Good, or Easy. Good and Easy share the same praise lines. Optional messages use the frequency above and skip the next card after appearing. The session greeting, timeout, and recovery messages still appear when triggered."))
        messages.addWidget(section("Make messages easy to read", message_text,
            "New setups start at 12 px. Increase this for larger lettering; the bubble grows to fit. Appearance has a live preview of the pending text size and colors."))
        custom_heading = QLabel("Custom messages")
        custom_heading.setStyleSheet("font-weight:700; font-size:16px; margin-top:10px;")
        messages.addWidget(custom_heading)
        custom_intro = QLabel(
            "Add your own lines by event. They can join the built-in messages or be turned off."
        )
        custom_intro.setWordWrap(True)
        messages.addWidget(custom_intro)
        messages.addLayout(custom_messages)
        messages.addStretch()

        theme_form = QFormLayout()
        theme_form.addRow("Color theme:", self.theme_combo)
        theme_form.addRow(self.appearance_swatch)
        timer_look = QFormLayout()
        timer_look.addRow("Timer style:", self.timer_style_combo)
        timer_look.addRow(self.timer_style_note)
        timer_look.addRow("Timer size:", self.timer_size_row)
        timer_look.addRow("Glass opacity:", self.timer_opacity_row)
        recovery_look = QFormLayout()
        recovery_look.addRow("Show recovery as:", self.recovery_display_combo)
        recovery_look.addRow("Text-only style:", self.counter_style_combo)
        appearance_controls = QVBoxLayout()
        appearance_controls.addWidget(section("Matching colors", theme_form,
            "A theme coordinates the timer, speech bubbles, hearts, and home-screen progress bar."))
        appearance_controls.addWidget(section("Timer appearance", timer_look,
            "Size scales the whole timer. Glass opacity changes only the translucent background; lower values are more see-through."))
        appearance_controls.addWidget(section("Recovery appearance", recovery_look,
            "Hearts refill as you complete reviews. Hover over them to see how many reviews are left. Text counter style applies when you choose Text counter.",
            note_min_height=88))
        appearance_controls.addStretch()
        self._build_appearance_preview()
        appearance_columns = QHBoxLayout()
        appearance_columns.setSpacing(16)
        appearance_columns.addLayout(appearance_controls, 1)
        appearance_columns.addWidget(self.appearance_preview_group, 1)
        appearance = QVBoxLayout()
        appearance.addLayout(appearance_columns)

        self.hardcore_check.setText("Enable HARDCORE MODE")
        hardcore_form = QFormLayout()
        hardcore_form.addRow(self.hardcore_check)
        hardcore_form.addRow("Again answers in a row:", self.hardcore_misses_row)
        hardcore_form.addRow("Reviews to recover:", self.hardcore_recovery_row)
        hardcore = QVBoxLayout()
        hardcore.addWidget(section("An optional extra challenge", hardcore_form,
            "Several Again ratings in a row can start a recovery period. Any Hard, Good, or Easy rating breaks that miss streak. Finish the recovery reviews to refill their hearts. This changes their reactions only, not Anki's scheduling."))
        other_penalties = QLabel("Hardcore and timer recovery are separate. Turning one off clears its own recovery period; the other can still be active.")
        other_penalties.setWordWrap(True)
        hardcore.addWidget(other_penalties)
        hardcore.addStretch()

        about = QVBoxLayout()
        about_box = QGroupBox("About Focus Friends")
        about_box_layout = QVBoxLayout(about_box)
        about_blurb = QLabel(
            "Focus Friends is a small animated companion for Anki that helps make each "
            "review feel a little more focused and fun. The countdown is about giving "
            "each card your attention, not about punishing you for forgetting an answer. "
            "If time runs out, keep studying to help your buddy recover. You can choose "
            "a character and customize the timer, messages, appearance, and optional "
            "hardcore challenge. Card scheduling stays with Anki."
        )
        about_blurb.setWordWrap(True)
        about_box_layout.addWidget(about_blurb)
        about.addWidget(about_box)

        animation_credits = [
            ("Demon Girl", "https://petdex.dev/pets/nezuko"),
            ("Butterfly Girl", "https://codex-pets.net/#/pets/shinobu"),
            ("Sakia", "https://petdex.dev/pets/chitose"),
            ("Momo", "https://codex-pets.net/#/pets/eru"),
            ("Kokona", "https://codexpet.top/pets/firefly--lingxiaotian"),
            ("Soyo", "https://codexpet.top/pets/miku-sea--legeling"),
            ("Suzuka", "https://codex-pets.net/#/pets/sengoku-yuno"),
            ("Miku", "https://codexpet.top/pets/kita-ikuyo--legeling"),
            ("Yume", "https://petdex.dev/pets/mizuno-akane"),
            ("Kano", "https://petdex.dev/pets/abg"),
            ("Megumi", "https://codex-pets.net/#/pets/yanami-anna-eating"),
            ("Yui", "https://petdex.dev/pets/yuuhi"),
        ]
        credits_group = QGroupBox("Animation credits")
        credits_layout = QVBoxLayout(credits_group)
        credits_note = QLabel("Character animation pages:")
        credits_layout.addWidget(credits_note)
        credits_html = "<br>".join(
            f'• <a href="{html.escape(url, quote=True)}">{html.escape(name)}</a>'
            for name, url in animation_credits
        )
        credits_label = QLabel(credits_html)
        credits_label.setTextFormat(_qt_enum("TextFormat", "RichText"))
        credits_label.setTextInteractionFlags(
            _qt_enum("TextInteractionFlag", "TextBrowserInteraction")
        )
        credits_label.setOpenExternalLinks(True)
        credits_label.setWordWrap(True)
        credits_layout.addWidget(credits_label)
        about.addWidget(credits_group)
        about.addStretch()

        self._refresh_mood_labels()

        self.tabs = QTabWidget()
        for title, form in (
            ("General", general),
            ("Home screen", home),
            ("Reviews", reviews),
            ("Message Bubbles", messages),
            ("Appearance", appearance),
            ("HARDCORE MODE", hardcore),
            ("About", about),
        ):
            page = QWidget()
            page.setLayout(form)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)
        self.tabs.currentChanged.connect(self._appearance_tab_changed)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self.setMinimumSize(700, 480)
        available = self.screen().availableGeometry()
        self.resize(min(900, available.width() - 60), min(900, available.height() - 60))

    def _note_mini_size_change(self, value):
        self.mini_size_note.setVisible(int(value) != self._saved_mini_size)

    def _update_message_controls(self, *_args):
        enabled = self.chatter_check.isChecked()
        self.rating_messages_check.setEnabled(enabled)
        self.freq_row.setEnabled(enabled and self.rating_messages_check.isChecked())

    @staticmethod
    def _parse_custom_message_text(text: str) -> list:
        """Keep a bounded list of plain-text lines for the message pools."""
        result = []
        seen = set()
        for line in str(text or "").splitlines():
            line = line.strip()[:240]
            if not line:
                continue
            key = line.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(line)
            if len(result) >= 30:
                break
        return result

    def _custom_category_changed(self, index: int) -> None:
        if not hasattr(self, "custom_message_edit"):
            return
        self._custom_message_drafts[self._current_custom_event] = self._parse_custom_message_text(
            self.custom_message_edit.toPlainText()
        )
        event = self.custom_event_combo.itemData(index)
        if not event:
            return
        self._current_custom_event = event
        self.custom_message_edit.blockSignals(True)
        self.custom_message_edit.setPlainText(
            "\n".join(self._custom_message_drafts.get(event, []))
        )
        self.custom_message_edit.blockSignals(False)
        self._custom_preview_index = 0
        self._preview_custom_message()

    def _custom_editor_changed(self) -> None:
        self._custom_message_drafts[self._current_custom_event] = self._parse_custom_message_text(
            self.custom_message_edit.toPlainText()
        )
        self._custom_preview_index = 0

    def _update_custom_message_controls(self, *_args) -> None:
        enabled = self.custom_messages_check.isChecked()
        self.custom_event_combo.setEnabled(enabled)
        self.custom_message_edit.setEnabled(enabled)
        self.custom_preview_button.setEnabled(enabled)
        self.custom_clear_button.setEnabled(enabled)

    def _preview_custom_message(self) -> None:
        event = self._current_custom_event
        custom = self._parse_custom_message_text(self.custom_message_edit.toPlainText())
        if custom:
            choices = custom
            source = "Your message"
        elif event == "dialogue":
            choices = TALK_STYLES["kawaii"]["dialogue"]["neutral"]
            source = "Built-in example"
        else:
            choices = TALK_STYLES["kawaii"].get(event, [])
            source = "Built-in example"
        if not choices:
            self.custom_preview_text.setText("Add a line to preview this category.")
            return
        index = self._custom_preview_index % len(choices)
        self._custom_preview_index += 1
        self.custom_preview_text.setText(f"{source}:  {_clean_message(choices[index])}")

    def _restore_builtin_messages(self) -> None:
        self._custom_message_drafts = {
            key: [] for _label, key in self.custom_message_categories
        }
        self.custom_message_edit.clear()
        self._custom_preview_index = 0
        self.custom_preview_text.setText(
            "Custom lines cleared. The built-in messages will be used."
        )

    def _update_appearance_controls(self, *_args):
        theme = COLOR_THEMES[self.theme_combo.currentData()]
        style = self.timer_style_combo.currentData()
        self.timer_opacity_row.setEnabled(style == "glass")
        self.timer_opacity_label.setText(f"{self.timer_opacity_slider.value()}%")
        self.timer_size_label.setText(f"{self.timer_size_slider.value()}%")
        self.counter_style_combo.setEnabled(self.recovery_display_combo.currentData() == "text")
        descriptions = {
            "glass": "A translucent panel with a soft blur. The slider changes the background; numbers stay clear.",
            "pulse": "A compact pill with a health bar and a small countdown at the right.",
            "ring": "A small circular countdown around the number.",
            "kawaii": "A rounded pastel pill using your theme colors.",
            "tab": "A very slim bar with the countdown in a small floating tab.",
        }
        self.timer_style_note.setText(descriptions[style])
        self.timer_style_note.updateGeometry()
        self.appearance_swatch.setText(f"{theme['label']}  ·  ♥︎ ♥︎ ♥︎ ♡ ♡")
        self.appearance_swatch.setStyleSheet(
            f"background:{theme['bubble']};color:{theme['ink']};border:1px solid {theme['accent']};"
            "border-radius:14px;padding:12px;font-size:16px;"
        )
        self._queue_appearance_preview()
        if hasattr(self, "preview_image"):
            self._render_preview()

    def _build_appearance_preview(self):
        self._appearance_finished = False
        self._appearance_seconds = self.focus_spin.value()
        self._appearance_replay_requested = True
        self._appearance_update_timer = QTimer(self)
        self._appearance_update_timer.setSingleShot(True)
        self._appearance_update_timer.timeout.connect(self._flush_appearance_preview)
        self._appearance_timer = QTimer(self)
        self._appearance_timer.timeout.connect(self._appearance_preview_tick)

        self.appearance_preview_group = QGroupBox("Live preview")
        preview_layout = QVBoxLayout(self.appearance_preview_group)
        self._appearance_view = AppearancePreview(self)
        preview_layout.addWidget(self._appearance_view, 1)
        buttons = QHBoxLayout()
        self.preview_dark_check = QCheckBox("Dark background")
        self.preview_dark_check.setChecked(self.palette().window().color().lightness() < 128)
        self.preview_dark_check.toggled.connect(self._queue_appearance_preview)
        replay_button = QPushButton("Replay")
        replay_button.setToolTip("Replay the sample countdown and bubble entrance")
        replay_button.clicked.connect(self._replay_appearance_preview)
        expired_button = QPushButton("Time’s up")
        expired_button.clicked.connect(self._expire_appearance_preview)
        buttons.addWidget(self.preview_dark_check)
        buttons.addStretch()
        buttons.addWidget(replay_button)
        buttons.addWidget(expired_button)
        preview_layout.addLayout(buttons)
        recovery_row = QHBoxLayout()
        recovery_row.addWidget(QLabel("Reviews left:"))
        self.preview_recovery_slider = QSlider(_qt_enum("Orientation", "Horizontal"))
        self.preview_recovery_slider.setRange(0, self.recovery_spin.value())
        self.preview_recovery_slider.setValue(min(3, self.recovery_spin.value()))
        self.preview_recovery_label = QLabel(str(self.preview_recovery_slider.value()))
        self.preview_recovery_label.setMinimumWidth(24)
        self.preview_recovery_slider.valueChanged.connect(self._preview_recovery_changed)
        recovery_row.addWidget(self.preview_recovery_slider, 1)
        recovery_row.addWidget(self.preview_recovery_label)
        preview_layout.addLayout(recovery_row)
        note = QLabel("Sample progress only. Your appearance changes are saved with OK.")
        note.setWordWrap(True)
        preview_layout.addWidget(note)
        for signal in (
            self.character_combo.currentIndexChanged,
            self.counter_style_combo.currentIndexChanged, self.bubble_size_spin.valueChanged,
            self.recovery_counter_check.toggled, self.focus_spin.valueChanged,
        ):
            signal.connect(self._queue_appearance_preview)
        self.recovery_spin.valueChanged.connect(self._preview_recovery_length_changed)

    def _pending_appearance_config(self):
        cfg = get_config()
        cfg.update(
            character=self._character_keys[self.character_combo.currentIndex()],
            talking_style="kawaii",
            color_theme=self.theme_combo.currentData(), timer_style=self.timer_style_combo.currentData(),
            timer_opacity=self.timer_opacity_slider.value(), timer_size=self.timer_size_slider.value(),
            recovery_display=self.recovery_display_combo.currentData(),
            counter_style=self._counter_style_keys[self.counter_style_combo.currentIndex()],
            show_recovery_counter=self.recovery_counter_check.isChecked(),
            bubble_font_size=self.bubble_size_spin.value(), focus_seconds=self.focus_spin.value(),
            recovery_reviews=self.recovery_spin.value(),
        )
        return cfg

    def _appearance_tab_changed(self, index):
        general = self.tabs.tabText(index) == "General"
        if general and self._preview_frames:
            self._preview_timer.start(int(FRAME_SECONDS * 1000))
        else:
            self._preview_timer.stop()
        active = self.tabs.tabText(index) == "Appearance"
        self._appearance_view.set_active(active)
        if not active:
            self._appearance_timer.stop()
            self._appearance_update_timer.stop()
            return
        self._queue_appearance_preview()
        if self._appearance_seconds > 0:
            self._appearance_timer.start(1000)

    def _queue_appearance_preview(self, *_args, replay=False):
        timer = getattr(self, "_appearance_update_timer", None)
        if timer is None or self._appearance_finished or sip.isdeleted(self):
            return
        self._appearance_replay_requested = self._appearance_replay_requested or replay
        timer.start(60)

    def _flush_appearance_preview(self):
        if self._appearance_finished or self.tabs.tabText(self.tabs.currentIndex()) != "Appearance":
            return
        self._appearance_view.set_sample(
            self._pending_appearance_config(), self._appearance_seconds,
            self.preview_recovery_slider.value(), self.preview_dark_check.isChecked(),
            replay=self._appearance_replay_requested,
        )
        self._appearance_replay_requested = False

    def _appearance_preview_tick(self):
        self._appearance_seconds = max(0, self._appearance_seconds - 1)
        if self._appearance_seconds == 0:
            self._appearance_timer.stop()
        self._queue_appearance_preview()

    def _replay_appearance_preview(self):
        self._appearance_seconds = self.focus_spin.value()
        self._appearance_timer.start(1000)
        self._queue_appearance_preview(replay=True)

    def _expire_appearance_preview(self):
        self._appearance_timer.stop()
        self._appearance_seconds = 0
        self._queue_appearance_preview(replay=True)

    def _preview_recovery_changed(self, remaining):
        self.preview_recovery_label.setText(str(remaining))
        self._queue_appearance_preview()

    def _preview_recovery_length_changed(self, total):
        self.preview_recovery_slider.setMaximum(total)
        self._queue_appearance_preview()

    def done(self, result):
        self._appearance_finished = True
        self._appearance_timer.stop()
        self._appearance_update_timer.stop()
        self._appearance_view.set_active(False)
        self._preview_timer.stop()
        super().done(result)

    def _open_gallery(self):
        key = self._character_keys[self.character_combo.currentIndex()]
        gallery = CharacterGallery(key, self)
        if gallery.exec() == QDialog.DialogCode.Accepted:
            self.character_combo.setCurrentIndex(self._character_keys.index(gallery.selected_key))

    # --- Character preview playground -------------------------------------
    # Lets you try every character / talking style / mood combination without
    # starting a review. It previews the *pending* combo selections, not the
    # saved config, so you can explore and then cancel.
    def _build_preview(self) -> None:
        self._preview_mode = "idle"
        self.preview_buttons = {}

        self.preview_image = QLabel()
        self.preview_image.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.preview_image.setAlignment(_ALIGN_CENTER)

        self.preview_text = QLabel()
        self.preview_text.setAlignment(_ALIGN_CENTER)
        self.preview_text.setWordWrap(True)
        # No hardcoded colour: a QLabel inherits the dialog's foreground, so the
        # text stays readable in Anki's light and dark themes alike.
        self.preview_text.setStyleSheet("font-size:13px;")
        self.preview_text.setMinimumHeight(64)
        self.preview_hearts = QLabel()
        self.preview_hearts.setAlignment(_ALIGN_CENTER)

        # Play the real strip through, not just frame 0.
        self._preview_frames = []
        self._preview_index = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._advance_preview)

        buttons = QGridLayout()
        buttons.setSpacing(6)
        for index, (key, label) in enumerate(PREVIEW_MODES):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self._select_preview(k))
            self.preview_buttons[key] = btn
            buttons.addWidget(btn, index // 4, index % 4)

        inner = QVBoxLayout()
        inner.addLayout(buttons)
        explanation = QLabel("Try each animation. Sad, Timeout, and Recovering share the sad pose; the recovery examples also show the hearts and reviews remaining.")
        explanation.setWordWrap(True)
        inner.addWidget(explanation)
        inner.addWidget(self.preview_image, 0, _ALIGN_CENTER)
        inner.addWidget(self.preview_hearts)
        inner.addWidget(self.preview_text)

        self.preview_box = QGroupBox("Preview")
        self.preview_box.setLayout(inner)

        # Re-render whenever the things it depends on change.
        self.character_combo.currentIndexChanged.connect(lambda _i: self._render_preview())
        self.name_edit.textChanged.connect(lambda _t: self._render_preview())
        self._select_preview("idle")

    def _select_preview(self, mode: str) -> None:
        self._preview_mode = mode
        for key, btn in self.preview_buttons.items():
            btn.setChecked(key == mode)
        self._render_preview()

    def _preview_target(self):
        character = self._character_keys[self.character_combo.currentIndex()]
        pet_name = self.name_edit.text().strip() or PET_PROFILES[character]["default_name"]
        return character, TALK_STYLES["kawaii"], pet_name

    @staticmethod
    def _say(text: str, pet_name: str) -> str:
        return _clean_message(text.replace("Lumi", pet_name).replace("{name}", pet_name))

    def _render_preview(self) -> None:
        try:
            character, style, pet_name = self._preview_target()
        except (IndexError, KeyError):
            return
        mode = getattr(self, "_preview_mode", "idle")

        theme = COLOR_THEMES[self.theme_combo.currentData()]
        self.preview_text.setStyleSheet(
            f"font-size:{self.bubble_size_spin.value()}px;background:{theme['bubble']};color:{theme['ink']};"
            f"border:1px solid {theme['accent']};border-radius:10px;padding:4px;"
        )
        self.preview_hearts.setStyleSheet(f"font-size:18px;color:{theme['accent']};")
        self.preview_hearts.setVisible(self.recovery_display_combo.currentData() != "text")
        self.preview_hearts.setText("♡ ♡ ♡ ♡ ♡" if mode == "timeout" else "♥︎ ♥︎ ♡ ♡ ♡" if mode == "recovering" else "♥︎ ♥︎ ♥︎ ♥︎ ♥︎")
        if mode in ("timeout", "recovering"):
            left = self.recovery_spin.value()
            if mode == "recovering":
                left = max(1, int(round(left * 0.6)))
            sprite = "failed"
            lines = [f"Okay again in {left} review{'s' if left != 1 else ''}"]
        elif mode == "sad":
            sprite = "failed"
            lines = [self._say(random.choice(_message_lines("dialogue", style["dialogue"]["sad"])), pet_name)]
        else:
            sprite = mode
            descriptions = {
                "idle": "Idle: their usual calm pose between reactions.",
                "waiting": "Waiting: a little pause or resting pose.",
                "review": "Thinking: their alternate review pose.",
                "jumping": "Jumping: one of their happy celebrations!",
                "waving": "Waving: their hello and celebration animation.",
                "running_left": "Running left: their movement animation.",
                "running_right": "Running right: their movement animation.",
                "look_a": "Looking around: the first set of directions.",
                "look_b": "Looking around: the second set of directions.",
            }
            lines = [descriptions.get(mode, mode)]

        spec = _pet_profile(character)["sprites"].get(sprite)
        if not spec:
            self.preview_image.clear()
            self.preview_text.setText(f"(no sprite named '{sprite}' for {character})")
            return
        path = _sprite_path(spec[0])
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview_image.clear()
            self.preview_text.setText(f"(could not load {os.path.basename(path)})")
            return
        self._preview_frames = self._slice_frames(pixmap, spec[1], character)
        self._preview_index = 0
        if self._preview_frames:
            self.preview_image.setPixmap(self._preview_frames[0])
            if not hasattr(self, "tabs") or self.tabs.tabText(self.tabs.currentIndex()) == "General":
                self._preview_timer.start(int(round(_sprite_frame_seconds(sprite) * 1000)))
        self.preview_text.setText("\n".join(x for x in lines if x))

    @staticmethod
    def _slice_frames(pixmap, frame_count: int, character: str = None) -> list:
        """Cut a horizontal sprite strip into individually scaled frames."""
        frame_w, frame_h = _pet_frame_size(character)
        frames = []
        for i in range(max(1, int(frame_count))):
            frame = pixmap.copy(i * frame_w, 0, frame_w, frame_h)
            if frame.isNull():
                break
            frames.append(frame.scaled(PREVIEW_W, PREVIEW_H, _KEEP_ASPECT, _SMOOTH_TRANSFORM))
        return frames

    def _advance_preview(self) -> None:
        if not self._preview_frames:
            return
        self._preview_index = (self._preview_index + 1) % len(self._preview_frames)
        self.preview_image.setPixmap(self._preview_frames[self._preview_index])

    def accept(self):
        cfg = get_config()
        cfg["character"] = self._character_keys[self.character_combo.currentIndex()]
        cfg["talking_style"] = "kawaii"
        cfg["pet_name"] = self.name_edit.text().strip() or DEFAULT_CONFIG["pet_name"]
        cfg["mood_neutral_at"] = self.neutral_spin.value()
        cfg["mood_happy_at"] = self.happy_spin.value()
        cfg["mood_excited_at"] = self.excited_spin.value()
        cfg["sprite_size"] = self.size_spin.value()
        cfg["mini_size"] = self.mini_size_spin.value()
        cfg["show_during_review"] = self.mini_check.isChecked()
        cfg["show_chatter"] = self.chatter_check.isChecked()
        cfg["show_rating_messages"] = self.rating_messages_check.isChecked()
        cfg["chatter_percent"] = BUBBLE_FREQUENCIES[self._freq_keys[self.freq_combo.currentIndex()]]["percent"]
        cfg["bubble_font_size"] = self.bubble_size_spin.value()
        self._custom_message_drafts[self._current_custom_event] = self._parse_custom_message_text(
            self.custom_message_edit.toPlainText()
        )
        cfg["custom_messages_enabled"] = self.custom_messages_check.isChecked()
        cfg["custom_messages"] = {
            key: lines[:30]
            for key, lines in self._custom_message_drafts.items()
            if lines
        }
        cfg["mini_position"] = self._pos_keys[self.pos_combo.currentIndex()]
        cfg["show_mood_bar"] = self.mood_bar_check.isChecked()
        cfg["show_dialogue"] = self.dialogue_check.isChecked()
        cfg["run_across"] = self.run_check.isChecked()
        cfg["side_panel"] = self.side_check.isChecked()
        # Switching the timer off forgives any penalty still running: they are not
        # being timed any more, so leaving them sad would have nothing to do with it.
        was_on = bool(get_config().get("show_focus_timer", True))
        cfg["show_focus_timer"] = self.focus_check.isChecked()
        if was_on and not cfg["show_focus_timer"]:
            _forgive_recovery_penalty(timeout=True, hardcore=False)

        hardcore_was_on = bool(get_config().get("hardcore_mode", False))
        cfg["hardcore_mode"] = self.hardcore_check.isChecked()
        if hardcore_was_on and not cfg["hardcore_mode"]:
            _forgive_recovery_penalty(timeout=False, hardcore=True)
        cfg["focus_seconds"] = self.focus_spin.value()
        cfg["recovery_reviews"] = self.recovery_spin.value()
        cfg["recovery_timeout_behavior"] = self.recovery_behavior_combo.currentData()
        cfg["show_recovery_counter"] = self.recovery_counter_check.isChecked()
        cfg["counter_style"] = self._counter_style_keys[self.counter_style_combo.currentIndex()]
        cfg["hardcore_mode"] = self.hardcore_check.isChecked()
        cfg["hardcore_misses"] = self.hardcore_misses_spin.value()
        cfg["hardcore_recovery"] = self.hardcore_recovery_spin.value()
        timer_position = self._timer_pos_keys[self.timer_pos_combo.currentIndex()]
        if timer_position != "last":
            # Fixed presets ignore the old single-position fallback. Per-deck
            # positions remain intact if the user later switches back to Last.
            cfg["timer_pos_xy"] = None
        cfg["timer_position"] = timer_position
        cfg["timer_style"] = self.timer_style_combo.currentData()
        cfg["timer_opacity"] = self.timer_opacity_slider.value()
        cfg["timer_size"] = self.timer_size_slider.value()
        cfg["color_theme"] = self.theme_combo.currentData()
        cfg["recovery_display"] = self.recovery_display_combo.currentData()
        save_config(cfg)
        super().accept()
        if mw.state == "deckBrowser":
            mw.deckBrowser.refresh()

    def _character_changed(self, index):
        key = self._character_keys[index]
        self.character_label.setText(PET_PROFILES[key]["label"])
        self.name_edit.setText(PET_PROFILES[key]["default_name"])
        self._refresh_mood_labels()

    def _refresh_mood_labels(self):
        """Keep the "Cards for X -> Y" rows in step with the selected voice."""
        names = MOOD_TIER_NAMES["kawaii"]["tiers"]
        texts = [
            f"Cards for {names['sad'][0]} \u2192 {names['neutral'][0]}:",
            f"Cards for {names['neutral'][0]} \u2192 {names['happy'][0]}:",
            f"Cards for {names['happy'][0]} \u2192 {names['excited'][0]}:",
        ]
        for label, text in zip(self._mood_row_labels, texts):
            label.setText(text)


def open_settings() -> None:
    timer_was_active = bool(_focus_timer and _focus_timer.isActive())
    timer_was_enabled = get_config().get("show_focus_timer", True)
    seconds_left = _focus_seconds_left
    reviewer = getattr(mw, "reviewer", None)
    card_id = getattr(getattr(reviewer, "card", None), "id", None)
    _stop_focus_timer()
    dialog = None
    try:
        dialog = SettingsDialog(mw)
        dialog.exec()
    finally:
        if dialog is not None:
            dialog.deleteLater()
        # Resume after the modal dialog has returned keyboard focus to Anki.
        QTimer.singleShot(50, lambda: _resume_review_after_settings(
            timer_was_active, timer_was_enabled, seconds_left, card_id
        ))


def _resume_review_after_settings(was_active, was_enabled, seconds_left, card_id):
    global _mini_reaction_until, _greeting_shown, _focus_seconds_left
    reviewer = getattr(mw, "reviewer", None)
    if sip.isdeleted(mw) or mw.state != "review" or reviewer is None:
        return
    _mini_reaction_until = 0.0
    _greeting_shown = False
    _eval_in_reviewer("window.lumiBuddyToken=(window.lumiBuddyToken||0)+1;")
    _eval_in_reviewer(_bubble_js(None, immediate=True))
    if _mini_pet_active():
        show_idle_pet()
    else:
        _eval_in_reviewer("var buddy=document.getElementById('lumibuddy-mini');if(buddy)buddy.remove();")
    if getattr(reviewer, "state", None) == "question" and get_config().get("show_focus_timer", True):
        same_card = card_id == getattr(getattr(reviewer, "card", None), "id", None)
        if _focus_waiting_to_begin:
            _focus_seconds_left = _focus_seconds()
            _eval_in_reviewer(_focus_timer_js(_focus_seconds_left, waiting=True))
        elif was_active and same_card and seconds_left > 0:
            _focus_seconds_left = min(seconds_left, _focus_seconds())
            _eval_in_reviewer(_focus_timer_js(_focus_seconds_left))
            _focus_timer.start(1000)
        elif not was_enabled or (was_active and not same_card):
            _start_focus_timer()
        elif load_state().get("timed_out_current"):
            _eval_in_reviewer(_focus_timer_js(0, expired=True))
    web = getattr(reviewer, "web", None)
    if web is not None and hasattr(web, "setFocus") and (not isinstance(web, QWidget) or not sip.isdeleted(web)):
        web.setFocus()


# ---------------------------------------------------------------------------
# Wire everything up
# ---------------------------------------------------------------------------
def _handle_position_message(message):
    """Our own bridge messages. Returns (handled, result)."""
    global _focus_waiting_to_begin
    if message == _TIMER_START_MSG:
        if (_focus_waiting_to_begin and mw.state == "review" and
                getattr(getattr(mw, "reviewer", None), "state", None) == "question"):
            _focus_waiting_to_begin = False
            _start_focus_timer()
        return True, None
    if isinstance(message, str) and message.startswith(_TIMER_POS_MSG_PREFIX):
        payload = message[len(_TIMER_POS_MSG_PREFIX):]
        cfg = get_config()
        if payload == "clear":
            if cfg.get("timer_position", "last") == "last":
                _save_position_for_deck(cfg, "timer_pos_by_deck", "timer_pos_xy", None)
        elif payload.startswith("set:"):
            try:
                left, top = (max(0, int(float(value))) for value in payload[4:].split(","))
            except (ValueError, OverflowError):
                return False, None
            if cfg.get("timer_position", "last") == "last":
                _save_position_for_deck(cfg, "timer_pos_by_deck", "timer_pos_xy", (left, top))
        else:
            return False, None
        save_config(cfg)
        return True, None
    if not isinstance(message, str) or not message.startswith(_POS_MSG_PREFIX):
        return False, None
    payload = message[len(_POS_MSG_PREFIX):]
    if payload == "clear":
        if get_config().get("mini_position", DEFAULT_CONFIG["mini_position"]) == "last":
            _save_mini_xy(None)
        return True, None
    if payload.startswith("set:"):
        try:
            left, top = (int(float(v)) for v in payload[4:].split(","))
        except ValueError:
            return False, None
        if get_config().get("mini_position", DEFAULT_CONFIG["mini_position"]) == "last":
            _save_mini_xy((left, top))
        return True, None
    return False, None


def on_webview_message(handled, message, *args):
    """Receive drag reports from the reviewer page over Anki's pycmd bridge.

    This hook changed shape twice:
      * Anki <= 23.x passed a bare bool and wanted a bare bool back.
      * Anki 25.09+ passes `(handled, result)` and unpacks a tuple back, and also
        passes a third `context` argument.
    The type of the first argument tells us which contract the caller is using,
    so both are supported without pinning a version.

    Everything is wrapped because this runs for *every* message any webview
    sends - remembering a drag is not worth breaking the bridge over.
    """
    tuple_style = isinstance(handled, tuple)
    # If an earlier handler in the chain already claimed the message, pass it on
    # untouched - and do no work, or we would clobber their state.
    if bool(handled[0] if tuple_style else handled):
        return handled
    try:
        mine, result = _handle_position_message(message)
    except Exception:
        mine, result = False, None
    return (mine, result) if tuple_style else mine


def setup() -> None:
    gui_hooks.deck_browser_will_render_content.append(on_deck_browser_render)
    gui_hooks.reviewer_did_answer_card.append(on_answer)
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    show_answer_hook = getattr(gui_hooks, "reviewer_did_show_answer", None)
    if show_answer_hook is not None:
        show_answer_hook.append(on_show_answer)
    reviewer_end_hook = getattr(gui_hooks, "reviewer_will_end", None)
    if reviewer_end_hook is not None:
        reviewer_end_hook.append(on_reviewer_will_end)
    gui_hooks.sync_did_finish.append(_reconcile_today_after_sync)
    undo_hook = getattr(gui_hooks, "state_did_undo", None)
    if undo_hook is None:
        undo_hook = getattr(gui_hooks, "reviewer_did_undo_answer", None)
    if undo_hook is not None:
        undo_hook.append(_sync_review_undo)
    operation_hook = getattr(gui_hooks, "operation_did_execute", None)
    if operation_hook is not None:
        operation_hook.append(_sync_review_undo)
    close_hook = getattr(gui_hooks, "profile_will_close", None)
    if close_hook is not None:
        close_hook.append(_clear_review_journal)
    msg_hook = getattr(gui_hooks, "webview_did_receive_js_message", None)
    if msg_hook is not None:
        msg_hook.append(on_webview_message)

    global _focus_timer
    _focus_timer = QTimer(mw)
    _focus_timer.setSingleShot(False)
    _focus_timer.timeout.connect(_focus_timer_tick)

    action = QAction(f"{ADDON_NAME} Settings…", mw)
    action.triggered.connect(open_settings)
    mw.form.menuTools.addAction(action)


setup()
