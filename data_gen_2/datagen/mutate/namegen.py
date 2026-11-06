"""Lookalike vendor name generator.

02_PIPELINE_SCRIPTS.md Section 6:
Generate candidates by edits (word substitution/addition/drop, single-character edits,
transposition, substitution with a look-alike letter such as m->rn, l->I, o->0, etc.)
and keep the first (by deterministic order) whose normalized similarity to the real name
lies in [reject_threshold + 0.03, match_threshold - 0.03] (about 0.78-0.87),
and also does not exceed the similarity to any other vendor's name.
"""

from typing import List, Optional
from rapidfuzz import fuzz

from datagen.norm import normalize_vendor_name


LOOKALIKE_SUBS = [
    ("m", "rn"),
    ("rn", "m"),
    ("l", "I"),
    ("I", "l"),
    ("o", "0"),
    ("0", "o"),
    ("e", "c"),
    ("c", "e"),
    ("w", "vv"),
    ("vv", "w"),
    ("cl", "d"),
    ("d", "cl"),
    ("i", "1"),
    ("1", "i"),
    ("s", "5"),
    ("5", "s"),
    ("b", "8"),
    ("8", "b"),
]

ALT_INDUSTRY_WORDS = [
    "Parts",
    "Systems",
    "Technologies",
    "Labs",
    "Solutions",
    "Works",
    "Industries",
    "Enterprise",
    "Ventures",
    "Global",
    "Supplies",
]


def generate_lookalike_name(
    vendor_name: str,
    other_vendor_names: List[str],
    match_threshold: float = 0.90,
    reject_threshold: float = 0.75,
) -> str:
    """Generate a lookalike name within [reject_threshold + 0.03, match_threshold - 0.03] similarity."""
    target_min = reject_threshold + 0.03
    target_max = match_threshold - 0.03

    norm_target = normalize_vendor_name(vendor_name)
    norm_others = [normalize_vendor_name(o) for o in other_vendor_names]

    # Generate candidate variations deterministically
    candidates: List[str] = []

    words = vendor_name.split()

    # 1. Multi-word substitution: replace last or first non-legal word with an industry word
    if len(words) >= 2:
        for alt_w in ALT_INDUSTRY_WORDS:
            # Replace last word
            cand_last = " ".join(words[:-1] + [alt_w])
            candidates.append(cand_last)
            # Replace middle or first word
            if len(words) >= 3:
                cand_mid = " ".join([words[0], alt_w] + words[2:])
                candidates.append(cand_mid)
            # Add word
            cand_add = " ".join(words + [alt_w])
            candidates.append(cand_add)

    # 2. Lookalike substitutions
    for old, new in LOOKALIKE_SUBS:
        if old in vendor_name:
            candidates.append(vendor_name.replace(old, new, 1))
        if old in vendor_name.lower():
            idx = vendor_name.lower().find(old)
            if idx >= 0:
                c = vendor_name[:idx] + new + vendor_name[idx + len(old):]
                candidates.append(c)

    # 3. Transposition of adjacent letters (2-3 transpositions or edits for longer strings)
    for i in range(len(vendor_name) - 1):
        if vendor_name[i].isalnum() and vendor_name[i + 1].isalnum() and vendor_name[i] != vendor_name[i + 1]:
            transposed = vendor_name[:i] + vendor_name[i + 1] + vendor_name[i] + vendor_name[i + 2:]
            candidates.append(transposed)

    # 4. Deletion of single character
    for i in range(len(vendor_name)):
        if vendor_name[i].isalnum():
            deleted = vendor_name[:i] + vendor_name[i + 1:]
            candidates.append(deleted)

    # 5. Replacement of vowels
    vowels = "aeiou"
    for i in range(len(vendor_name)):
        ch = vendor_name[i].lower()
        if ch in vowels:
            for alt_v in vowels:
                if alt_v != ch:
                    repl = vendor_name[:i] + (alt_v.upper() if vendor_name[i].isupper() else alt_v) + vendor_name[i + 1:]
                    candidates.append(repl)

    # Deduplicate candidates preserving order
    seen = set()
    unique_candidates: List[str] = []
    for c in candidates:
        if c not in seen and c != vendor_name:
            seen.add(c)
            unique_candidates.append(c)

    # Test candidates up to 200
    for cand in unique_candidates[:200]:
        norm_cand = normalize_vendor_name(cand)
        sim = fuzz.token_set_ratio(norm_cand, norm_target) / 100.0

        if target_min <= sim <= target_max:
            # Check similarity to other vendors: does not exceed sim to this vendor
            conflict = False
            for o_norm in norm_others:
                other_sim = fuzz.token_set_ratio(norm_cand, o_norm) / 100.0
                if other_sim >= sim:
                    conflict = True
                    break
            if not conflict:
                return cand

    raise RuntimeError(
        f"Could not find a lookalike name for '{vendor_name}' in range [{target_min:.2f}, {target_max:.2f}] within 200 candidates"
    )
