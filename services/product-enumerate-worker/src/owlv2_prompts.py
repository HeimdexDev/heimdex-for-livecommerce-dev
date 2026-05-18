"""Prompts + schema for the 2-stage OWLv2 + gpt-4o-mini enumeration.

Replaces the single-pass ``EnumerationPrompt.SYSTEM`` (which asked
gpt-4o-mini to do both detection and labeling on a whole keyframe
batch). The new flow:

* **Stage 1 — OWLv2**: open-vocab detector localizes products from
  generic English text queries (``DEFAULT_OWLV2_QUERIES``). Better
  bboxes than gpt-4o-mini's free-form coordinates.
* **Stage 2 — gpt-4o-mini per crop**: each OWLv2 bbox is cropped and
  sent with ``LABEL_PROMPT_SYSTEM`` for a short Korean noun phrase +
  ``is_product`` flag. ``is_product=False`` crops (faces, props, on-
  screen graphics) are dropped, which filters OWLv2 false positives.

These prompts live in the worker for now because the calibration is
worker-side (detector threshold / NMS / queries co-evolve with the
label prompt). Once stable, promote to
``heimdex_media_contracts.product.prompts`` so the API can record an
honest ``enumeration_prompt_version`` per catalog row.
"""

from __future__ import annotations


# Internal version tag — bumped independently of contracts'
# ``EnumerationPrompt.VERSION`` until the new pipeline is promoted.
# Logged in the per-batch debug dict so we can attribute regressions
# in the goldens eval to a specific prompt revision.
OWLV2_PROMPT_VERSION = "v2.0-owlv2"


LABEL_PROMPT_SYSTEM = (
    "You are labeling a single cropped image from a Korean live-commerce "
    "video. The crop was localized by an object detector and may be "
    "imperfect — partially cut off, slightly off-center, or containing "
    "some background. Your job is to say what product, if any, is shown "
    "in this specific crop.\n"
    "\n"
    "WHAT COUNTS AS A PRODUCT (is_product=true)\n"
    "A sellable item presented as merchandise:\n"
    "  • HELD or DEMONSTRATED — held, opened, applied, or pointed to by "
    "the presenter.\n"
    "  • DISPLAYED — sitting on a showcase table, stand, shelf, rack, "
    "or hanger.\n"
    "  • PACKAGED — branded box, pouch, bottle, tube, jar, bag.\n"
    "  • PLATED FOOD — food in a bowl/plate/board when the food itself "
    "is clearly identifiable as the sale item (e.g., kimchi stew, "
    "grilled meat, dumplings). Generic vessels with unidentifiable "
    "contents do NOT qualify.\n"
    "  • WORN OR CARRIED — clothing, footwear, bags, watches, jewelry, "
    "eyewear, scarves, hats on a model/presenter, when any 'for sale' "
    "signal is visible in the crop (close-up framing on the item, "
    "hangtag, multiple variants nearby, presenter posing/demoing).\n"
    "\n"
    "Common categories include cosmetics, food, apparel, footwear, "
    "bags & accessories, jewelry, appliances, kitchenware, bedding, "
    "home goods, health devices, supplements, baby/pet goods, and "
    "more. The list is illustrative — apply the rules above regardless "
    "of category.\n"
    "\n"
    "WHAT IS NOT A PRODUCT (is_product=false)\n"
    "  • Human faces or body parts with no merchandise visible.\n"
    "  • Studio backdrops, walls, furniture, plants, wall art.\n"
    "  • Studio equipment — microphones, cameras, lights, monitors, "
    "cables, teleprompters.\n"
    "  • On-screen graphics — chyrons, price banners, sponsor logos "
    "burned into the video.\n"
    "  • Reflections in mirrors, monitor glass, or other surfaces.\n"
    "  • Presenter's personal items — everyday clothing, shoes, "
    "jewelry, watch, glasses, phone, hair clips, water bottle, coffee "
    "mug — UNLESS a 'for sale' signal (see WORN OR CARRIED above) is "
    "visible in the crop.\n"
    "  • Generic serving vessels with unidentifiable contents.\n"
    "  • Severely blurry, motion-blurred, or out-of-focus crops where "
    "the item's identity cannot be determined.\n"
    "\n"
    "CROP-SPECIFIC GUIDANCE\n"
    "  • Partial crops are fine — if you can still identify what the "
    "item is from the visible portion, label it.\n"
    "  • If the crop contains multiple products, label the one that is "
    "largest and most centered. If they are roughly equal, label the "
    "one in sharpest focus.\n"
    "  • If the crop is ambiguous between a product and a prop/person, "
    "prefer is_product=false. This stage is a precision gate; missed "
    "items are recovered elsewhere.\n"
    "\n"
    "OUTPUT — Return strict JSON:\n"
    "  is_product (bool): true if the crop clearly shows a sellable "
    "product per the rules above; false otherwise.\n"
    "  label (string): if is_product=true, a short Korean noun phrase "
    "describing the product visually, like '핑크 세럼 병', '베이지 니트 "
    "스웨터', '흰색 러닝화', '갈색 가죽 토트백', '냉동 만두 봉지', "
    "'스테인리스 프라이팬', '극세사 이불'. Avoid brand names unless the "
    "brand text is clearly readable in the crop. If is_product=false, "
    "return an empty string."
)

LABEL_JSON_SCHEMA = {
    "name": "crop_label",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "is_product": {"type": "boolean"},
            "label": {"type": "string"},
        },
        "required": ["is_product", "label"],
    },
}

# Default text queries for OWLv2, derived from the product categories
# enumerated in EnumerationPrompt.SYSTEM (cosmetics / food / apparel /
# appliances / supplements). Tweak via --queries / --queries-file when
# the segment's category is known.
DEFAULT_QUERIES: list[str] = [
    # cosmetics
    "a cosmetic bottle",
    "a serum bottle",
    "a tube of cream",
    "a jar of cream",
    "a lipstick",
    "a cushion compact",
    "a mask sheet pack", 
    # food
    "a food package",
    "a snack bag",
    "a frozen food pouch",
    "a bowl of food",
    "a plate of food",
    "a bottle of beverage",
    # apparel
    "a sweater",
    "a jacket",
    "a shirt",
    "a dress",
    "a pair of pants",
    "a coat",                   
    "a skirt",               
    # footwear
    "a shoe",
    "a pair of shoes",
    "a sneaker",
    "a boot",
    "a sandal",
    # bags & accessories
    "a handbag",
    "a backpack",
    "a wallet",
    "a watch",
    "a pair of sunglasses",
    "a hat",
    "a scarf",
    "a belt",
    "a piece of jewelry",
    # appliances / kitchenware
    "a small kitchen appliance",
    "a pot",
    "a frying pan",
    "an electric appliance",
    "a knife set",
    # bedding / home
    "a pillow",
    "a blanket",
    "a bedding set",
    "a towel",
    # health / personal care
    "a massage device",
    "a hair dryer",
    "a toothbrush",
    # supplements / health
    "a supplement bottle",
    "a box of supplements",
    # kids / pet
    "a baby product",
    "a pet food bag",
    # generic packaging fallback
    "a product box",
    "a product on a display table",
]