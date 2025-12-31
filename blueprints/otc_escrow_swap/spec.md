# OTC Escrow Swap Blueprint — Specification (Final)

This document defines the **authoritative specification** for the production OTC Escrow Swap nano-contract deployed on the Hathor network.

The behavior described here MUST match the deployed `OtcEscrowSwap` blueprint.

---

## 1. Blueprint Purpose & Scope

### 1.1 Purpose

The **OTC Escrow Swap blueprint** provides a **trust-minimized, on-chain escrow mechanism** for over-the-counter (OTC) token swaps on the Hathor network.

It enables two parties to exchange tokens directly **without relying on an order book, automated market maker, or external pricing oracle**, while ensuring:

* deterministic settlement rules
* strict conservation of funds
* no counterparty risk during funding
* safe recovery paths in the event of non-cooperation or timeout

The blueprint is designed to be **simple, auditable, and composable**, suitable for direct user interaction, CLI usage, and website-based visualization.

---

### 1.2 Core Functionality

The blueprint supports:

* Maker-defined swap offers (base units only)
* Public and directed escrows
* Strict maker-first funding order
* Stage-based expiry with refunds
* Deterministic protocol fees
* Safe cancellation and refund paths
* Website- and indexer-friendly introspection

---

### 1.3 Non-Goals

This blueprint intentionally does **not** attempt to:

* Provide price discovery or market matching
* Integrate external oracles
* Automatically settle based on time
* Maintain on-chain lists filtered by status or address

These concerns are expected to be handled **off-chain**.

---

## 2. Amounts & Decimals

All amounts are stored and validated in **base units**.

* Hathor native and issued tokens use **2 decimals**
* `1.00` token = `100` base units

### Rules

* All amounts passed to the contract are base units
* Deposits and withdrawals must match exactly
* Any mismatch causes the transaction to fail
* Deposit and withdrawal actions must operate on exactly one token and one amount.


---

## 3. Roles & Identity Model

Each escrow involves the following roles:

* **Owner** — caller identity at `initialize()`
* **Maker** — opens the escrow
* **Taker** — accepts and funds the escrow
* **Fee Recipient** — withdraws accumulated protocol fees

All identities are enforced via CallerID.

---

## 4. Escrow Lifecycle

### 4.1 Initialization

`initialize(ctx, …)` sets:

* owner
* fee recipient
* protocol fee (bps)
* default expiry configuration
* storage and counters

---

### 4.2 Open Escrow (Maker)

Public and directed escrows may be opened, with optional custom expiry.

Effects:

* Escrow terms stored
* `open_expiry_timestamp` recorded
* Status → `STATUS_OPEN`
* Escrow ID appended
* Counters updated

---

### 4.3 Accept Escrow (Taker)

`accept_escrow(ctx, escrow_id)`:

* Records taker identity
* Enforces directed-taker restriction if applicable
* Must not be expired
* Status → `STATUS_ACCEPTED`


#### Directed escrow rules

If an escrow is directed:

- Only the configured directed taker may accept the escrow
- Only the directed taker may fund the taker side
- The maker may update the directed taker only while the escrow is OPEN
- Directed takers may never be the maker identity

---

### 4.4 Cancel Before Funding (Maker-Only)

`cancel_before_funding(ctx, escrow_id)`:

* Allowed only before any funding
* Status → `STATUS_CANCELLED` (terminal)
* No fees charged

---

### 4.5 Maker Funds

`fund_maker(ctx, escrow_id)`:

* Maker deposits exact `maker_amount`
* Sets `maker_funded_expiry_timestamp`
* Status → `STATUS_FUNDED_MAKER`

---

### 4.6 Taker Funds

`fund_taker(ctx, escrow_id)`:

* Taker deposits exact `taker_amount`
* Must not be expired for maker-funded stage
* Status → `STATUS_FUNDED_BOTH`

---

### 4.7 Withdraw (Settlement)

`withdraw(ctx, escrow_id)`:

* Maker withdraws `taker_amount − taker_fee`
* Taker withdraws `maker_amount − maker_fee`
* Fees are internally accounted
* Status → `STATUS_EXECUTED` once settlement completes

Withdrawals are explicit user actions; settlement is not automatic when both sides are funded.
---

### 4.8 Refund (After Expiry)

`refund(ctx, escrow_id)`:

* Allowed only after stage-appropriate expiry
* Each party refunds only their own deposit
* No protocol fees charged
* Status → `STATUS_REFUNDED` once complete

Refunds must be explicitly claimed; they are not automatic.
STATUS_REFUNDED is reached only after all eligible parties have successfully refunded their deposits.

---

## 5. Escrow Status Constants

| Value | Name                | Meaning            |
| ----: | ------------------- | ------------------ |
|     0 | STATUS_OPEN         | Maker set terms    |
|     1 | STATUS_ACCEPTED     | Taker recorded     |
|     2 | STATUS_FUNDED_MAKER | Maker funded       |
|     3 | STATUS_FUNDED_BOTH  | Both funded        |
|     4 | STATUS_EXECUTED     | Swap completed     |
|     5 | STATUS_REFUNDED     | Fully refunded     |
|    -2 | STATUS_CANCELLED    | Cancelled by maker |

---

## 6. Expiry Model (Stage-Based)

Expiry is **derived**, not a stored status.

* OPEN / ACCEPTED → `open_expiry_timestamp`
* FUNDED_MAKER → `maker_funded_expiry_timestamp`
* FUNDED_BOTH and later → expiry no longer applies

Expiry:

* Prevents forward actions
* Enables refunds
* Does not mutate stored status

---

## 7. Protocol Fees

* Defined in basis points (bps)
* Bounded: `0 ≤ bps ≤ 200`
* Calculated via ceil rounding
* Charged only on execution
* Never charged on cancellation or refund paths

Fees are accumulated per token UID and withdrawable only by the fee recipient.

## Configuration Bounds

| Parameter | Constraint |
|---------|------------|
| Protocol fee | `0 ≤ bps ≤ 200` |
| Min expiry | `> 0` seconds |
| Max expiry | `≥ min_expiry_secs` |
| Default expiries | Must be within `[min, max]` |


Note: The blueprint ships with production defaults
(`min_expiry_secs = 60`, `max_expiry_secs = 365 days`, etc.),
but these values are configurable by the owner at initialization
and via `set_expiry_config`, subject to the bounds above.

### Production defaults

| Parameter | Default |
|---------|---------|
| Default open expiry | 30 days |
| Default maker-funded expiry | 7 days |
| Min expiry | 60 seconds |
| Max expiry | 365 days |

---

## 8. Views & Introspection

All views return **positional arrays**.

### Key Views

* `get_config()`
* `get_escrow(id)`
* `get_escrow_full(id, now)`
* `get_fee_quote(maker_amount, taker_amount)`
* `get_counters()`
* `get_escrow_ids_page(cursor, limit)`

These support UI rendering, troubleshooting, and off-chain indexing.

---

## 9. Safety Invariants

1. Conservation of funds
2. No fee on failure paths
3. Deterministic integer math
4. No oracle dependencies
5. Explicit role enforcement
6. Expiry never causes loss of funds

---

## 10. Final Notes

This specification represents the **production-ready OTC Escrow Swap blueprint**.

Any future changes MUST:

* Update this document
* Preserve backward compatibility unless explicitly versioned

---

**End of specification.**
