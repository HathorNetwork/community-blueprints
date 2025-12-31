# OtcEscrowSwap — OTC Escrow Swap Blueprint

This folder contains the **production-ready OTC escrow swap** blueprint for Hathor.

It implements a trust-minimized, on-chain escrow workflow for OTC token swaps, including:
- public or directed escrows
- strict maker-first funding order
- stage-based expiry + refunds
- deterministic protocol fees (basis points, ceil rounding, no hidden slippage)
- cancel-before-funding (maker-only)
- view methods for UI/indexer introspection

For the authoritative functional spec, see: **`spec.md`**.  
For Localnet verification steps and transaction links, see: **`localnet_testflow.md`**.

---

## Files

- `otc_escrow_swap.py` — Blueprint implementation
- `test_otc_escrow_swap.py` — Automated unit test suite (Blueprint SDK / `BlueprintTestCase`)
- `spec.md` — Authoritative specification (final)
- `localnet_testflow.md` — Localnet integration test flow & results
- `USE_CASES.md` — Design-informed intended use-cases and scope boundaries

---

## Blueprint summary

### Purpose
The blueprint provides a **trust-minimized, on-chain escrow mechanism** for OTC swaps (no order book / AMM / oracle), with deterministic settlement rules and safe recovery paths.

### Intended Use-Cases

This blueprint is designed as a **general-purpose OTC settlement primitive**.
The use-cases considered during design are documented in
`USE_CASES.md` (see ./USE_CASES.md).

These use-cases are **illustrative rather than exhaustive**, and are intended
to clarify when bilateral, deterministic escrow is preferable to AMM-based
execution (e.g., due to liquidity, price impact, or confidentiality
constraints).

### Roles
- Owner — caller identity at `initialize()`
- Maker — opens escrow
- Taker — accepts + funds escrow
- Fee Recipient — withdraws accumulated protocol fees

### Lifecycle (high-level)
1) Maker opens (public or directed), optionally with custom expiry  
2) Taker accepts  
3) Maker funds (deposit)  
4) Taker funds (deposit)  
5) Withdraw (settlement, fees charged on execution only)  
6) Refund after stage-based expiry (no fees), if needed

---

## Methods Overview (Public & View)

### Public methods (state-changing)

**Initialization & Admin**

* `initialize(protocol_fee_bps, default_open_expiry_secs, default_maker_funded_expiry_secs, min_expiry_secs, max_expiry_secs)`
  Initializes the contract configuration and sets the owner.
* `set_fee_config(fee_recipient, protocol_fee_bps)` *(owner-only)*
  Updates protocol fee recipient and fee rate (bounded).
* `set_expiry_config(default_open_expiry_secs, default_maker_funded_expiry_secs, min_expiry_secs, max_expiry_secs)` *(owner-only)*
  Updates expiry defaults and bounds.

**Escrow creation**

* `open_escrow(maker_token, maker_amount, taker_token, taker_amount)`
  Opens a public escrow using default open expiry.
* `open_escrow_with_expiry(maker_token, maker_amount, taker_token, taker_amount, expiry_timestamp)`
  Opens a public escrow with explicit expiry.
* `open_escrow_directed(maker_token, maker_amount, taker_token, taker_amount, directed_taker)`
  Opens a directed escrow using default open expiry.
* `open_escrow_directed_with_expiry(maker_token, maker_amount, taker_token, taker_amount, expiry_timestamp, directed_taker)`
  Opens a directed escrow with explicit expiry.

**Escrow lifecycle**

* `accept_escrow(escrow_id)`
  Taker accepts escrow terms (no token movement).
* `set_directed_taker(escrow_id, new_directed_taker)` *(maker-only, OPEN only)*
  Updates the directed taker before funding.
* `cancel_before_funding(escrow_id)` *(maker-only)*
  Cancels escrow before any funding has occurred.

**Funding**

* `fund_maker(escrow_id)` *(deposit required)*
  Maker deposits maker token (must be exact).
* `fund_taker(escrow_id)` *(deposit required)*
  Taker deposits taker token (maker must be funded first).

**Settlement**

* `withdraw(escrow_id)` *(withdrawal required)*
  Maker or taker withdraws net proceeds after full funding; protocol fees are accrued.
* `refund(escrow_id)` *(withdrawal required, after expiry)*
  Refunds deposited tokens after stage-based expiry (no fees).

---

### View methods (read-only)

* `get_config()`
  Returns current fee and expiry configuration.
* `get_fee_quote(maker_amount, taker_amount)`
  Returns protocol fee amounts and net settlement values.
* `get_escrow(escrow_id)`
  Returns summary escrow state.
* `get_escrow_full(escrow_id, timestamp)`
  Returns full escrow state with expiry flags.
* `get_counters()`
  Returns aggregate escrow counters.
* `get_escrow_ids_page(cursor, limit)`
  Returns paginated escrow IDs for UI/indexing.

---

## Out of scope

- No partial fills or order-book matching
- No oracle-based pricing
- No automatic execution without explicit withdraw calls
- No fee charging on cancel or refund paths

---

## Key safety rules (highlights)

- **Amounts are base units**; deposits/withdrawals must match exactly.
- **Maker must fund before taker**.
- **Expiry is stage-based**:
  - OPEN/ACCEPTED uses `open_expiry_timestamp`
  - FUNDED_MAKER uses `maker_funded_expiry_timestamp`
  - FUNDED_BOTH and later: expiry no longer applies
- **Fees**
  - bps bounded: `0 ≤ bps ≤ 200`
  - charged only on execution, never on cancel/refund paths

---

## Key constants & defaults

| Parameter | Value |
|---------|------|
| `MAX_PROTOCOL_FEE_BPS` | 200 (2.00%) |
| Default open expiry | 30 days |
| Default maker-funded expiry | 7 days |
| Min expiry | 60 seconds |
| Max expiry | 365 days |

---

## How to run unit tests (Blueprint SDK)

These unit tests use Hathor’s `BlueprintTestCase` harness (same pattern as
`test_swap_demo.py` in `hathor-core`).

The test file included in this submission is intended to be copied into a
`hathor-core` checkout for execution, which is how the Hathor team validates
blueprint unit tests.

From the root of a `hathor-core` checkout:

```
poetry install

poetry run pytest -v -n0 hathor_tests/nanocontracts/blueprints/test_otc_escrow_swap.py \
  -W ignore::DeprecationWarning \
  -W ignore::PendingDeprecationWarning \
  -W ignore::FutureWarning
```

### Latest unit test result

✅ **23 passed**

#### Scenario coverage (unit tests)

Core scenarios (aligned with Localnet scenario IDs):

* `SA` deploy/initialize config sanity
* `S0` public complete lifecycle with fees
* `S1` directed complete lifecycle
* `S2` cancel before funding (maker-only)
* `S3` refund before expiry fails, then normal settlement
* `S4` expiry before accept blocks accept + `get_escrow_full` expiry flags
* `S5` accept before expiry; funding after expiry blocked
* `S8` directed: wrong taker cannot fund
* `S10` set_directed_taker negative cases
* `S12` directed: maker funded then expires → refund
* `S13` public: maker funded then expires → refund
* `S14` directed: wrong taker cannot accept; correct taker can accept
* `S15` directed retarget then accept
* `S16` directed: open-expiry blocks funding after expiry
* `S17` admin/owner-only actions
* `S18` views + counters + pagination sanity

Unit Test Extras (hardening beyond Localnet scenarios):

* `UTE-01` set_fee_config bounds + auth (bps range, owner-only)
* `UTE-02` set_expiry_config bounds + auth (min/max and default bounds)
* `UTE-03` accept by second taker fails (race protection)
* `UTE-04` fund_maker invalid actions (wrong token/amount)
* `UTE-05` fund_taker invalid actions (wrong token/amount)
* `UTE-06` withdraw invalid actions (wrong token/amount)
* `UTE-07` double withdraw + closed-state guards

---

## Localnet testing note

The file `localnet_testflow.md` documents end-to-end scenario testing
performed on a private Hathor Localnet, including transaction hashes
and expected outcomes.

Because Localnet chain state is environment-specific, the underlying
chain snapshot used to generate these transactions is not included
in this repository.

The corresponding Localnet state archive
(`hathor_localnet_state_20251229_205141.tar`)
can be provided to reviewers upon request if deeper reproduction
or inspection is desired.

---

## Security & design considerations

- All token movements are validated via strict action parsing (single-token, exact-amount deposits and withdrawals).
- Funding order is enforced (maker must fund before taker).
- Directed escrows enforce identity checks on accept and funding paths.
- Expiry is enforced per lifecycle stage to avoid indefinite lockups.
- Cancel and refund paths never charge protocol fees.
- All settlement and refund paths are idempotent and protected against double-withdrawal.

---

## Notes for reviewers

* The behavior described in `spec.md` is authoritative for this submission. 
* Unit tests are designed to validate:

  * auth gates and invariants
  * stage expiry enforcement
  * strict action validation (deposit/withdraw correctness)
  * deterministic fee math behavior and fee recipient withdrawal path

---
