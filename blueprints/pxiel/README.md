# Pxiel — Collaborative Pixel Canvas Blueprint

This folder contains the **Pxiel** blueprint for Hathor — a collaborative pixel art canvas where users can paint pixels by paying HTR fees.

---

## Files

- `pxiel.py` — Blueprint implementation
- `tests_pxiel.py` — Automated test suite (Blueprint SDK / `BlueprintTestCase`)

---

## Blueprint Summary

### Purpose
The blueprint provides a **collaborative pixel art canvas** (similar to Reddit's r/place) where anyone can paint pixels on a shared grid by depositing HTR as a fee. The canvas owner can withdraw accumulated fees.

### Key Features
- Configurable canvas size and fee per pixel
- Single pixel painting with fee deposit
- Batch painting (up to 32 pixels per transaction)
- Fee collection and owner withdrawal
- Paginated view of all painted pixels
- Event emission for real-time updates

### Roles
- **Owner** — The address that initialized the contract; can withdraw accumulated fees
- **Painter** — Any user who pays the fee to paint pixels

---

## Methods Overview

### Public Methods (State-Changing)

| Method | Description |
|--------|-------------|
| `initialize(size, fee_htr)` | Creates a new canvas with given size (NxN) and fee per pixel |
| `paint(x, y, color)` | Paints a single pixel (requires HTR deposit ≥ fee) |
| `paint_batch(xs, ys, colors)` | Paints multiple pixels in one transaction (max 32) |
| `withdraw_fees()` | Owner withdraws collected fees |

### View Methods (Read-Only)

| Method | Returns |
|--------|---------|
| `get_pixel_info(x, y)` | Color, last painter address, and timestamp for a pixel |
| `get_stats()` | Total paint count and fees collected |
| `get_owner()` | Owner address |
| `get_canvas_size()` | Canvas dimension (N for NxN grid) |
| `get_paint_fee()` | Fee in HTR cents per pixel |
| `get_pixels_count()` | Number of painted pixels |
| `get_pixels_page(offset, limit)` | Paginated list of painted pixels (max 1000 per page) |

---

## Custom Errors

| Error | Cause |
|-------|-------|
| `OutOfBounds` | Coordinates (x, y) are outside canvas bounds |
| `InvalidColorFormat` | Color is not in `#RRGGBB` hex format |
| `EmptyBatch` | Batch is empty, too large (>32), or arrays have mismatched sizes |
| `FeeRequired` | No HTR deposit or deposit amount is below required fee |

---

## Key Constants

| Parameter | Value |
|-----------|-------|
| `MAX_BATCH_SIZE` | 32 pixels |
| `MAX_PIXELS_PAGE_SIZE` | 1000 pixels |

---

## Example Usage

```python
# Initialize a 100x100 canvas with 1 HTR cent fee per pixel
contract.initialize(size=100, fee_htr=1)

# Paint pixel at (10, 20) with color #FF5733
contract.paint(x=10, y=20, color="#FF5733")  # requires 1 HTR cent deposit

# Batch paint 3 pixels
contract.paint_batch(
    xs=[0, 1, 2],
    ys=[0, 1, 2],
    colors=["#FF0000", "#00FF00", "#0000FF"]
)  # requires 3 HTR cents deposit
```

---

## Events

The contract emits a `Paint` event for each pixel painted:

```json
{"event": "Paint", "x": 10, "y": 20, "color": "#FF5733", "fee": 1}
```

---

## Security Considerations

- All coordinates are validated against canvas bounds
- Color format is strictly validated (`#RRGGBB` hex)
- Fee deposits are validated against required minimum
- Only the owner can withdraw accumulated fees
- Batch size is capped to prevent gas exhaustion

---

## How to Run Tests

From the root of a `hathor-core` checkout:

```bash
poetry install
poetry run pytest -v tests_pxiel.py
```
