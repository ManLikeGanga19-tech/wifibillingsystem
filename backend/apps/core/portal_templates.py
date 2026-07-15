"""The catalogue of captive-portal looks an ISP can choose from.

The backend is deliberately thin here: it stores and validates a template *id*, nothing
more. The visual presets — background treatment, card style, palette, layout — live in the
frontends (portal/src/templates.ts renders them; the console renders the same tokens as a
preview). Keeping the id list here, as the single source of truth the API validates
against, means the store can never hold a template the portal cannot render.

To add a look: add its id + label below AND its token preset in the two frontend registries.
The three stay in lockstep; a test asserts the id set matches the portal's.
"""

# (id, human label). Order is the order the console shows the cards in.
PORTAL_TEMPLATES = (
    ("aurora", "Aurora"),
    ("badge", "Badge"),
    ("classic", "Classic"),
    ("clay", "Clay"),
    ("grid", "Grid"),
    ("halo", "Halo"),
    ("lagoon", "Lagoon"),
    ("linen", "Linen"),
    ("lumen", "Lumen"),
    ("lumen-dark", "Lumen Dark"),
    ("marigold", "Marigold"),
    ("monochrome", "Monochrome"),
    ("neon", "Neon"),
    ("nimbus", "Nimbus"),
    ("pebble", "Pebble"),
    ("simple", "Simple"),
    ("slip", "Slip"),
    ("sunrise", "Sunrise"),
    ("vault", "Vault"),
)

TEMPLATE_IDS = frozenset(tid for tid, _ in PORTAL_TEMPLATES)

#: The default look — light, neutral, works with any brand colour.
DEFAULT_TEMPLATE = "lumen"


def is_valid_template(template_id: str) -> bool:
    return template_id in TEMPLATE_IDS
