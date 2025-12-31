# OTC Escrow Swap — Consolidated Localnet Test Flow (Production)

> **Scope:** Consolidates scenario tests from prior versions into a single run against `OTC_Escrow_Prod.py`.
> **Rule:** Each scenario uses a unique escrow ID, created in-order within this single localnet session.
> **Views:** Query via `GET /wallet/nano-contracts/state?...&calls[]=` (views are not `@public`).
> **TestStatus:** All test scenarios below have passed on Localnet.
> **TestStatusEnv:** Chain state file for tx confirmations: hathor_localnet_state_20251229_205141.tar

## Scenario Index (Escrow IDs)

| Scenario | Escrow ID | Description |
|---|---:|---|
| SA |  | Deploy & Initialize (blueprint + contract) | **Pass**
| S0 | 0 | Public Escrow — Complete Lifecycle (open→accept→funds→withdraws/fees) | **Pass**
| S1 | 1 | Directed Escrow — Complete Lifecycle | **Pass**
| S2 | 2 | Public Escrow — Cancel Before Funding | **Pass**
| S3 | 3 | Public Escrow — Both Funded (verify refund blocked; settle normally) | **Pass**
| S4 | 4 | Public Escrow — Expires Before Accept (accept/fund blocked) | **Pass**
| S5 | 5 | Public Escrow — Expires After Accept (cannot fund) | **Pass**
| S8 | 8 | Directed — Wrong Taker Cannot Fund | **PASS**
| S10 | 10 | Directed — set_directed_taker Negative Tests | **PASS**
| S12 | 12 | Directed + Expiry + Refund (maker funded then expires; maker refunds) | **PASS**
|---|---:|---|
| S13 | 13 | RETEST of S6 - Public Escrow — Maker Funded Only then Expires (taker cannot fund; maker refunds) | **PASS**
| S14 | 14 | RETEST of S7 - Directed — Wrong Taker Cannot Accept | **PASS**
| S15 | 15 | RETEST of S9 - Directed — Maker Retargets Directed Taker (OPEN only) | **PASS**
| S16 | 16 | RETEST of S11 - Directed — Expires After Accept (cannot fund) | **PASS**
|---|---:|---|
| S17 |  | Admin/Owner Only Actions (set_fee_config access + bounds) |
| S18 |  | Views & Query Sanity (config, counters, escrow summary/full, fee quote, pagination) |
|---|---:|---|
## The following scenarios were replaced with ones above as they needed retesting under new escrow IDs. 
| S6 | 6 | Public Escrow — Maker Funded Only then Expires (taker cannot fund; maker refunds) | **PASS** **via RETEST UNDER S-13**
| S7 | 7 | Directed — Wrong Taker Cannot Accept | **Pass** **via RETEST UNDER S-14**
| S9 | 9 | Directed — Maker Retargets Directed Taker (OPEN only) | **Pass** **via RETEST UNDER S-15**
| S11 | 11 | Directed — Expires After Accept (cannot fund) | **Pass** **via RETEST UNDER S-16**

----------------------------------------------------------------

***# A) Localnet Environment Setup - Reload Backup where Testing was Completed***

Completed Testing chain state file - hathor_localnet_state_20251229_205141.tar


A-1) Stop stack:

```
docker compose down
```

A-2) Move current data out of the way and restore:

```
mv data data_backup_$(date +%Y%m%d_%H%M%S)
mkdir data

tar -xzvf hathor_localnet_state_<TIMESTAMP>.tar.gz
```

A-3) Start with loaded back-up:

```
docker compose up -d
```


***## B) Fresh chain state (for new testing purposes)***

⚠️ This deletes local chain state. Run only if you want a clean deterministic test run.

```bash
cd ~/dev/hathor-localnet
docker compose down
rm -rf data/*
docker compose up -d
```

Restore output to terminal (if needed)

```bash
exec 1>/dev/tty 2>/dev/tty
```
----------------------------------------------------------------

## 1) Constants

```bash
cd ~/dev/hathor-blueprints

export WALLET="http://localhost:8000"
export FULLNODE="http://localhost:8080"

# Tokens (reuse known test token UIDs)
export OTCM_UID="00000087d3b2fe5b3b3fb651d2e74c086328889ee3762ca67e1ac394095e1259"
export OTCT_UID="0000049397c0b4a9f030b2e8894bb35759bd555d6b43fd70591484e2e5550801"

# Fee setup
export PROTOCOL_FEE_BPS=100   # 1%

# Expiry config (short values so expiry scenario tests run quickly on Localnet)
export DEFAULT_OPEN_EXPIRY_SECS=600          # 10 minutes
export DEFAULT_MAKER_FUNDED_EXPIRY_SECS=240  # 4 minutes
export MIN_EXPIRY_SECS=60                    # 60 seconds
export MAX_EXPIRY_SECS=86400                 # 1 day
```
            

## 2) Start wallets + get addresses

```bash
# Start Alice (maker)
curl -sS -X POST -H "Content-Type: application/json" -d '{"wallet-id":"alice","seedKey":"alice"}' "$WALLET/start" | jq

# Start Bob (taker)
curl -sS -X POST -H "Content-Type: application/json" -d '{"wallet-id":"bob","seedKey":"bob"}' "$WALLET/start" | jq

# Start Genesis (negative tests)
curl -sS -X POST -H "Content-Type: application/json" -d '{"wallet-id":"genesis","seedKey":"genesis"}' "$WALLET/start" | jq

# Start Protocol (owner/dev)
curl -sS -X POST -H "Content-Type: application/json" -d '{"wallet-id":"protocol","seedKey":"protocol"}' "$WALLET/start" | jq
```

```bash
export ALICE_ADDR=$(curl -sS -H "X-Wallet-Id: alice"     "$WALLET/wallet/address" | jq -r '.address')
export BOB_ADDR=$(curl -sS -H "X-Wallet-Id: bob"       "$WALLET/wallet/address" | jq -r '.address')
export GENESIS_ADDR=$(curl -sS -H "X-Wallet-Id: genesis" "$WALLET/wallet/address" | jq -r '.address')
export PROTOCOL_ADDR=$(curl -sS -H "X-Wallet-Id: protocol" "$WALLET/wallet/address" | jq -r '.address')

echo "ALICE_ADDR=$ALICE_ADDR"
echo "BOB_ADDR=$BOB_ADDR"
echo "GENESIS_ADDR=$GENESIS_ADDR"
echo "PROTOCOL_ADDR=$PROTOCOL_ADDR"
```

---

# SA — Deploy & Initialize

## SA-01) Deploy blueprint (OTC_Escrow_Prod)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: protocol" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d "  {
    \"code\": $ESCAPED_CODE,
      \"address\": \"$PROTOCOL_ADDR\"
    }"\" \
  "$WALLET/wallet/nano-contracts/create-on-chain-blueprint" | tee /tmp/ocb_create_prod.json | jq
```

```bash
export BLUEPRINT_ID=$(jq -r '.hash' /tmp/ocb_create_prod.json)
echo "BLUEPRINT_ID=$BLUEPRINT_ID"
```

**Test Result**: Pass
**Blueprint ID**: 00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c
**Test Comments**:http://localhost:3000/transaction/00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c


## SA-02) Create contract (initialize)

Initialize args:
1) fee_recipient
2) protocol_fee_bps
3) default_open_expiry_secs
4) default_maker_funded_expiry_secs
5) min_expiry_secs
6) max_expiry_secs

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: protocol" \
  -H "Content-Type: application/json" \
  -d "  {
    \"blueprint_id\": \"$BLUEPRINT_ID\",
      \"address\": \"$PROTOCOL_ADDR\",
      \"data\": {
        \"actions\": [],
        \"args\": [
          \"$PROTOCOL_ADDR\",
          $PROTOCOL_FEE_BPS,
          $DEFAULT_OPEN_EXPIRY_SECS,
          $DEFAULT_MAKER_FUNDED_EXPIRY_SECS,
          $MIN_EXPIRY_SECS,
          $MAX_EXPIRY_SECS
        ]
      }
    }"\" \
  "$WALLET/wallet/nano-contracts/create" | tee /tmp/nc_create_prod.json | jq
```

```bash
export CONTRACT_ID=$(jq -r '.hash // .nc_id // .history.nc_id' /tmp/nc_create_prod.json)
echo "CONTRACT_ID=$CONTRACT_ID"
```

**Test Result**:Pass
**Contract ID**:00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996
**Test Comments**: http://localhost:3000/transaction/00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996

## SA-03) Sanity: get_counters() immediately after initialize

```bash
curl -sS -X GET -H "X-Wallet-Id: alice" \
  "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_counters()" | jq
```

Expected:
- total_escrows = 0
- all status counts = 0
- public = 0, directed = 0

**Test Result**: Pass
**Test Comments**: Expected results returned:

{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_counters()": {
        "value": [
          0,
          0,
          0,
          0,
          0,
          0,
          0,
          0,
          0,
          0
        ]
      }
    }
  }
}


## SA-04) Sanity: get_escrow_exists + get_escrow_status (non-existent)

```bash
curl -sS -X GET -H "X-Wallet-Id: alice" \
  "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_escrow_exists(999999)&calls[]=get_escrow_status(999999)" | jq
```

Expected:
- exists = false
- status = -1


**Test Result**: Pass
**Test Comments**: Expected results returned:

{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_escrow_exists(999999)": {
        "value": false
      },
      "get_escrow_status(999999)": {
        "value": -1
      }
    }
  }
}


---

## Helper: fee math

```
fee = ceil(amount * bps / 10_000) = (amount * bps + 9999) // 10_000
```

**Test Result**: N/A, Fail
**Test Comments**: syntax error near unexpected token 

---

# S0 — Public Escrow Complete Lifecycle (Escrow ID 0)

```bash
export ESCROW_PUBLIC=0
```

## S0-01) Alice opens public escrow

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "  {
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": { \"actions\": [], \"args\": [\"$OTCM_UID\", 100, \"$OTCT_UID\", 125] }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000006e283cebf930c069975ef440c49613d5f07e6197fb40e6a469273609964

## S0-02) Bob accepts

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "  {
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": { \"actions\": [], \"args\": [$ESCROW_PUBLIC] }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000076446d92aa03ff37a959ff8490d3d88614264421a1293cb86692ccf595a3

## S0-03) Alice funds maker (100 OTCM)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "  {
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": { \"actions\": [{\"type\":\"deposit\",\"token\":\"$OTCM_UID\",\"amount\":100}], \"args\": [$ESCROW_PUBLIC] }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000019e526eb8e78c615bd6b9f15a98bed526e94e95449441f857fdaeae4b8c

## S0-04) Bob funds taker (125 OTCT)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "  {
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_taker\",
    \"address\": \"$BOB_ADDR\",
    \"data\": { \"actions\": [{\"type\":\"deposit\",\"token\":\"$OTCT_UID\",\"amount\":125}], \"args\": [$ESCROW_PUBLIC] }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000001bcdbb2260b79a71fc230e3d0b524bd618fe37bd078f31dfd8d9c81aabe

### S0 settlement expectations (bps=100)
- maker fee on 100 = 1 → Bob receives 99 OTCM
- taker fee on 125 = 2 → Alice receives 123 OTCT
- protocol fees: 1 OTCM and 2 OTCT

## S0-05) Alice withdraws 123 OTCT

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "  {
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": { \"actions\": [{\"type\":\"withdrawal\",\"token\":\"$OTCT_UID\",\"amount\":123,\"address\":\"$ALICE_ADDR\"}], \"args\": [$ESCROW_PUBLIC] }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000057abcb1f065070845b413de50d58989fedca4ec1db9cb49aa5973a38c677

## S0-06) Bob withdraws 99 OTCM

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "  {
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$BOB_ADDR\",
    \"data\": { \"actions\": [{\"type\":\"withdrawal\",\"token\":\"$OTCM_UID\",\"amount\":99,\"address\":\"$BOB_ADDR\"}], \"args\": [$ESCROW_PUBLIC] }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00001d52a593894c0431cd0f9625a61b285d1e2f61820f95e3bda7f1663ed077

## S0-07) Protocol withdraws fees (1 OTCM then 2 OTCT)

Protocol Withdraw #1

```bash
curl -sS -X POST -H "X-Wallet-Id: protocol" -H "Content-Type: application/json" -d "{
  \"nc_id\": \"$CONTRACT_ID\",
  \"method\": \"withdraw\",
  \"address\": \"$PROTOCOL_ADDR\",
  \"data\": { \"actions\": [{\"type\":\"withdrawal\",\"token\":\"$OTCM_UID\",\"amount\":1,\"address\":\"$PROTOCOL_ADDR\"}], \"args\": [$ESCROW_PUBLIC] }
}" "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000276ebaddf5f5dff9b3a0dfb583c18b1a6d38babf0ef10ee832661d1301c2

Protocol Withdraw #2

```bash
curl -sS -X POST -H "X-Wallet-Id: protocol" -H "Content-Type: application/json" -d "{
  \"nc_id\": \"$CONTRACT_ID\",
  \"method\": \"withdraw\",
  \"address\": \"$PROTOCOL_ADDR\",
  \"data\": { \"actions\": [{\"type\":\"withdrawal\",\"token\":\"$OTCT_UID\",\"amount\":2,\"address\":\"$PROTOCOL_ADDR\"}], \"args\": [$ESCROW_PUBLIC] }
}" "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00003fa366816a9e721fccda7b8a44b52fbb0178ec06517fe47193160f28e906

---

# S1 — Directed Escrow Complete Lifecycle (Escrow ID 1)

```bash
export ESCROW_DIRECTED=1
```

## S1-01) Alice opens directed escrow → Bob is directed taker

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_directed\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        50,
        \"$OTCT_UID\",
        70,
        \"$BOB_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00001d4f7b4d6224716da2dcdaba973ceb581d01fd5246753490da61b9eeccfd

## S1-02) Bob accepts

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00003eae43795179b66e416a5d3a557381968fa9383044b3c5686df667fa898c

## S1-03) Alice funds maker (50 OTCM)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCM_UID\", \"amount\":50}
      ],
      \"args\": [
        $ESCROW_DIRECTED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000024111257778716567fbd1931d9f16558b227157b4b2b8c4e8c95102da7b

## S1-04) Bob funds taker (70 OTCT)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_taker\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCT_UID\", \"amount\":70}
      ],
      \"args\": [
        $ESCROW_DIRECTED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000019eb723dacd62f17860c71a4855783619919211f53f6314252f9fd88843

### S1 settlement expectations (bps=100)
- fee on 50 = 1 → Bob receives 49 OTCM
- fee on 70 = 1 → Alice receives 69 OTCT
- protocol fees: 1 OTCM and 1 OTCT

## S1-05) Withdraws

Alice withdraws 69 OTCT:

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCT_UID\", \"amount\":69, \"address\":\"$ALICE_ADDR\"}
      ],
      \"args\": [
        $ESCROW_DIRECTED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00001257cba5d43d91525f2d7033bdda4f655d2f776665456dfb95c706e38362

Bob withdraws 49 OTCM:

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCM_UID\", \"amount\":49, \"address\":\"$BOB_ADDR\"}
      ],
      \"args\": [
        $ESCROW_DIRECTED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00004f4a2801fef1214a875ec1207fe345fd7568bc9f0f7e4c45daeca3195917

Protocol withdraws 1 OTCM:

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: protocol" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$PROTOCOL_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCM_UID\", \"amount\":1, \"address\":\"$PROTOCOL_ADDR\"}
      ],
      \"args\": [
        $ESCROW_DIRECTED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```  

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00004bd150001ddfc0956b7f060722ac0760e81904d33f901e3b68af82a13814

Protocol withdraws 1 OTCT:

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: protocol" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$PROTOCOL_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCT_UID\", \"amount\":1, \"address\":\"$PROTOCOL_ADDR\"}
      ],
      \"args\": [
        $ESCROW_DIRECTED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```  

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00001e6745867634f6e452792dbb1cf30e392982272e003b49d50107a89330a7

---

# S2 — Public Escrow Cancel Before Funding (Escrow ID 2)

```bash
export ESCROW_CANCEL=2
```

## S2-01) Alice opens public escrow

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        10,
        \"$OTCT_UID\",
        20
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: 
**Test Comments**: http://localhost:3000/transaction/0000341cbaf0785c9804a5cfc8954743bad830e82d91b685bbafe28ff92917de

## S2-02) (Optional) Bob accepts

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_CANCEL
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: Processed in the same block. Looks like escrow was cancelled by Alice (via S2-03) before Bob could accept. **To do: Check actual timestamps to confirm** 
error=InvalidEscrow('Escrow ID does not exist') 


**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00002c93824e4927148105ca8c1b1befd3804c1e2a884e4438804a0296a01082" -n

9:2025-12-29 21:06:45 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow ID does not exist') tx=00002c93824e4927148105ca8c1b1befd3804c1e2a884e4438804a0296a01082
10:2025-12-29 21:06:45 [debug    ] add_voided_by                  tx=00002c93824e4927148105ca8c1b1befd3804c1e2a884e4438804a0296a01082 voided_hash=00002c93824e4927148105ca8c1b1befd3804c1e2a884e4438804a0296a01082
12:2025-12-29 21:06:45 [info     ] nano tx execution status       blk=000000196e63f8e11fc0139abb15be346d89259db29df9fdf549bc8a80391e72 execution=failure tx=00002c93824e4927148105ca8c1b1befd3804c1e2a884e4438804a0296a01082


## S2-03) Maker cancels before funding

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"cancel_before_funding\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_CANCEL
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000383303dd4228014fd7f516180ec4c64069455b0af956e2996d515822bc8d


## S2-04) Negative: Bob cancels (should void)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"cancel_before_funding\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_CANCEL
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000028dd2e0c5b0fa95d463b4cec4b9e4fdf71eb430f3174507b5d4586a9a061
error=Unauthorized('Only maker can cancel this escrow'

**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "000028dd2e0c5b0fa95d463b4cec4b9e4fdf71eb430f3174507b5d4586a9a061" -n


14:2025-12-29 21:08:10 [info     ] nc execution failed            cause=None error=Unauthorized('Only maker can cancel this escrow') tx=000028dd2e0c5b0fa95d463b4cec4b9e4fdf71eb430f3174507b5d4586a9a061
15:2025-12-29 21:08:10 [debug    ] add_voided_by                  tx=000028dd2e0c5b0fa95d463b4cec4b9e4fdf71eb430f3174507b5d4586a9a061 voided_hash=000028dd2e0c5b0fa95d463b4cec4b9e4fdf71eb430f3174507b5d4586a9a061
16:2025-12-29 21:08:10 [info     ] nano tx execution status       blk=000000231e3715e10e840dfef049f55641b2a4e4046f1086087e6685c9577972 execution=failure tx=000028dd2e0c5b0fa95d463b4cec4b9e4fdf71eb430f3174507b5d4586a9a061

## S2-05) Negative: Alice tries to fund after cancel (should void)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCM_UID\", \"amount\":10}
      ],
      \"args\": [
        $ESCROW_CANCEL
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000001986120a2553ac2f774e368521ed1eef21ef05880e62c1fa8275fc114ca
error=InvalidEscrow('Escrow has been cancelled')

**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "000001986120a2553ac2f774e368521ed1eef21ef05880e62c1fa8275fc114ca" -n

17:2025-12-29 21:08:28 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow has been cancelled') tx=000001986120a2553ac2f774e368521ed1eef21ef05880e62c1fa8275fc114ca

---

# S3 — Public Escrow Both Funded (verify refund blocked; settle) (Escrow ID 3)

```bash
export ESCROW_BOTH_FUNDED=3
```

## S3-01) Open + accept + fund both quickly

### 1) Alice opens public escrow

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        20,
        \"$OTCT_UID\",
        30
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00004e9e0697178c0c13372cee35a47178a761bd2ac80ad934936d61cf6b801b

### 2) Bob accepts

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_BOTH_FUNDED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000424d0635c581f85fbf6092362b363c03b3eca5e24e7c8cc55d6f51476dd2

### 3) Alice funds maker (20 OTCM)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCM_UID\", \"amount\":20}
      ],
      \"args\": [
        $ESCROW_BOTH_FUNDED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000001544797136977ec4a9717a46070f68c3363b46a773014b176ef0663bb81

### 4) Bob funds taker (30 OTCT)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_taker\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCT_UID\", \"amount\":30}
      ],
      \"args\": [
        $ESCROW_BOTH_FUNDED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000000489ff92870694804dd36740d53e81cb13df504555e4e3eb991bd7feb4c

---

## S3-02) Negative: refund before expiry (should void)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"refund\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCM_UID\", \"amount\":20, \"address\":\"$ALICE_ADDR\"}
      ],
      \"args\": [
        $ESCROW_BOTH_FUNDED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000021e7b6ba728e126ea309a2d0016a05c4f04da38d0af6a906a6f180b8337a
error=InvalidEscrow('Escrow has not expired') 


**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "000021e7b6ba728e126ea309a2d0016a05c4f04da38d0af6a906a6f180b8337a" -n

25:2025-12-29 21:27:23 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow has not expired') tx=000021e7b6ba728e126ea309a2d0016a05c4f04da38d0af6a906a6f180b8337a
26:2025-12-29 21:27:23 [debug    ] add_voided_by                  tx=000021e7b6ba728e126ea309a2d0016a05c4f04da38d0af6a906a6f180b8337a voided_hash=000021e7b6ba728e126ea309a2d0016a05c4f04da38d0af6a906a6f180b8337a
27:2025-12-29 21:27:23 [info     ] nano tx execution status       blk=0000000b9a5cd3b542206597a17d4cc5a0281bc96881aae34d1f426269584e69 execution=failure tx=000021e7b6ba728e126ea309a2d0016a05c4f04da38d0af6a906a6f180b8337a

---

## S3-03) Use get_fee_quote then withdraw net amounts + protocol fees


```bash
curl -sS -X GET \
  -H "X-Wallet-Id: alice" \
  "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_fee_quote(20,30)" | jq
```

**Test Result**: Pass
**Test Comments**: Calculation helper.
The call is, “If an escrow swaps 20 OTCM for 30 OTCT, what are the protocol fees and net payouts?”



{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_fee_quote(20,30)": {
        "value": [
          1,
          1,
          29,
          19
        ]
      }
    }
  }
}


Fee quote view matched expeted results:

FeeQuoteView(
  maker_fee,
  taker_fee,
  maker_net_receive,
  taker_net_receive
)


## S3-04) Withdraws

Alice withdraws 29 OTCT:

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCT_UID\", \"amount\":29, \"address\":\"$ALICE_ADDR\"}
      ],
      \"args\": [
        $ESCROW_BOTH_FUNDED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00002011ba2b63929d70dbd474b6d72488f0322759a194c381bfaebf06c9722e

Bob withdraws 19 OTCM:

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCM_UID\", \"amount\":19, \"address\":\"$BOB_ADDR\"}
      ],
      \"args\": [
        $ESCROW_BOTH_FUNDED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000019325e95620e3411093652093ace668f593e7104ce4cba0438a5642608ef

Protocol withdraws 1 OTCM:

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: protocol" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$PROTOCOL_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCM_UID\", \"amount\":1, \"address\":\"$PROTOCOL_ADDR\"}
      ],
      \"args\": [
        $ESCROW_BOTH_FUNDED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```  

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00002b4d8acfda68b3af3f25a091c3424e22c7c55fed9e84ee7e8906c62aa478

Protocol withdraws 1 OTCT:

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: protocol" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"withdraw\",
    \"address\": \"$PROTOCOL_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCT_UID\", \"amount\":1, \"address\":\"$PROTOCOL_ADDR\"}
      ],
      \"args\": [
        $ESCROW_BOTH_FUNDED
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```  

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00003b458c3ed922e84a6f45054e6973c81ee2c22b57e099e9599389500136c9

---

***# S4 — Public Escrow Expires Before Accept (Escrow ID 4)***

```bash
export ESCROW_EXPIRE_OPEN=4
```

## S4-01) Open with short expiry and wait

# Set an expiry ~120 seconds from now (adjust if needed)

```bash
EXP_TS=$(( $(date +%s) + 120 ))
```

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_with_expiry\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        11,
        \"$OTCT_UID\",
        22,
        $EXP_TS
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

```
sleep 120
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00002019d6318d8efdba71b53190a8659161f61b5cb25855a3e3e0eb1733333d




First two runs were flagging Expiry timestamp is below min_expiry_secs from now. Need to increase EXP_TS to 120 for 3rd try.

docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00004ca8e46e9ec9bf469bed612fde5c9847011a4b2154d59edd8a9d97631aa1" -n

20:2025-12-29 21:47:12 [info     ] nc execution failed            cause=None error=InvalidConfig('Expiry timestamp is below min_expiry_secs from now') tx=00004ca8e46e9ec9bf469bed612fde5c9847011a4b2154d59edd8a9d97631aa1
21:2025-12-29 21:47:12 [debug    ] add_voided_by                  tx=00004ca8e46e9ec9bf469bed612fde5c9847011a4b2154d59edd8a9d97631aa1 voided_hash=00004ca8e46e9ec9bf469bed612fde5c9847011a4b2154d59edd8a9d97631aa1
22:2025-12-29 21:47:12 [info     ] nano tx execution status       blk=000000020b96ffc998a0941a2c92e332f060f51ae892d206a67a0230093970af execution=failure tx=00004ca8e46e9ec9bf469bed612fde5c9847011a4b2154d59edd8a9d97631aa1

docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00004214988d8d27ce58a3e508a3cfbe8a94c344dc68d883582fbf0e0fa5f20e" -n

17:2025-12-29 21:44:17 [info     ] nc execution failed            cause=None error=InvalidConfig('Expiry timestamp is below min_expiry_secs from now') tx=00004214988d8d27ce58a3e508a3cfbe8a94c344dc68d883582fbf0e0fa5f20e
18:2025-12-29 21:44:17 [debug    ] add_voided_by                  tx=00004214988d8d27ce58a3e508a3cfbe8a94c344dc68d883582fbf0e0fa5f20e voided_hash=00004214988d8d27ce58a3e508a3cfbe8a94c344dc68d883582fbf0e0fa5f20e
19:2025-12-29 21:44:17 [info     ] nano tx execution status       blk=00000007fa2bf04c51555e9410fdc505fa42977c94d56fb64efb2af497d53d39 execution=failure tx=00004214988d8d27ce58a3e508a3cfbe8a94c344dc68d883582fbf0e0fa5f20e


## S4-02) Accept should fail (expired)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_EXPIRE_OPEN
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: error=InvalidEscrow('Escrow has expired')
http://localhost:3000/transaction/00006cfad45fdcf62486bfe4f1bfbaa3f7675c260363ab496887e14ec8187a12

**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00006cfad45fdcf62486bfe4f1bfbaa3f7675c260363ab496887e14ec8187a12" -n

24:2025-12-29 21:52:56 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow has expired') tx=00006cfad45fdcf62486bfe4f1bfbaa3f7675c260363ab496887e14ec8187a12
25:2025-12-29 21:52:56 [debug    ] add_voided_by                  tx=00006cfad45fdcf62486bfe4f1bfbaa3f7675c260363ab496887e14ec8187a12 voided_hash=00006cfad45fdcf62486bfe4f1bfbaa3f7675c260363ab496887e14ec8187a12
26:2025-12-29 21:52:56 [info     ] nano tx execution status       blk=0000002c83754067d9a497731fc36c7a8e9e89526fe467688607e848777c411c execution=failure tx=00006cfad45fdcf62486bfe4f1bfbaa3f7675c260363ab496887e14ec8187a12



## S4-03) View expiry flags

```bash
NOW_TS=$(date +%s)
curl -sS -X GET -H "X-Wallet-Id: alice"   "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_escrow_full($ESCROW_EXPIRE_OPEN,$NOW_TS)" | jq
```

**Test Result**: Pass
**Test Comments**: Expected Results

now = 1767045232
open expirty timestamp = 1767045077
is open_expired? true 


{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_escrow_full(4,1767045232)": {
        "value": [
          "WcAccYo8pMZLVJ573KmSHGacKDUeCaYtki",
          "",
          "0000031457b791e84a317eb3200eaad492e9f95e42cad5edf3979abb2f50a74f",
          11,
          "00000118eafe46ee390d5655f03651b9e8be7c34f76a810b4086a2d845faf5f6",
          22,
          false,
          false,
          false,
          false,
          false,
          false,
          1767045077, #open expiry timestamp 
          0,
          true,           # is open expired?
          false,
          true,
          false,
          "",
          false,
          false,
          0
        ]
      }
    }
  }
}

---

***# S5 — Public Escrow Expires After Accept (Escrow ID 5)***

```bash
export ESCROW_EXPIRE_AFTER_ACCEPT=5
```

## S5-01) Open short expiry; accept; wait; funding blocked

# Set an expiry ~240 seconds from now (adjust if needed)

```bash
EXP_TS=$(( $(date +%s) + 240 ))
```

# 1) Alice opens escrow with short expiry


```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_with_expiry\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        13,
        \"$OTCT_UID\",
        17,
        $EXP_TS
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000193c8360fdf0fa02ff5da59b309c87fad4d974fefa0e34891cd8f1dd799c

# 2) Bob accepts

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_EXPIRE_AFTER_ACCEPT
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000000fc1ff6662a8a539a7895a8e1f9e680b1d3f3027e2e4aef9cdb70656db7


```bash
sleep 240
```

## S5-02) fund_maker should fail (expired)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCM_UID\", \"amount\":13}
      ],
      \"args\": [
        $ESCROW_EXPIRE_AFTER_ACCEPT
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: error=InvalidEscrow('Escrow has expired')
http://localhost:3000/transaction/000000b9765895eaeeb01dd1bc12a0b31a472fe13d3e97bc4234035951ab0fab

**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "000000b9765895eaeeb01dd1bc12a0b31a472fe13d3e97bc4234035951ab0fab" -n

13:2025-12-29 22:09:13 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow has expired') tx=000000b9765895eaeeb01dd1bc12a0b31a472fe13d3e97bc4234035951ab0fab
14:2025-12-29 22:09:13 [debug    ] add_voided_by                  tx=000000b9765895eaeeb01dd1bc12a0b31a472fe13d3e97bc4234035951ab0fab voided_hash=000000b9765895eaeeb01dd1bc12a0b31a472fe13d3e97bc4234035951ab0fab
15:2025-12-29 22:09:13 [info     ] nano tx execution status       blk=0000003141cb3b87a5811a10d1cd8fc4a040d20cc629c7f1fe6dbb180845d6f3 execution=failure tx=000000b9765895eaeeb01dd1bc12a0b31a472fe13d3e97bc4234035951ab0fab

---

***# S6 — Maker Funded Only then Expires (Refund) (Escrow ID 6)***

***This scenario is fully retested fully under S13.***
Retest required because of Localnet environment timing issues / set expiry timestamps.
Not a contract issue. 


```bash
export ESCROW_MAKER_FUNDED_EXPIRE=6
```

## S6-01) Open + accept + maker funds; wait for maker-funded expiry

# 1) Alice opens public escrow

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        21,
        \"$OTCT_UID\",
        22
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00000a933edc677b031a30a24b981545bd556d8823fe76a95549f4283da647d6


# 2) Bob accepts

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_MAKER_FUNDED_EXPIRE
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000040a852f2381267ed535b38c78e8a85896bde58bc9081de14804af4943cbe

# 3) Alice funds maker (21 OTCM)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCM_UID\", \"amount\":21}
      ],
      \"args\": [
        $ESCROW_MAKER_FUNDED_EXPIRE
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000015b073b31d169bce53fbe733985b4630b3a7db6b6f949585eed1b01b466


# Wait for maker-funded expiry window to pass

```
sleep 70
```

## S6-02) taker funding should fail

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_taker\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCT_UID\", \"amount\":22}
      ],
      \"args\": [
        $ESCROW_MAKER_FUNDED_EXPIRE
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**: Need to Retest last. Was using the wrong expiry timestamps. default_maker_funded_expiry_secs = 240 not 70.
So a delta of 169 was allowed to go through. Will retest again.
Failed, Funding went through. 
**Test Comments**: http://localhost:3000/transaction/000002337e33d9a06ad0ab8f6d6ad2e240439b44031dcc04dca94e7743fb33a6

**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "000002337e33d9a06ad0ab8f6d6ad2e240439b44031dcc04dca94e7743fb33a6" -n



>   "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_escrow_full($ESCROW_MAKER_FUNDED_EXPIRE,$NOW_TS)" | jq

now = 1767047674
open_expiry_timestamp = 1767047463
maker_funded_expiry_timestamp =1767047103
status = 3 (both funded)

{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_escrow_full(6,1767047674)": {
        "value": [
          "WcAccYo8pMZLVJ573KmSHGacKDUeCaYtki",
          "WT7mEwUW8kaky27PjLbpwzbTZ2sTxw1pbd",
          "0000031457b791e84a317eb3200eaad492e9f95e42cad5edf3979abb2f50a74f",
          21,
          "00000118eafe46ee390d5655f03651b9e8be7c34f76a810b4086a2d845faf5f6",
          22,
          true,
          true,
          false,
          false,
          false,
          false,
          1767047463,
          1767047103,
          true,
          true,
          false,
          false,
          "",
          false,
          false,
          3
        ]
      }
    }
  }
}

MAKER_FUND_TXID = 0000015b073b31d169bce53fbe733985b4630b3a7db6b6f949585eed1b01b466

curl -s "http://localhost:8080/v1a/transaction?id=0000015b073b31d169bce53fbe733985b4630b3a7db6b6f949585eed1b01b466" | jq '.timestamp'

root@DESKTOP:~/dev/hathor-blueprints# curl -s "http://localhost:8080/v1a/transaction?id=0000015b073b31d169bce53fbe733985b4630b3a7db6b6f949585eed1b01b466" \
>   | jq '.tx.timestamp'
1767046815
root@DESKTOP:~/dev/hathor-blueprints# curl -s "http://localhost:8080/v1a/transaction?id=000002337e33d9a06ad0ab8f6d6ad2e240439b44031dcc04dca94e7743fb33a6" \
>   | jq '.tx.timestamp'
1767046984
root@DESKTOP:~/dev/hathor-blueprints# MAKER_TS=$(curl -s "http://localhost:8080/v1a/transaction?id=0000015b073b31d169bce53fbe733985b4630b3a7db6b6f949585eed1b01b466" | jq -r '.tx.timestamp')
AKER_TS-MAKER_TS))"
root@DESKTOP:~/dev/hathor-blueprints# TAKER_TS=$(curl -s "http://localhost:8080/v1a/transaction?id=000002337e33d9a06ad0ab8f6d6ad2e240439b44031dcc04dca94e7743fb33a6" | jq -r '.tx.timestamp')
root@DESKTOP:~/dev/hathor-blueprints# echo "maker=$MAKER_TS taker=$TAKER_TS delta=$((TAKER_TS-MAKER_TS))"
maker=1767046815 taker=1767046984 


delta=169


What the numbers prove

Maker fund tx timestamp: 1767046815

Taker fund tx timestamp: 1767046984

Delta: 169 seconds

So by chain/tx time, taker funded 169s after maker funded, which is well past the configured maker-funded expiry of 60s.

Therefore, taker funding should have been blocked (voided) in STATUS_FUNDED_MAKER once the maker-funded expiry passed.

So this is a real bug / missing guard, not localnet time weirdness.



>   "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_config()" | jq
{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_config()": {
        "value": [
          "WgBEype81huhwQRf617jj1846gB4yrWzts",
          "WgBEype81huhwQRf617jj1846gB4yrWzts",
          100,
          600,
          240,
          60,
          86400
        ]
      }
    }
  }
}


returned tuple is:
owner = WgBE...
fee_recipient = WgBE...
protocol_fee_bps = 100
default_open_expiry_secs = 600
default_maker_funded_expiry_secs = 240
min_expiry_secs = 60
max_expiry_secs = 86400



## S6-03) maker refunds 21 OTCM

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"refund\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCM_UID\", \"amount\":21, \"address\":\"$ALICE_ADDR\"}
      ],
      \"args\": [
        $ESCROW_MAKER_FUNDED_EXPIRE
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**:  N/A - Retest Scenario w/ S15
**Test Comments**: N/A - Retest Scenario w/ S15

---

***# S7 — Directed: Wrong Taker Cannot Accept (Escrow ID 7)***

***This scenario is fully retested fully under S14.***
Retest required because of Localnet environment timing issues / set expiry timestamps.
Not a contract issue. 


```bash
export ESCROW_DIRECTED_WRONG_ACCEPT=7
```

S7-01) Alice opens a directed escrow (directed taker = Bob)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_directed\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        10,
        \"$OTCT_UID\",
        20,
        \"$BOB_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**:  
**Test Comments**: http://localhost:3000/transaction/0000115c563906eb6569b8d202683995499ccb4100e378c7854e81cfe6806afa


S7-02) Negative: Genesis tries to accept (should void / Unauthorized)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: genesis" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$GENESIS_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_WRONG_ACCEPT
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**:  Pass? Escrow ID doesnt exist? Should be unauthorized. May need to retest. 
**Test Comments**: http://localhost:3000/transaction/000082db52d2b4a17902fe340b78733c195068d9cfb1a76f59e1acaa3070a32a

**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "000082db52d2b4a17902fe340b78733c195068d9cfb1a76f59e1acaa3070a32a" -n


1:2025-12-29 23:39:34 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow ID does not exist') tx=000082db52d2b4a17902fe340b78733c195068d9cfb1a76f59e1acaa3070a32a
2:2025-12-29 23:39:34 [debug    ] add_voided_by                  tx=000082db52d2b4a17902fe340b78733c195068d9cfb1a76f59e1acaa3070a32a voided_hash=000082db52d2b4a17902fe340b78733c195068d9cfb1a76f59e1acaa3070a32a
3:2025-12-29 23:39:34 [info     ] nano tx execution status       blk=0000000261f2c14c97e132f71d8ede5d8cc25557dc69eb41f942f3bbfd03e836 execution=failure tx=000082db52d2b4a17902fe340b78733c195068d9cfb1a76f59e1acaa3070a32a


S7-03) Bob accepts (should succeed)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_WRONG_ACCEPT
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**:  Pass
**Test Comments**: http://localhost:3000/transaction/00003eb6ebefb925950d03bfdec417cddd1c75ad00676ded4c80941a5399ee8f

---

***# S8 — Directed: Wrong Taker Cannot Fund (Escrow ID 8)***

```bash
export ESCROW_DIRECTED_WRONG_FUND=8
```


S8-01) Maker opens directed escrow

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d '{
    "nc_id": "'"$CONTRACT_ID"'",
    "method": "open_escrow_directed",
    "address": "'"$ALICE_ADDR"'",
    "data": {
      "actions": [],
      "args": [
        "'"$OTCM_UID"'",
        12,
        "'"$OTCT_UID"'",
        34,
        "'"$BOB_ADDR"'"
      ]
    }
  }' \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**:  Pass
**Test Comments**: http://localhost:3000/transaction/0000287749141a71446f0e1534fa87bef7776c3bfd9bbda0179b69032d2af168


S8-02) Bob accepts (correct directed taker)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d '{
    "nc_id": "'"$CONTRACT_ID"'",
    "method": "accept_escrow",
    "address": "'"$BOB_ADDR"'",
    "data": {
      "actions": [],
      "args": ['"$ESCROW_DIRECTED_WRONG_FUND"']
    }
  }' \
  "$WALLET/wallet/nano-contracts/execute" | jq
```




**Test Result**:  Pass
**Test Comments**: http://localhost:3000/transaction/0000629d188d8f7906b304fb7bfff7ff52d89f1bae7e194b2c62ad16129fb8a2



S8-03) Maker funds

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d '{
    "nc_id": "'"$CONTRACT_ID"'",
    "method": "fund_maker",
    "address": "'"$ALICE_ADDR"'",
    "data": {
      "actions": [
        {
          "type": "deposit",
          "token": "'"$OTCM_UID"'",
          "amount": 12
        }
      ],
      "args": ['"$ESCROW_DIRECTED_WRONG_FUND"']
    }
  }' \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**:  Pass
**Test Comments**: http://localhost:3000/transaction/000000818feeb7d6308bd316459cbe7fbc4215c0c8bf15f84474361546bf8fa8


S8-04) Genesis tries to fund taker side → SHOULD FAIL

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: genesis" \
  -H "Content-Type: application/json" \
  -d '{
    "nc_id": "'"$CONTRACT_ID"'",
    "method": "fund_taker",
    "address": "'"$GENESIS_ADDR"'",
    "data": {
      "actions": [
        {
          "type": "deposit",
          "token": "'"$OTCT_UID"'",
          "amount": 34
        }
      ],
      "args": ['"$ESCROW_DIRECTED_WRONG_FUND"']
    }
  }' \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**: Pass
**Test Comments**: error=Unauthorized('Only the directed taker can fund taker side') 
http://localhost:3000/transaction/000006ba7e8ec1c4e2c03ee8252ade61723d39fa069a9a17887cc10e9e604f99

**Test Logs**: 
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "000006ba7e8ec1c4e2c03ee8252ade61723d39fa069a9a17887cc10e9e604f99" -n


9:2025-12-29 23:53:42 [info     ] nc execution failed            cause=None error=Unauthorized('Only the directed taker can fund taker side') tx=000006ba7e8ec1c4e2c03ee8252ade61723d39fa069a9a17887cc10e9e604f99
10:2025-12-29 23:53:42 [debug    ] add_voided_by                  tx=000006ba7e8ec1c4e2c03ee8252ade61723d39fa069a9a17887cc10e9e604f99 voided_hash=000006ba7e8ec1c4e2c03ee8252ade61723d39fa069a9a17887cc10e9e604f99
12:2025-12-29 23:53:42 [info     ] nano tx execution status       blk=00000027f042c8240800babe4828578dd031df0bb4f270418c09ecb63a823677 execution=failure tx=000006ba7e8ec1c4e2c03ee8252ade61723d39fa069a9a17887cc10e9e604f99


S8-05) Correct taker (Bob) funds → SHOULD PASS

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d '{
    "nc_id": "'"$CONTRACT_ID"'",
    "method": "fund_taker",
    "address": "'"$BOB_ADDR"'",
    "data": {
      "actions": [
        {
          "type": "deposit",
          "token": "'"$OTCT_UID"'",
          "amount": 34
        }
      ],
      "args": ['"$ESCROW_DIRECTED_WRONG_FUND"']
    }
  }' \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**:  Pass
**Test Comments**: http://localhost:3000/transaction/000002aafa8bd552a403f2f4e76e4dedf80db32992db4c3dc03af03ef7aa636e


---

***# S9 — Directed: Maker Retargets Directed Taker (OPEN only) (Escrow ID 9)***

***This scenario is fully retested fully under S15.***
Retest required because of Localnet environment timing issues / set expiry timestamps.
Not a contract issue. 

```bash
export ESCROW_DIRECTED_RETARGET=9
```

S9-01) Alice opens directed escrow (initial directed taker = Bob)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_directed\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        9,
        \"$OTCT_UID\",
        9,
        \"$BOB_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: 
**Test Comments**: http://localhost:3000/transaction/00004e827e0fe427e6a77235a437507affb1eda60105950b4f778713c1273452


S9-02) Alice retargets directed taker to Genesis (OPEN only)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"set_directed_taker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_RETARGET,
        \"$GENESIS_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: N/A needs retest. Accept and Set Taker were in the same block. 
InvalidEscrow('Directed taker can only be updated while escrow is OPEN'
**Test Comments**: http://localhost:3000/transaction/0000478844df90637ff8cef7dbb2f9c37f671d794294e105516036fd80686534

**Test Logs**
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "0000478844df90637ff8cef7dbb2f9c37f671d794294e105516036fd80686534" -n

16:2025-12-30 00:02:12 [info     ] nc execution failed            cause=None error=InvalidEscrow('Directed taker can only be updated while escrow is OPEN') tx=0000478844df90637ff8cef7dbb2f9c37f671d794294e105516036fd80686534
17:2025-12-30 00:02:12 [debug    ] add_voided_by                  tx=0000478844df90637ff8cef7dbb2f9c37f671d794294e105516036fd80686534 voided_hash=0000478844df90637ff8cef7dbb2f9c37f671d794294e105516036fd80686534
20:2025-12-30 00:02:12 [info     ] nano tx execution status       blk=0000003929a3b994e9eddf0d3125010ceba59742159c78839f29b8d83dc2d86c execution=failure tx=0000478844df90637ff8cef7dbb2f9c37f671d794294e105516036fd80686534


S9-03) Negative: Bob tries to accept (should fail)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_RETARGET
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: N/A Needs retest
**Test Comments**: N


S9-04) Genesis accepts (should succeed)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: genesis" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$GENESIS_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_RETARGET
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: 
**Test Comments**: 



---

**# S10 — Directed: set_directed_taker Negative Tests (Escrow ID 10)**

```bash
export ESCROW_DIRECTED_NEG=10
```

S10-01) Alice opens directed escrow (initial directed taker = Bob)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_directed\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        9,
        \"$OTCT_UID\",
        9,
        \"$BOB_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00000c8ecc94079830c830cc30fc1ec940cdaa4ee3005463da319f8bf80864e7


S10-02) Negative: Bob tries to retarget directed taker (should fail)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"set_directed_taker\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_NEG,
        \"$GENESIS_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: error=Unauthorized('Only maker can update directed taker')
http://localhost:3000/transaction/00001cd3238c643164b20b7b2a80eac138c8d3e6e6f6d7f94d591310841fd465

**Test Logs**
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00001cd3238c643164b20b7b2a80eac138c8d3e6e6f6d7f94d591310841fd465" -n

17:2025-12-30 00:15:32 [info     ] nc execution failed            cause=None error=Unauthorized('Only maker can update directed taker') tx=00001cd3238c643164b20b7b2a80eac138c8d3e6e6f6d7f94d591310841fd465
18:2025-12-30 00:15:32 [debug    ] add_voided_by                  tx=00001cd3238c643164b20b7b2a80eac138c8d3e6e6f6d7f94d591310841fd465 voided_hash=00001cd3238c643164b20b7b2a80eac138c8d3e6e6f6d7f94d591310841fd465
20:2025-12-30 00:15:32 [info     ] nano tx execution status       blk=0000000423fd281fcffcd6ac78fad225320f41d795088c1a8a273cbd6d14853c execution=failure tx=00001cd3238c643164b20b7b2a80eac138c8d3e6e6f6d7f94d591310841fd465


S10-03) Bob accepts escrow (should succeed)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_NEG
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00006aba935c6bee36aabc76308e662eb2e8e7da90a76e3e18bf52563dc23f86


S10-04) Negative: Alice tries to retarget after accept (should fail; OPEN only)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"set_directed_taker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_NEG,
        \"$GENESIS_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: error=InvalidEscrow('Directed taker can only be updated while escrow is OPEN')
http://localhost:3000/transaction/00002cc83e8a66616fa56717f7652fea29c7f89f4bfea999156548cd6ed7f90d


**Test Logs**
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00002cc83e8a66616fa56717f7652fea29c7f89f4bfea999156548cd6ed7f90d" -n


21:2025-12-30 00:15:48 [info     ] nc execution failed            cause=None error=InvalidEscrow('Directed taker can only be updated while escrow is OPEN') tx=00002cc83e8a66616fa56717f7652fea29c7f89f4bfea999156548cd6ed7f90d
22:2025-12-30 00:15:48 [debug    ] add_voided_by                  tx=00002cc83e8a66616fa56717f7652fea29c7f89f4bfea999156548cd6ed7f90d voided_hash=00002cc83e8a66616fa56717f7652fea29c7f89f4bfea999156548cd6ed7f90d
23:2025-12-30 00:15:48 [info     ] nano tx execution status       blk=00000015f41da6d085921e52e52f0f2b0a835a3e959f53225b4526802c52aef8 execution=failure tx=00002cc83e8a66616fa56717f7652fea29c7f89f4bfea999156548cd6ed7f90d

---

***# S11 — Directed: Expires After Accept, Cannot Fund (Escrow ID 11)***

***This scenario is fully retested fully under S16.***
Retest required because of Localnet environment timing issues / set expiry timestamps.
Not a contract issue.

```bash
export ESCROW_DIRECTED_EXPIRE_ACCEPT=11
```


# Set an expiry ~120 seconds from now (adjust if needed)

```bash
EXP_TS=$(( $(date +%s) + 120 ))
```


S11-01) Alice opens directed escrow with short open-expiry


```bash
EXP_TS=$(( $(date +%s) + 120 ))

curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_directed_with_expiry\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        14,
        \"$OTCT_UID\",
        15,
        $EXP_TS,
        \"$BOB_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000491d20df96feb1b0ab5eeb3b72d363711da57305c0b184c2275a1da59ef0



S11-02) Bob accepts (should succeed before expiry

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_EXPIRE_ACCEPT
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```



**Test Result**: Need a retest. Tried to accept before Escrow tx was confirmed. 
**Test Comments**: error=InvalidEscrow('Escrow ID does not exist')
http://localhost:3000/transaction/0000493d87a884d2c609b4c6bf84ac6b37387ce9f4807ea94f97088054605192

**Test Logs**
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "0000493d87a884d2c609b4c6bf84ac6b37387ce9f4807ea94f97088054605192" -n


9:2025-12-30 00:40:17 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow ID does not exist') tx=0000493d87a884d2c609b4c6bf84ac6b37387ce9f4807ea94f97088054605192
10:2025-12-30 00:40:17 [debug    ] add_voided_by                  tx=0000493d87a884d2c609b4c6bf84ac6b37387ce9f4807ea94f97088054605192 voided_hash=0000493d87a884d2c609b4c6bf84ac6b37387ce9f4807ea94f97088054605192
11:2025-12-30 00:40:17 [info     ] nano tx execution status       blk=0000002999e05cc173561700add9b7e782c692b7f0dd779bc820b29933f8f8c8 execution=failure tx


```
sleep 120
```

S11-04) Alice tries to fund maker (should fail: expired)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCM_UID\", \"amount\":14}
      ],
      \"args\": [
        $ESCROW_DIRECTED_EXPIRE_ACCEPT
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

---

***# S12 — Directed + Expiry + Refund (Maker Funded then Expires) (Escrow ID 12)***


```bash
export ESCROW_DIRECTED_REFUND=12
```

### **S12-01) Alice opens directed escrow (directed taker = Bob)**

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_directed\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        16,
        \"$OTCT_UID\",
        18,
        \"$BOB_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00000745b8ebe32eea137b6a4ff29bdd980cf05f0b2f6c4094cf3e19bba2af06


### **S12-02) Bob accepts**

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_REFUND
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00000b16ccfd4d4816e378a9e4026ff3c44c4edac34896d1c9d7c2eae7316ef7


### **S12-03) Alice funds maker (16 OTCM)**

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCM_UID\", \"amount\":16}
      ],
      \"args\": [
        $ESCROW_DIRECTED_REFUND
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000002c34879112d7d7a5c3f5ba1220df1dcb9fbedbc2ce1309489e44395aeef


### Wait until maker-funded expiry passes**

```bash
sleep 270
```

### **S12-04) Negative: Bob tries to fund taker (should fail: expired)**

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_taker\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCT_UID\", \"amount\":18}
      ],
      \"args\": [
        $ESCROW_DIRECTED_REFUND
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**: Pass
**Test Comments**: error=InvalidEscrow('Escrow has expired')
http://localhost:3000/transaction/000000ad8e492503a6b2d63c984aa3c933319b1b88b4cae4a9525b65a1f166b9


**Test Logs**
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "000000ad8e492503a6b2d63c984aa3c933319b1b88b4cae4a9525b65a1f166b9" -n

14:2025-12-30 00:59:25 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow has expired') tx=000000ad8e492503a6b2d63c984aa3c933319b1b88b4cae4a9525b65a1f166b9
15:2025-12-30 00:59:25 [debug    ] add_voided_by                  tx=000000ad8e492503a6b2d63c984aa3c933319b1b88b4cae4a9525b65a1f166b9 voided_hash=000000ad8e492503a6b2d63c984aa3c933319b1b88b4cae4a9525b65a1f166b9
16:2025-12-30 00:59:25 [info     ] nano tx execution status       blk=0000000853ccac0401e8c5fe62155573f096155c4a6cbb2add50d1e0e0e80216 execution=failure tx=000000ad8e492503a6b2d63c984aa3c933319b1b88b4cae4a9525b65a1f166b9


### **S12-05) Alice refunds maker deposit (16 OTCM)**

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"refund\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCM_UID\", \"amount\":16, \"address\":\"$ALICE_ADDR\"}
      ],
      \"args\": [
        $ESCROW_DIRECTED_REFUND
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00002ee6318d6becfb27a177b729522e73148c34d653d7646d74d4705261544d


---



----------------------------------------------------------------------------------------------------

***# S13 — Retest of S5- Maker Funded Only then Expires (Refund) (Escrow ID 13)***

```bash
export ESCROW_MAKER_FUNDED_EXPIRE_RETEST=13
```

## S13-01) Open + accept + maker funds; wait for maker-funded expiry

# 1) Alice opens public escrow

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        21,
        \"$OTCT_UID\",
        22
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00003bdc416da8302f517bacafaf86b854577ded0e45acc96d8affb59144fb40


# 2) Bob accepts

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_MAKER_FUNDED_EXPIRE_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00006c699f4e1952f2000411a9456fcd5e3c0082f08d61b08d102362e7aed3b2

# 3) Alice funds maker (21 OTCM)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCM_UID\", \"amount\":21}
      ],
      \"args\": [
        $ESCROW_MAKER_FUNDED_EXPIRE_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000034772ecc32a1dd56f7909d30642e9a4beee54cf7a110cb387754b77d8b8


# Wait for maker-funded expiry window to pass

```
sleep 260
```

## S13-02) taker funding should fail

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_taker\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCT_UID\", \"amount\":22}
      ],
      \"args\": [
        $ESCROW_MAKER_FUNDED_EXPIRE_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**: Pass
**Test Comments**: error=InvalidEscrow('Escrow has expired')
http://localhost:3000/transaction/000001b1703af46ef5ca01394a3da5175a6f556cf627bbdb9a2cec352a2e0a16

**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "000001b1703af46ef5ca01394a3da5175a6f556cf627bbdb9a2cec352a2e0a16" -n


26:2025-12-30 01:09:40 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow has expired') tx=000001b1703af46ef5ca01394a3da5175a6f556cf627bbdb9a2cec352a2e0a16
27:2025-12-30 01:09:40 [debug    ] add_voided_by                  tx=000001b1703af46ef5ca01394a3da5175a6f556cf627bbdb9a2cec352a2e0a16 voided_hash=000001b1703af46ef5ca01394a3da5175a6f556cf627bbdb9a2cec352a2e0a16
28:2025-12-30 01:09:40 [debug    ] tx.mark_as_voided              tx=000001b1703af46ef5ca01394a3da5175a6f556cf627bbdb9a2cec352a2e0a16
29:2025-12-30 01:09:40 [info     ] nano tx execution status       blk=00000017fe042a265eb1159118b2e3e460c1df54f521c3258701c3440591bfcc execution=failure tx=000001b1703af46ef5ca01394a3da5175a6f556cf627bbdb9a2cec352a2e0a16


## S13-03) maker refunds 21 OTCM

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"refund\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"withdrawal\", \"token\":\"$OTCM_UID\", \"amount\":21, \"address\":\"$ALICE_ADDR\"}
      ],
      \"args\": [
        $ESCROW_MAKER_FUNDED_EXPIRE_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000003349fcd2ed0265c4ecbb664af19e30f0a1f6b2001526c8adf76edf74d69

---


***# S14 - RETEST OF S7 — Directed: Wrong Taker Cannot Accept (Escrow ID 7)***

```bash
export ESCROW_DIRECTED_WRONG_ACCEPT_RETEST=14
```

S7-01) Alice opens a directed escrow (directed taker = Bob)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_directed\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        10,
        \"$OTCT_UID\",
        20,
        \"$BOB_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**:  Pass
**Test Comments**: http://localhost:3000/transaction/00003b7b43b74b7ff00aed2f940052b88050aafa7cc74782cbeca7450aaf2c25


S14-02) Negative: Genesis tries to accept (should void / Unauthorized)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: genesis" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$GENESIS_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_WRONG_ACCEPT_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**:  Pass
**Test Comments**: error=Unauthorized('Only the directed taker can accept this escrow')
http://localhost:3000/transaction/00005a6921696ddf68da3272f245d05d7895a8eadf8016154a51d1b5a051b11e

**Test Logs**:
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00005a6921696ddf68da3272f245d05d7895a8eadf8016154a51d1b5a051b11e" -n


25:2025-12-30 01:13:48 [info     ] nc execution failed            cause=None error=Unauthorized('Only the directed taker can accept this escrow') tx=00005a6921696ddf68da3272f245d05d7895a8eadf8016154a51d1b5a051b11e
26:2025-12-30 01:13:48 [debug    ] add_voided_by                  tx=00005a6921696ddf68da3272f245d05d7895a8eadf8016154a51d1b5a051b11e voided_hash=00005a6921696ddf68da3272f245d05d7895a8eadf8016154a51d1b5a051b11e
27:2025-12-30 01:13:48 [info     ] nano tx execution status       blk=00000014648a82cd4ff0b84a1cadbd8aa9dcbf4b6b3ed87cba606bbc992628b3 execution=failure tx=00005a6921696ddf68da3272f245d05d7895a8eadf8016154a51d1b5a051b11e


S14-03) Bob accepts (should succeed)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_WRONG_ACCEPT_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**:  Pass
**Test Comments**: http://localhost:3000/transaction/0000381da053b2309ebfbcd61b7cf28b06597f1c94fc6365e2b9dbcdc2d2fb14




***# S15 - S9 RETEST — Directed: Maker Retargets Directed Taker (OPEN only) (Escrow ID 9)***


```bash
export ESCROW_DIRECTED_RETARGET_RETEST=15
```

S15-01) Alice opens directed escrow (initial directed taker = Bob)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_directed\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        9,
        \"$OTCT_UID\",
        9,
        \"$BOB_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00000289132939b46133c9c0c688486469513f2cdc828dbe4c52b656dbb459a9


S15-02) Alice retargets directed taker to Genesis (OPEN only)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"set_directed_taker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_RETARGET_RETEST,
        \"$GENESIS_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/000042c271dd97523d487ea47979707046ce583204c8f41a68c61b4d3bea4d03


S15-03) Negative: Bob tries to accept (should fail)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_RETARGET_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: error=Unauthorized('Only the directed taker can accept this escrow')
http://localhost:3000/transaction/00005a38c0fc197f429693dc1ab2d33dbb71c423ed32bac530b7cf4904334aed


**Test Logs**
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00005a38c0fc197f429693dc1ab2d33dbb71c423ed32bac530b7cf4904334aed" -n


25:2025-12-30 01:20:38 [info     ] nc execution failed            cause=None error=Unauthorized('Only the directed taker can accept this escrow') tx=00005a38c0fc197f429693dc1ab2d33dbb71c423ed32bac530b7cf4904334aed
26:2025-12-30 01:20:38 [debug    ] add_voided_by                  tx=00005a38c0fc197f429693dc1ab2d33dbb71c423ed32bac530b7cf4904334aed voided_hash=00005a38c0fc197f429693dc1ab2d33dbb71c423ed32bac530b7cf4904334aed
27:2025-12-30 01:20:38 [info     ] nano tx execution status       blk=0000000744c7cc877550b18397aab17244cc4611308a6b83dbd244558d8a35c8 execution=failure tx=00005a38c0fc197f429693dc1ab2d33dbb71c423ed32bac530b7cf4904334aed

S15-04) Genesis accepts (should succeed)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: genesis" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$GENESIS_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_RETARGET_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/0000621efc0c173cf2c23aced66e7bff738cd3c3c5db743830177c0d4cf75ef4



---

***# S16 - RETEST OF S11 — Directed: Expires After Accept, Cannot Fund (Escrow ID 11)***

This scenario will be retested fully under S17.
Retest required because of Localnet environment timing issues / set expiry timestamps.
Not a contract issue. 

```bash
export ESCROW_DIRECTED_EXPIRE_ACCEPT_RETEST=16
```


# Set an expiry ~120 seconds from now (adjust if needed)

```bash
EXP_TS=$(( $(date +%s) + 120 ))
```


S16-01) Alice opens directed escrow with short open-expiry


```bash
EXP_TS=$(( $(date +%s) + 120 ))

curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"open_escrow_directed_with_expiry\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$OTCM_UID\",
        14,
        \"$OTCT_UID\",
        15,
        $EXP_TS,
        \"$BOB_ADDR\"
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00003c2ae0026b74f26f822035880ce9eb2e033419f0cc843593f3454c9a8a0f



S16-02) Bob accepts (should succeed before expiry

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"accept_escrow\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        $ESCROW_DIRECTED_EXPIRE_ACCEPT_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```


**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00006169c5e9cc745b83870d59a03b197973803ffb08e95cc21a3423866576f2

```
sleep 120
```

S16-03) Alice tries to fund maker (should fail: expired)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: alice" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"fund_maker\",
    \"address\": \"$ALICE_ADDR\",
    \"data\": {
      \"actions\": [
        {\"type\":\"deposit\", \"token\":\"$OTCM_UID\", \"amount\":14}
      ],
      \"args\": [
        $ESCROW_DIRECTED_EXPIRE_ACCEPT_RETEST
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: error=InvalidEscrow('Escrow has expired')
http://localhost:3000/transaction/00002027293543091402325d5d8961582f37295d3b970afd998c35740e33ebf2

**Test Logs**
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00002027293543091402325d5d8961582f37295d3b970afd998c35740e33ebf2" -n


27:2025-12-30 01:31:26 [info     ] nc execution failed            cause=None error=InvalidEscrow('Escrow has expired') tx=00002027293543091402325d5d8961582f37295d3b970afd998c35740e33ebf2
28:2025-12-30 01:31:26 [debug    ] add_voided_by                  tx=00002027293543091402325d5d8961582f37295d3b970afd998c35740e33ebf2 voided_hash=00002027293543091402325d5d8961582f37295d3b970afd998c35740e33ebf2
29:2025-12-30 01:31:26 [info     ] nano tx execution status       blk=0000000ead81440e38a0dc54c93d2c932255feef67ea7000d0e63378018a5bca execution=failure tx=00002027293543091402325d5d8961582f37295d3b970afd998c35740e33ebf2

---

# S17 — Admin/Owner Only Actions

## S17-01) Negative: Bob tries set_fee_config (should void / unauthorized)

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: bob" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"set_fee_config\",
    \"address\": \"$BOB_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$PROTOCOL_ADDR\",
        50
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**:error=Unauthorized('Only the contract owner can update fee configuration')
http://localhost:3000/transaction/00001c2740773ac33eaf3ba967bf5f031a695ecefb4ca6fa3955c36493499e1f


**Test Logs**
docker logs hathor-localnet-full-node-1 --since 30m | grep -i "00001c2740773ac33eaf3ba967bf5f031a695ecefb4ca6fa3955c36493499e1f" -n

17:2025-12-30 01:41:40 [info     ] nc execution failed            cause=None error=Unauthorized('Only the contract owner can update fee configuration') tx=00001c2740773ac33eaf3ba967bf5f031a695ecefb4ca6fa3955c36493499e1f
18:2025-12-30 01:41:40 [debug    ] add_voided_by                  tx=00001c2740773ac33eaf3ba967bf5f031a695ecefb4ca6fa3955c36493499e1f voided_hash=00001c2740773ac33eaf3ba967bf5f031a695ecefb4ca6fa3955c36493499e1f
19:2025-12-30 01:41:40 [info     ] nano tx execution status       blk=00000025380da42fa01b08f9667294afabf95541e476bc3a03a3ed61824ae305 execution=failure tx=00001c2740773ac33eaf3ba967bf5f031a695ecefb4ca6fa3955c36493499e1f


## S17-02) Protocol/Owner sets fee config (should succeed

```bash
curl -sS -X POST \
  -H "X-Wallet-Id: protocol" \
  -H "Content-Type: application/json" \
  -d "{
    \"nc_id\": \"$CONTRACT_ID\",
    \"method\": \"set_fee_config\",
    \"address\": \"$PROTOCOL_ADDR\",
    \"data\": {
      \"actions\": [],
      \"args\": [
        \"$PROTOCOL_ADDR\",
        150
      ]
    }
  }" \
  "$WALLET/wallet/nano-contracts/execute" | jq
```

**Test Result**: Pass
**Test Comments**: http://localhost:3000/transaction/00003043a922e3a54ef47bf14c3d5b7bb9e729adc4522367844d426087788390

---



---


# S14 — Views & Query Sanity

## S14-01) get_config

```bash
curl -sS -X GET -H "X-Wallet-Id: alice"   "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_config()" | jq
```

{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_config()": {
        "value": [
          "WgBEype81huhwQRf617jj1846gB4yrWzts",
          "WgBEype81huhwQRf617jj1846gB4yrWzts",
          150,
          600,
          240,
          60,
          86400
        ]
      }
    }
  }
}


## S14-02) get_fee_quote

```bash
curl -sS -X GET -H "X-Wallet-Id: alice"   "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_fee_quote(100,125)" | jq
```

{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_fee_quote(100,125)": {
        "value": [
          2,
          2,
          123,
          98
        ]
      }
    }
  }
}

## S14-03) get_escrow + get_escrow_full (escrow 0)

```bash
NOW_TS=$(date +%s)

curl -sS -X GET -H "X-Wallet-Id: alice"   "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_escrow($ESCROW_PUBLIC)" | jq


{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_escrow(0)": {
        "value": [
          "WcAccYo8pMZLVJ573KmSHGacKDUeCaYtki",
          "WT7mEwUW8kaky27PjLbpwzbTZ2sTxw1pbd",
          "0000031457b791e84a317eb3200eaad492e9f95e42cad5edf3979abb2f50a74f",
          100,
          "00000118eafe46ee390d5655f03651b9e8be7c34f76a810b4086a2d845faf5f6",
          125,
          true,
          true,
          true,
          true,
          false,
          4
        ]
      }
    }
  }
}

curl -sS -X GET -H "X-Wallet-Id: alice"   "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_escrow_full($ESCROW_PUBLIC,$NOW_TS)" | jq
```

{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_escrow_full(0,1767059268)": {
        "value": [
          "WcAccYo8pMZLVJ573KmSHGacKDUeCaYtki",
          "WT7mEwUW8kaky27PjLbpwzbTZ2sTxw1pbd",
          "0000031457b791e84a317eb3200eaad492e9f95e42cad5edf3979abb2f50a74f",
          100,
          "00000118eafe46ee390d5655f03651b9e8be7c34f76a810b4086a2d845faf5f6",
          125,
          true,
          true,
          true,
          true,
          false,
          false,
          1767040608,
          1767040326,
          true,
          true,
          false,
          false,
          "",
          false,
          false,
          4
        ]
      }
    }
  }
}

## S14-04) get_counters + pagination

```bash
curl -sS -X GET -H "X-Wallet-Id: alice"   "$WALLET/wallet/nano-contracts/state?id=$CONTRACT_ID&calls[]=get_counters()&calls[]=get_escrow_ids_page(0,50)" | jq
```

{
  "success": true,
  "state": {
    "success": true,
    "nc_id": "00003ff6de9b1827ffa0275c8b4a438c39b92a55a4d63124d00ead1752ba0996",
    "blueprint_id": "00000075bc5b33d25153dbdb86940fcecdb68890ff2491621c2cf486cd509e5c",
    "blueprint_name": "OtcEscrowSwap",
    "fields": {},
    "balances": {},
    "calls": {
      "get_counters()": {
        "value": [
          17,
          2,
          7,
          0,
          2,
          3,
          2,
          1,
          7,
          10
        ]
      },
      "get_escrow_ids_page(0,50)": {
        "value": [
          0,
          50,
          0,
          [
            0,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16
          ]
        ]
      }
    }
  }
}

Expected:
- ids includes the escrows you created in this run
- next_cursor = 0 when no more pages
