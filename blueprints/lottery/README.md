# Lottery — Simple HTR Lottery Blueprint

This folder contains the **Lottery** blueprint for Hathor — a single-round lottery where users buy tickets with HTR and a winner receives the prize after the lottery is drawn.

---

## Files

- `lottery.py` — Blueprint implementation
- `tests.py` — Automated test suite (Blueprint SDK / `BlueprintTestCase`)

---

## Blueprint Summary

### Purpose
The blueprint implements a **single lottery round** with a fixed ticket price and a configurable commission paid to the creator. The creator can draw the winner any time before timeout; after timeout anyone can draw.

### Key Features
- Configurable ticket price and commission (0–100%)
- 10 HTR creation fee (claimable by creator)
- Ticket purchases accumulate the pot
- Winner selection using the contract RNG (deterministic across nodes)
- Creator and winner payouts tracked independently
- Event emission for creation, ticket purchase, winner draw, and reward claims

### Roles
- **Creator** — Address that initializes the contract; receives creation fee and commission
- **Participants** — Addresses that buy tickets and are eligible to win

---

## Methods Overview

### Public Methods (State-Changing)

| Method | Description |
|--------|-------------|
| `initialize(description, ticket_price, commission_percent)` | Creates a new lottery with ticket price and commission |
| `buy_ticket()` | Buys a ticket (requires HTR deposit ≥ ticket price) |
| `draw_winner()` | Draws a winner; creator-only before timeout, anyone after |
| `claim_reward()` | Withdraws available reward for creator or winner |

### View Methods (Read-Only)

| Method | Returns |
|--------|---------|
| `get_state()` | Current lottery state snapshot |

---

## Custom Errors

| Error | Cause |
|-------|-------|
| `InvalidPrice` | Ticket price ≤ 0 or commission outside 0–100 |
| `InsufficientFunds` | Missing deposit or deposit below required amount |
| `LotteryClosed` | Action not allowed because lottery is closed |
| `Unauthorized` | Caller not allowed to draw/withdraw |

---

## Key Constants

| Parameter | Value |
|-----------|-------|
| `CREATION_FEE` | `1000` (10 HTR in cents) |
| `TIMEOUT_SECONDS` | `2,592,000` (30 days) |

---

## Example Usage

```python
# Initialize a lottery with a 5 HTR ticket price and 10% commission
contract.initialize("Weekly Lottery", ticket_price=500, commission_percent=10)

# Buy a ticket (requires deposit >= 5 HTR)
contract.buy_ticket()

# Draw winner (creator only until timeout)
contract.draw_winner()

# Claim reward (winner or creator)
contract.claim_reward()
```

---

## Events

The contract emits JSON-formatted events:

```json
{"event": "LotteryCreated", "creator": "<hex-address>", "fee": 1000}
{"event": "TicketBought", "buyer": "<hex-address>", "count": 3}
{"event": "WinnerDrawn", "winner": "<hex-address>", "prize": 1350}
{"event": "RewardClaimed", "claimer": "<hex-address>", "amount": 1350}
```

---

## Security Considerations

- Winner selection uses the contract RNG, which is deterministic across nodes.
- Ticket purchases accept deposits greater than the ticket price and add the full amount to the pot.
- Only the creator can draw before timeout; after timeout anyone can draw.
- Rewards are tracked per-role and can be claimed incrementally.

---

## How to Run Tests

From the root of a `hathor-core` checkout:

```bash
poetry install
poetry run pytest -v tests.py
```
