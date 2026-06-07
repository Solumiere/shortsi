"""
Persona prompts for the Alternate-History faceless shorts channel.
Edit these to rebrand. run_shorts.py rotates through the POSES lists so the same
narrator / protagonist face recurs across every video (consistency = brand).
"""

# Recurring on-screen guide - the channel's visual signature.
NARRATOR = (
    "a weathered ancient war-narrator, gaunt skull-like face half in shadow, "
    "deep-set glowing eyes, battered bronze and dark leather armor, hooded cloak, "
    "photorealistic, cinematic chiaroscuro lighting, shallow depth of field, "
    "muted desaturated tones, heavy film grain"
)

NARRATOR_POSES = [
    f"{NARRATOR}. Facing camera, leaning in close as if sharing a secret, low torchlight from below, embers in the dark air. 9:16 vertical, ultra realistic, 4K.",
    f"{NARRATOR}. Slowly turning his head toward the camera, faint knowing smirk, sparks drifting past. 9:16 vertical, ultra realistic, 4K.",
    f"{NARRATOR}. Arms crossed, looking directly at camera, cold blue rim light behind him. 9:16 vertical, ultra realistic, 4K.",
    f"{NARRATOR}. Raising a bony finger toward the camera, intense stare, smoke curling around him. 9:16 vertical, ultra realistic, 4K.",
]

# POV protagonist - a modern soldier displaced into the ancient past.
PROTAGONIST = (
    "a modern special-forces soldier in 2026 multicam fatigues and plate carrier, "
    "short stubble, exhausted determined eyes, dust and dried mud on his face, "
    "photorealistic, cinematic lighting, shallow depth of field, muted tones, film grain"
)

PROTAGONIST_POSES = [
    f"{PROTAGONIST}. Crouched low in cold mud at dawn, gripping his rifle, scanning a misty treeline. 9:16 vertical, ultra realistic, 4K.",
    f"{PROTAGONIST}. Standing among ancient stone ruins, looking up in disbelief at a towering Roman aqueduct. 9:16 vertical, ultra realistic, 4K.",
    f"{PROTAGONIST}. Back pressed against a crumbling wall, breathing hard, distant torches approaching. 9:16 vertical, ultra realistic, 4K.",
    f"{PROTAGONIST}. Face lit by firelight at night, jaw clenched, helmet off, thousand-yard stare. 9:16 vertical, ultra realistic, 4K.",
]
