"""Aggregate the items and blocks a mod set registers (the pack's "what's in it").

Without running the game we can't query the live registries, so we approximate
from two cross-loader, language-agnostic asset sources, in priority order:

1. ``assets/<ns>/lang/en_us.json`` — keys ``item.<ns>.<name>`` / ``block.<ns>.<name>``
   give both the id *and* a human display name. This is the most reliable source
   and covers block-items too.
2. ``assets/<ns>/models/item/<name>.json`` — fills in items that have a model but
   no lang entry (no display name).

Block *models* are intentionally skipped: a block has many model/state variants,
so they'd massively over-count. Block-items still surface via the lang ``block.*``
keys. Items registered purely in code (no lang, no item model) aren't captured —
documented as an approximation in the UI.
"""

import json
import zipfile
from pathlib import Path
from typing import Any, Literal

from app.models import ItemEntry, RegistryIndex

_LANG_SUFFIX = "/lang/en_us.json"


def build_registry_index(jars: list[Path]) -> RegistryIndex:
    """Scan every jar's lang/model assets into a deduplicated item/block index."""
    entries: dict[str, ItemEntry] = {}
    for jar in jars:
        try:
            with zipfile.ZipFile(jar) as zf:
                names = zf.namelist()
                _collect_lang(zf, names, entries)
                _collect_item_models(names, entries)
        except (zipfile.BadZipFile, OSError):
            continue
    items = sorted(entries.values(), key=lambda e: (e.kind, e.id))
    return RegistryIndex(
        items=items,
        total=len(items),
        item_count=sum(1 for e in items if e.kind == "item"),
        block_count=sum(1 for e in items if e.kind == "block"),
    )


def _collect_lang(zf: zipfile.ZipFile, names: list[str], entries: dict[str, ItemEntry]) -> None:
    for name in names:
        if not (name.startswith("assets/") and name.endswith(_LANG_SUFFIX)):
            continue
        try:
            data: Any = json.loads(zf.read(name), strict=False)
        except (json.JSONDecodeError, KeyError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            parsed = _parse_lang_key(key)
            if parsed is None:
                continue
            kind, item_id, ns = parsed
            display = value if isinstance(value, str) else None
            # Lang is authoritative (it carries names); always overwrite.
            entries[item_id] = ItemEntry(id=item_id, display_name=display, kind=kind, mod=ns)


def _parse_lang_key(key: str) -> tuple[Literal["item", "block"], str, str] | None:
    """``item.create.brass_ingot`` -> ``("item", "create:brass_ingot", "create")``.

    Only exact ``<kind>.<ns>.<name>`` keys count; the extra dotted segment of
    tooltip/description lines (``...desc``) is rejected.
    """
    parts = key.split(".")
    if len(parts) != 3:
        return None
    kind, ns, name = parts
    if kind not in ("item", "block") or not ns or not name:
        return None
    return kind, f"{ns}:{name}", ns  # type: ignore[return-value]


def _collect_item_models(names: list[str], entries: dict[str, ItemEntry]) -> None:
    for name in names:
        parts = name.split("/")
        # assets/<ns>/models/item/<rel...>.json
        if (
            len(parts) < 5
            or parts[0] != "assets"
            or parts[2] != "models"
            or parts[3] != "item"
            or not name.endswith(".json")
        ):
            continue
        ns = parts[1]
        rel = "/".join(parts[4:])[: -len(".json")]
        item_id = f"{ns}:{rel}"
        # Don't clobber a lang-named entry; only fill genuine gaps.
        if item_id not in entries:
            entries[item_id] = ItemEntry(id=item_id, display_name=None, kind="item", mod=ns)
