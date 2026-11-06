"""Loader for authored JSON datasets (core + family files).

Checks for:
- JSON validity
- Schema validation against AuthoredCore and AuthoredFamily models
- Rejection of authored derived fields (V02)
- Resolution of {"offset_days": <int>} to ISO dates YYYY-MM-DD
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Union
import json

from pydantic import ValidationError

from datagen.constants import REFERENCE_DATE
from datagen.models import AuthoredCore, AuthoredFamily


DERIVED_FIELD_NAMES: Set[str] = {
    "subtotal",
    "tax_total",
    "grand_total",
    "line_total",
    "qty_remaining",
    "remaining_money",
    "total",
    "embedding",
    "invoice_no_norm",
}


def find_derived_fields_in_raw(obj: Any, path: str = "") -> List[str]:
    """Recursively search for derived field keys in an authored raw dictionary/list."""
    violations: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            current_path = f"{path}.{k}" if path else k
            if k in DERIVED_FIELD_NAMES:
                violations.append(current_path)
            violations.extend(find_derived_fields_in_raw(v, current_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            violations.extend(find_derived_fields_in_raw(item, f"{path}[{i}]"))
    return violations


def resolve_offset_date(offset_days: int, ref_date: datetime.date = REFERENCE_DATE) -> str:
    """Resolve an offset_days integer to an ISO date string."""
    d = ref_date + datetime.timedelta(days=offset_days)
    return d.isoformat()


class LoadedBase:
    def __init__(
        self,
        core: AuthoredCore,
        families: Dict[str, AuthoredFamily],
        raw_core: Dict[str, Any],
        raw_families: Dict[str, Dict[str, Any]],
        load_errors: List[Dict[str, Any]],
    ):
        self.core = core
        self.families = families
        self.raw_core = raw_core
        self.raw_families = raw_families
        self.load_errors = load_errors


def load_authored_base(base_dir: Union[str, Path]) -> LoadedBase:
    """Loads core.json and all family_*.json files in base_dir.

    Records schema errors and derived field presence.
    """
    base_path = Path(base_dir)
    core_path = base_path / "core.json"

    load_errors: List[Dict[str, Any]] = []
    raw_core: Dict[str, Any] = {}
    core: Optional[AuthoredCore] = None

    if not core_path.exists():
        load_errors.append({
            "code": "V01",
            "severity": "ERROR",
            "id": "core.json",
            "message": f"core.json not found in {base_dir}",
            "fix": "Ensure base/core.json exists",
        })
    else:
        try:
            with open(core_path, "r", encoding="utf-8") as f:
                raw_core = json.load(f)
            # Check derived fields in raw
            derived_violations = find_derived_fields_in_raw(raw_core)
            if derived_violations:
                load_errors.append({
                    "code": "V02",
                    "severity": "ERROR",
                    "id": "core.json",
                    "message": f"Authored derived fields present: {', '.join(derived_violations)}",
                    "fix": "Remove derived totals/remaining fields from core.json",
                })
            core = AuthoredCore.model_validate(raw_core)
        except json.JSONDecodeError as e:
            load_errors.append({
                "code": "V01",
                "severity": "ERROR",
                "id": "core.json",
                "message": f"Invalid JSON in core.json: {e}",
                "fix": "Fix JSON syntax in core.json",
            })
        except ValidationError as e:
            load_errors.append({
                "code": "V01",
                "severity": "ERROR",
                "id": "core.json",
                "message": f"Schema validation error in core.json: {e.errors(include_url=False)}",
                "fix": "Align core.json with AuthoredCore schema",
            })

    # Load family files: R, B, I, N
    families: Dict[str, AuthoredFamily] = {}
    raw_families: Dict[str, Dict[str, Any]] = {}

    for fam_name in ["R", "B", "I", "N"]:
        fam_path = base_path / f"family_{fam_name}.json"
        if not fam_path.exists():
            load_errors.append({
                "code": "V01",
                "severity": "ERROR",
                "id": f"family_{fam_name}.json",
                "message": f"family_{fam_name}.json not found in {base_dir}",
                "fix": f"Ensure base/family_{fam_name}.json exists",
            })
            continue

        try:
            with open(fam_path, "r", encoding="utf-8") as f:
                raw_fam = json.load(f)
            raw_families[fam_name] = raw_fam

            derived_violations = find_derived_fields_in_raw(raw_fam)
            if derived_violations:
                load_errors.append({
                    "code": "V02",
                    "severity": "ERROR",
                    "id": f"family_{fam_name}.json",
                    "message": f"Authored derived fields present: {', '.join(derived_violations)}",
                    "fix": f"Remove derived totals/remaining fields from family_{fam_name}.json",
                })

            fam = AuthoredFamily.model_validate(raw_fam)
            families[fam_name] = fam
        except json.JSONDecodeError as e:
            load_errors.append({
                "code": "V01",
                "severity": "ERROR",
                "id": f"family_{fam_name}.json",
                "message": f"Invalid JSON in family_{fam_name}.json: {e}",
                "fix": f"Fix JSON syntax in family_{fam_name}.json",
            })
        except ValidationError as e:
            load_errors.append({
                "code": "V01",
                "severity": "ERROR",
                "id": f"family_{fam_name}.json",
                "message": f"Schema validation error in family_{fam_name}.json: {e.errors(include_url=False)}",
                "fix": f"Align family_{fam_name}.json with AuthoredFamily schema",
            })

    return LoadedBase(
        core=core,
        families=families,
        raw_core=raw_core,
        raw_families=raw_families,
        load_errors=load_errors,
    )
