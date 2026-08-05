# 0003 - Auto-detect items, vendor, and category from uploads

Status: Accepted
Date: 2026-08-04

## Context

The tool previously required a manually maintained "item types" list per
category (`DEFAULT_CONFIG.types` in `index.html`, `ITEM_TYPES` in
`backfill_import.py`): a label, a vendor, and comma-separated keywords used
to fuzzy-match product names in each upload. Adding a new sandwich or milk
type meant editing both lists by hand and keeping them in sync — a real
foot-gun the old `backfill_import.py` docstring even warned about
("silently skip anything it doesn't recognize"). There was also a manual
mode toggle letting any category be switched between "reconciliation" and
"par", which never made sense (a category's math shouldn't be a per-session
UI choice), and a manual "+ New category" button.

The owner confirmed the Product Mix CSV's `Class` column (present in every
export, currently ignored) carries both vendor *and* category — their Revel
setup names its product categories after their vendors (e.g. the milk
category is literally named "Smith Brothers Farms"). That makes item
identity, vendor, and category all derivable straight from the upload, with
one specific exception: whether a category needs reconciliation math instead
of par math is a business rule Revel's data can't express (a milk sale being
fully rung up looks identical to a sandwich sale being fully rung up — the
"some of this leaves inventory unlogged" fact lives outside the POS
entirely).

## Decision

- **Item identity = exact product `Name`.** No keyword list, no fuzzy
  matching. A brand-new sandwich, milk type, or anything else shows up the
  moment it appears in an upload — including backfilled historical data, per
  the owner's explicit requirement that backfilling shouldn't silently drop
  items not already in some hardcoded list.
- **Vendor = Class, Category = Class.** Both are read directly off the same
  column; there's no separate vendor lookup to maintain.
- **Category tabs are dynamic**, sourced from `GET /api/categories`
  (categories with saved history) merged with whatever Class values appear
  in the just-uploaded, not-yet-saved file. The manual "+ New category"
  button is gone — a category simply appears the first time its Class shows
  up in an upload.
- **Mode (reconciliation vs. par) is implicit**, driven by one hardcoded
  constant: `RECONCILIATION_CLASSES = new Set(["Smith Brothers Farms"])` in
  `index.html`, mirrored as `RECONCILIATION_CLASSES = {"Smith Brothers
  Farms"}` in `backend/backfill_import.py`. Everything else defaults to par.
  The manual mode toggle UI and the "Item types for this category" card are
  both removed.
- **Upload is now category-agnostic.** Previously you picked a category tab
  *then* uploaded a CSV filtered (via keyword matching) to just that
  category's items. Now one upload is parsed once into
  `{ className: { itemName: qty } }` across every class present, and every
  category found populates its own tab — switching tabs no longer clears the
  uploaded data, since it's shared across all of them.
- `backend/backfill_import.py` mirrors the same Class/Name extraction (no
  `ITEM_TYPES`), auto-splits a mixed export by Class, and explicitly skips
  rows under `RECONCILIATION_CLASSES` — reconciliation math needs a real
  physical beginning/ending count each week, which can't be reconstructed
  from a sales export, so silently posting par-shaped backfill data under
  the milk category would corrupt its history rather than help it.
- The Inventory Log (damage/waste) export has no Class column, so damage
  rows are matched by exact name against whichever items are already known
  for the currently selected category, not globally.

## Alternatives considered

- **Keep keyword matching, just auto-suggest new entries**: rejected —
  still requires a human to confirm/edit every new item, which is exactly
  the manual step being removed.
- **Derive mode from a heuristic** (e.g. "does this category have an
  `endingCount` field in its oldest saved entry") instead of a hardcoded
  constant: rejected as needlessly indirect for one true fact that isn't
  going to change often and is much easier to find/audit as an explicit
  constant than to reverse-engineer from data shape.

## Consequences

- Category tab labels are now literally the Class string from Revel (e.g.
  "Smith Brothers Farms", "Memoranda") rather than the previous friendly
  names ("Milk", "Sandwiches"). This is a deliberate tradeoff for zero manual
  config — flag if the raw vendor-as-category-name reads oddly in practice.
- The hardcoded `"Smith Brothers Farms"` milk-class value is a real
  assumption (the owner's best recollection, not verified against a live
  export) and now exists in **two places** that must be kept in sync by
  hand: `index.html`'s `RECONCILIATION_CLASSES` and
  `backfill_import.py`'s. If it's ever wrong, every reconciliation-mode
  computation and the backfill guard both need the same fix.
- The "Item types" manual-config card and its CSS are gone entirely;
  anyone who previously used "+ Add item type" to add something not in a
  real Revel export (a manual, unbacked-by-sales-data item) can no longer do
  that — every item must appear in an actual upload first.
