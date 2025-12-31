> **Scope Note:**  
> This document reflects the intended use-cases supported by the
> current OtcEscrowSwap implementation and does not imply future
> features unless explicitly stated.

## Intended Use-Cases for **OtcEscrowSwap**

**OtcEscrowSwap** is designed for **trust-minimized, bilateral token exchanges**
where price discovery, liquidity depth, or public market impact are either
undesirable or impossible. It complements AMM-based DeFi rather than competing
with it.

---

## High-Level Mechanics

OtcEscrowSwap enables two parties (maker and taker) to exchange predefined
amounts of two tokens using an on-chain escrow. Both parties must fund the
escrow according to the agreed terms before the swap can execute. If the
conditions are not met within the contract lifecycle, funds are refundable
according to the escrow rules.

---

## Design-Informed Use-Cases

The following use-cases represent **common and intentional applications**
considered during the design of OtcEscrowSwap. They are **illustrative rather
than exhaustive** and are meant to demonstrate where deterministic, bilateral
OTC settlement is most appropriate.

The blueprint is intentionally generic and composable, and may support
additional use-cases beyond those listed here, provided they align with the
core mechanics and constraints described above.

---

### 1. Private Sale Allocations (Seed, Private, Strategic Rounds)

**Problem:**  
Private token sales often rely on manual trust, multisig coordination, or
centralized escrow services.

**Solution with OtcEscrowSwap:**

* Enables **direct, wallet-to-wallet private sales**
* Enforces **atomic settlement** within the contract lifecycle  
  (either both sides fund correctly or funds are refunded)
* Eliminates counterparty risk and human escrow
* Supports **directed escrows** (only a specific counterparty can accept)

**Ideal for:**

* Seed & private rounds
* Strategic partner allocations
* OTC vesting-free allocations

---

### 2. New Token Launches (Pre-Liquidity Phase)

**Problem:**  
Early token distribution often occurs **before any AMM pool exists**, forcing
teams to use manual transfers or centralized intermediaries.

**Solution with OtcEscrowSwap:**

* Enables **early OTC trading before liquidity pools**
* Allows price negotiation without public price anchoring
* Avoids front-running, MEV, and premature volatility
* Keeps early distribution **off-market and controlled**

**Ideal for:**

* Pre-DEX launch trading
* Advisor allocations
* Early community partners
* Genesis distribution phases

---

### 3. Large Trades Without Market Impact (Whale-Safe Transfers)

**Problem:**  
Large buys or sells on AMMs cause slippage, price crashes, and signaling risk.

**Solution with OtcEscrowSwap:**

* Executes **fixed-price bilateral swaps**
* No slippage, no pool imbalance
* No impact on public price charts
* No immediate arbitrage pressure during execution

**Ideal for:**

* Funds entering or exiting positions
* Treasury rebalancing
* Strategic reallocations
* OTC desks operating on-chain

---

### 4. Trading Tokens With No Existing Liquidity

**Problem:**  
AMMs require liquidity; without it, tokens are effectively illiquid.

**Solution with OtcEscrowSwap:**

* Enables trading **without liquidity pools**
* Works with:
  * Long-tail tokens
  * Experimental assets
  * Private or gated tokens
* No need to bootstrap pools prematurely

**Ideal for:**

* Niche tokens
* DAO-internal assets
* Early-stage or experimental projects
* Tokens intentionally not listed publicly

---

## Additional Expanded Use-Cases

### 5. Cross-Treasury or DAO-to-DAO Swaps

* DAO treasuries exchanging assets directly
* Avoids market execution risk
* Fully on-chain, auditable, and deterministic
* Requires both treasuries to agree on fixed terms prior to execution

---

### 6. Tokenized Access or On-Chain Entitlements (Fungible Assets)

* Fungible tokens exchanged for access rights, licenses, or utility claims
* Both sides must fund the escrow with fee-compatible on-chain assets
* Protocol fees are applied at execution and must be supported by the
  transferred asset
* The contract does not verify off-chain service delivery

**Examples:**
* Access or subscription tokens
* Validator bond or stake tokens
* Utility or entitlement tokens

---

### 7. Compliance-Sensitive or Jurisdiction-Aware Trades

* Directed escrows prevent unauthorized participation
* No open order book
* Reduced exposure to retail participation
* Cleaner audit trail
* Compliance constraints are enforced through counterparty selection,
  not identity verification

---

### 8. Coordinated OTC Exchanges Across Separate Token Domains

* Used to coordinate economic exchanges between separate token ecosystems
* No wrapping, minting, or cross-chain verification
* Settlement is negotiated off-chain and executed independently

**Notes:**
* The blueprint does not provide cross-chain atomicity
* This use-case relies on human or institutional coordination

---

## Non-Goals

OtcEscrowSwap intentionally does NOT:
* Verify off-chain service delivery
* Act as a cross-chain bridge
* Provide price discovery or liquidity pooling
* Replace AMMs or order books

---

## Out of Scope (Current Version)

The following are intentionally out of scope for the current implementation:
* Partial fills or incremental settlement
* Conditional or oracle-based execution
* Multi-party or auction-based swaps
* Programmatic price discovery

---

## Positioning vs AMMs & DeFi Suites

OtcEscrowSwap is designed for negotiated exchanges where AMMs are
structurally unsuitable, not as a replacement for pool-based DeFi.

**OtcEscrowSwap is NOT:**
* An AMM
* A liquidity pool
* A farming or yield protocol

**It IS:**
* A **foundational OTC primitive**
* A **trust-minimized settlement layer**
* A complement to DeFi suites, not a competitor

> AMMs are optimal for **continuous price discovery**  
> OTC escrow is optimal for **intentional, negotiated value exchange**
