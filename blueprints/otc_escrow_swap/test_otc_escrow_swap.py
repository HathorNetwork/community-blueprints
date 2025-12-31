import pytest

from hathor import Address, NCDepositAction, NCWithdrawalAction, TokenUid
from hathor_tests.nanocontracts.blueprints.unittest import BlueprintTestCase

# Import the blueprint from the submission folder (as it will exist in hathor-core)
from blueprints.otc_escrow_swap.otc_escrow_swap import (
    OtcEscrowSwap,
    InvalidConfig,
    Unauthorized,
    InvalidEscrow,
    InvalidActions,
    InvalidToken,
    STATUS_OPEN,
    STATUS_ACCEPTED,
    STATUS_FUNDED_MAKER,
    STATUS_FUNDED_BOTH,
    STATUS_EXECUTED,
    STATUS_REFUNDED,
    STATUS_CANCELLED,
    MAX_PROTOCOL_FEE_BPS,
)


class TestOtcEscrowSwap(BlueprintTestCase):
    """
    Unit test suite (Blueprint SDK / BlueprintTestCase) mapped from Localnet test scenario flow.
    Included Localnet scenarios:
      SA, S0, S1, S2, S3, S4, S5, S8, S10, S12, S13, S14, S15, S16, S17, S18
      S6, S7, S9, S11 were replaced by S13-S16
      
    Additional Unit Test Extras:
        UTE-01 - UTE-07
    """

    def setUp(self) -> None:
        super().setUp()

        # --- Register blueprint (docs-style) ---
        self.blueprint_id = self.gen_random_blueprint_id()
        self.contract_id = self.gen_random_contract_id()
        self.nc_catalog.blueprints[self.blueprint_id] = OtcEscrowSwap

        # --- Actors / tokens ---
        self.protocol = self.gen_random_address()    # contract owner (deployer)
        self.fee_recipient = self.protocol           # set to owner for simplicity
        self.alice = self.gen_random_address()
        self.bob = self.gen_random_address()
        self.genesis = self.gen_random_address()

        self.token_m: TokenUid = self.gen_random_token_uid()
        self.token_t: TokenUid = self.gen_random_token_uid()

        # --- Config (matches blueprint initialize signature) ---
        self.protocol_fee_bps = 100
        # Keep tests fast, but aligned with production guardrails
        self.default_open_expiry_secs = 600            # 10 minutes (fast but realistic)
        self.default_maker_funded_expiry_secs = 240    # 4 minutes
        self.min_expiry_secs = 60                      # MATCH production DEFAULT_MIN_EXPIRY_SECS
        self.max_expiry_secs = 365 * 24 * 60 * 60      # MATCH production DEFAULT_MAX_EXPIRY_SECS

        # IMPORTANT: create_contract MUST pass initialize args (blueprint requires them)
        ctx_create = self.create_context(caller_id=self.protocol, timestamp=1)
        self.runner.create_contract(
            self.contract_id,
            self.blueprint_id,
            ctx_create,
            self.fee_recipient,
            self.protocol_fee_bps,
            self.default_open_expiry_secs,
            self.default_maker_funded_expiry_secs,
            self.min_expiry_secs,
            self.max_expiry_secs,
        )

    # -----------------------
    # Helpers
    # -----------------------

    def _open_public(self, maker: Address, maker_amt: int, taker_amt: int, ts: int) -> int:
        ctx = self.create_context(caller_id=maker, timestamp=ts)
        escrow_id = self.runner.call_public_method(
            self.contract_id,
            "open_escrow",
            ctx,
            self.token_m,
            maker_amt,
            self.token_t,
            taker_amt,
        )
        assert isinstance(escrow_id, int)
        return escrow_id

    def _open_public_with_expiry(self, maker: Address, maker_amt: int, taker_amt: int, expiry_ts: int, ts: int) -> int:
        ctx = self.create_context(caller_id=maker, timestamp=ts)
        escrow_id = self.runner.call_public_method(
            self.contract_id,
            "open_escrow_with_expiry",
            ctx,
            self.token_m,
            maker_amt,
            self.token_t,
            taker_amt,
            expiry_ts,
        )
        assert isinstance(escrow_id, int)
        return escrow_id

    def _open_directed(self, maker: Address, directed_taker: Address, maker_amt: int, taker_amt: int, ts: int) -> int:
        ctx = self.create_context(caller_id=maker, timestamp=ts)
        escrow_id = self.runner.call_public_method(
            self.contract_id,
            "open_escrow_directed",
            ctx,
            self.token_m,
            maker_amt,
            self.token_t,
            taker_amt,
            directed_taker,
        )
        assert isinstance(escrow_id, int)
        return escrow_id

    def _open_directed_with_expiry(
        self, maker: Address, directed_taker: Address, maker_amt: int, taker_amt: int, expiry_ts: int, ts: int
    ) -> int:
        ctx = self.create_context(caller_id=maker, timestamp=ts)
        escrow_id = self.runner.call_public_method(
            self.contract_id,
            "open_escrow_directed_with_expiry",
            ctx,
            self.token_m,
            maker_amt,
            self.token_t,
            taker_amt,
            expiry_ts,
            directed_taker,
        )
        assert isinstance(escrow_id, int)
        return escrow_id

    def _accept(self, taker: Address, escrow_id: int, ts: int) -> None:
        ctx = self.create_context(caller_id=taker, timestamp=ts)
        self.runner.call_public_method(self.contract_id, "accept_escrow", ctx, escrow_id)

    def _set_directed_taker(self, maker: Address, escrow_id: int, new_taker: Address, ts: int) -> None:
        ctx = self.create_context(caller_id=maker, timestamp=ts)
        self.runner.call_public_method(self.contract_id, "set_directed_taker", ctx, escrow_id, new_taker)

    def _cancel_before_funding(self, maker: Address, escrow_id: int, ts: int) -> None:
        ctx = self.create_context(caller_id=maker, timestamp=ts)
        self.runner.call_public_method(self.contract_id, "cancel_before_funding", ctx, escrow_id)

    def _fund_maker(self, maker: Address, escrow_id: int, amount: int, ts: int) -> None:
        ctx = self.create_context(
            caller_id=maker,
            timestamp=ts,
            actions=[NCDepositAction(token_uid=self.token_m, amount=amount)],
        )
        self.runner.call_public_method(self.contract_id, "fund_maker", ctx, escrow_id)

    def _fund_taker(self, taker: Address, escrow_id: int, amount: int, ts: int) -> None:
        ctx = self.create_context(
            caller_id=taker,
            timestamp=ts,
            actions=[NCDepositAction(token_uid=self.token_t, amount=amount)],
        )
        self.runner.call_public_method(self.contract_id, "fund_taker", ctx, escrow_id)

    def _withdraw(self, caller: Address, escrow_id: int, token: TokenUid, amount: int, ts: int) -> None:
        ctx = self.create_context(
            caller_id=caller,
            timestamp=ts,
            actions=[NCWithdrawalAction(token_uid=token, amount=amount)],
        )
        self.runner.call_public_method(self.contract_id, "withdraw", ctx, escrow_id)

    def _refund(self, caller: Address, escrow_id: int, token: TokenUid, amount: int, ts: int) -> None:
        ctx = self.create_context(
            caller_id=caller,
            timestamp=ts,
            actions=[NCWithdrawalAction(token_uid=token, amount=amount)],
        )
        self.runner.call_public_method(self.contract_id, "refund", ctx, escrow_id)

    def _status(self, escrow_id: int) -> int:
        return self.runner.call_view_method(self.contract_id, "get_escrow_status", escrow_id)

    # -----------------------
    # SA — Deploy & Initialize (blueprint + contract)
    # -----------------------

    def test_sa_deploy_initialize_config_sanity(self):
        cfg = self.runner.call_view_method(self.contract_id, "get_config")
        assert cfg.owner == str(self.protocol)
        assert cfg.fee_recipient == str(self.fee_recipient)
        assert cfg.protocol_fee_bps == self.protocol_fee_bps

        assert self.runner.call_view_method(self.contract_id, "get_escrow_exists", 999999) is False
        assert self.runner.call_view_method(self.contract_id, "get_escrow_status", 999999) == -1

        details = self.runner.call_view_method(self.contract_id, "get_escrow", 999999)
        assert details.status == -1

    # -----------------------
    # S0 — Public Escrow — Complete Lifecycle (open→accept→funds→withdraws/fees)
    # -----------------------

    def test_s0_public_complete_lifecycle_with_fees(self):
        escrow_id = self._open_public(self.alice, 100, 125, ts=10)
        assert self._status(escrow_id) == STATUS_OPEN

        self._accept(self.bob, escrow_id, ts=11)
        assert self._status(escrow_id) == STATUS_ACCEPTED

        self._fund_maker(self.alice, escrow_id, 100, ts=12)
        assert self._status(escrow_id) == STATUS_FUNDED_MAKER

        self._fund_taker(self.bob, escrow_id, 125, ts=13)
        assert self._status(escrow_id) == STATUS_FUNDED_BOTH

        quote = self.runner.call_view_method(self.contract_id, "get_fee_quote", 100, 125)
        assert quote.maker_fee == 1
        assert quote.taker_fee == 2
        assert quote.maker_net_receive == 123
        assert quote.taker_net_receive == 99

        # Maker withdraws OTCT net; taker withdraws OTCM net
        self._withdraw(self.alice, escrow_id, self.token_t, quote.maker_net_receive, ts=14)
        self._withdraw(self.bob, escrow_id, self.token_m, quote.taker_net_receive, ts=15)
        assert self._status(escrow_id) == STATUS_EXECUTED

        # Fee recipient withdraws protocol fee balances per token (must match exact balance)
        fee_m = self.runner.call_view_method(self.contract_id, "get_protocol_fee_balance", self.token_m)
        fee_t = self.runner.call_view_method(self.contract_id, "get_protocol_fee_balance", self.token_t)
        assert fee_m == quote.maker_fee
        assert fee_t == quote.taker_fee

        self._withdraw(self.fee_recipient, escrow_id, self.token_m, fee_m, ts=16)
        self._withdraw(self.fee_recipient, escrow_id, self.token_t, fee_t, ts=17)

        assert self.runner.call_view_method(self.contract_id, "get_protocol_fee_balance", self.token_m) == 0
        assert self.runner.call_view_method(self.contract_id, "get_protocol_fee_balance", self.token_t) == 0

    # -----------------------
    # S1 — Directed Escrow — Complete Lifecycle
    # -----------------------

    def test_s1_directed_complete_lifecycle(self):
        escrow_id = self._open_directed(self.alice, self.bob, 50, 70, ts=20)
        self._accept(self.bob, escrow_id, ts=21)

        self._fund_maker(self.alice, escrow_id, 50, ts=22)
        self._fund_taker(self.bob, escrow_id, 70, ts=23)
        assert self._status(escrow_id) == STATUS_FUNDED_BOTH

        quote = self.runner.call_view_method(self.contract_id, "get_fee_quote", 50, 70)
        assert quote.maker_fee == 1
        assert quote.taker_fee == 1
        assert quote.maker_net_receive == 69
        assert quote.taker_net_receive == 49

        self._withdraw(self.alice, escrow_id, self.token_t, quote.maker_net_receive, ts=24)
        self._withdraw(self.bob, escrow_id, self.token_m, quote.taker_net_receive, ts=25)
        assert self._status(escrow_id) == STATUS_EXECUTED

    # -----------------------
    # S2 — Public Escrow — Cancel Before Funding
    # -----------------------

    def test_s2_cancel_before_funding(self):
        escrow_id = self._open_public(self.alice, 10, 20, ts=30)
        self._accept(self.bob, escrow_id, ts=31)
        assert self._status(escrow_id) == STATUS_ACCEPTED

        self._cancel_before_funding(self.alice, escrow_id, ts=32)
        assert self._status(escrow_id) == STATUS_CANCELLED

        with pytest.raises(Unauthorized):
            self._cancel_before_funding(self.bob, escrow_id, ts=33)

        with pytest.raises(InvalidEscrow):
            self._fund_maker(self.alice, escrow_id, 10, ts=34)

    # -----------------------
    # S3 — Public Escrow — Both Funded (verify refund blocked; settle normally)
    # -----------------------

    def test_s3_refund_before_expiry_should_fail_then_settle_normally(self):
        escrow_id = self._open_public(self.alice, 40, 60, ts=40)
        self._accept(self.bob, escrow_id, ts=41)
        self._fund_maker(self.alice, escrow_id, 40, ts=42)
        self._fund_taker(self.bob, escrow_id, 60, ts=43)
        assert self._status(escrow_id) == STATUS_FUNDED_BOTH

        with pytest.raises(InvalidEscrow):
            self._refund(self.alice, escrow_id, self.token_m, 40, ts=44)

        quote = self.runner.call_view_method(self.contract_id, "get_fee_quote", 40, 60)
        self._withdraw(self.alice, escrow_id, self.token_t, quote.maker_net_receive, ts=45)
        self._withdraw(self.bob, escrow_id, self.token_m, quote.taker_net_receive, ts=46)
        assert self._status(escrow_id) == STATUS_EXECUTED

    # -----------------------
    # S4 — Expiry before accept blocks accept + flags in get_escrow_full
    # -----------------------

    def test_s4_expiry_before_accept_blocks_accept_and_flags(self):
        t0 = 100
        expiry_ts = t0 + self.min_expiry_secs + 1
        escrow_id = self._open_public_with_expiry(self.alice, 10, 20, expiry_ts, ts=t0)

        with pytest.raises(InvalidEscrow):
            self._accept(self.bob, escrow_id, ts=expiry_ts + 1)

        full = self.runner.call_view_method(self.contract_id, "get_escrow_full", escrow_id, expiry_ts + 1)
        assert full.is_open_expired is True
        assert full.is_expired is True

    # -----------------------
    # S5 — Accept before expiry; funding after expiry blocked
    # -----------------------

    def test_s5_expiry_after_accept_blocks_funding(self):
        t0 = 200
        expiry_ts = t0 + self.min_expiry_secs + 1
        escrow_id = self._open_public_with_expiry(self.alice, 10, 20, expiry_ts, ts=t0)

        self._accept(self.bob, escrow_id, ts=t0 + 1)
        assert self._status(escrow_id) == STATUS_ACCEPTED

        with pytest.raises(InvalidEscrow):
            self._fund_maker(self.alice, escrow_id, 10, ts=expiry_ts + 1)

    # -----------------------
    # S8 — Directed wrong taker cannot fund
    # -----------------------

    def test_s8_directed_wrong_taker_cannot_fund(self):
        escrow_id = self._open_directed(self.alice, self.bob, 12, 13, ts=300)
        self._accept(self.bob, escrow_id, ts=301)
        self._fund_maker(self.alice, escrow_id, 12, ts=302)

        with pytest.raises(Unauthorized):
            self._fund_taker(self.genesis, escrow_id, 13, ts=303)

        self._fund_taker(self.bob, escrow_id, 13, ts=304)
        assert self._status(escrow_id) == STATUS_FUNDED_BOTH

    # -----------------------
    # S10 — set_directed_taker negatives
    # -----------------------

    def test_s10_set_directed_taker_negative_cases(self):
        escrow_id = self._open_directed(self.alice, self.bob, 9, 11, ts=400)

        # Non-maker cannot update
        with pytest.raises(Unauthorized):
            self._set_directed_taker(self.genesis, escrow_id, self.genesis, ts=401)

        # Maker can update while OPEN
        self._set_directed_taker(self.alice, escrow_id, self.genesis, ts=402)

        # After accept, maker cannot update (OPEN only)
        self._accept(self.genesis, escrow_id, ts=403)
        with pytest.raises(InvalidEscrow):
            self._set_directed_taker(self.alice, escrow_id, self.bob, ts=404)

    # -----------------------
    # S12 — Directed: maker funds, expires, taker blocked, maker refunds
    # -----------------------

    def test_s12_directed_maker_funded_then_expires_refund(self):
        escrow_id = self._open_directed(self.alice, self.bob, 16, 17, ts=500)
        self._accept(self.bob, escrow_id, ts=501)
        self._fund_maker(self.alice, escrow_id, 16, ts=502)
        assert self._status(escrow_id) == STATUS_FUNDED_MAKER

        too_late = 502 + self.default_maker_funded_expiry_secs + 1
        with pytest.raises(InvalidEscrow):
            self._fund_taker(self.bob, escrow_id, 17, ts=too_late)

        self._refund(self.alice, escrow_id, self.token_m, 16, ts=too_late + 1)
        assert self._status(escrow_id) == STATUS_REFUNDED

    # -----------------------
    # S13 — Public: maker funds, expires, taker blocked, maker refunds
    # -----------------------

    def test_s13_public_maker_funded_then_expires_refund(self):
        escrow_id = self._open_public(self.alice, 21, 34, ts=600)
        self._accept(self.bob, escrow_id, ts=601)
        self._fund_maker(self.alice, escrow_id, 21, ts=602)
        assert self._status(escrow_id) == STATUS_FUNDED_MAKER

        too_late = 602 + self.default_maker_funded_expiry_secs + 1
        with pytest.raises(InvalidEscrow):
            self._fund_taker(self.bob, escrow_id, 34, ts=too_late)

        self._refund(self.alice, escrow_id, self.token_m, 21, ts=too_late + 1)
        assert self._status(escrow_id) == STATUS_REFUNDED

    
    # -----------------------
    # S14 — Directed: Wrong taker cannot accept (Unauthorized); correct taker can accept
    # -----------------------

    def test_s14_directed_wrong_taker_cannot_accept(self):
        escrow_id = self._open_directed(self.alice, self.bob, 10, 20, ts=700)

        # Negative: Genesis tries to accept (should fail / Unauthorized)
        with pytest.raises(Unauthorized):
            self._accept(self.genesis, escrow_id, ts=701)

        # Bob accepts (should succeed)
        self._accept(self.bob, escrow_id, ts=702)
        assert self._status(escrow_id) == STATUS_ACCEPTED
    

    # -----------------------
    # S15 — Directed retarget: OPEN-only; old taker cannot accept; new taker can
    # -----------------------

    def test_s15_directed_retarget_then_accept(self):
        escrow_id = self._open_directed(self.alice, self.bob, 9, 11, ts=800)
        self._set_directed_taker(self.alice, escrow_id, self.genesis, ts=801)

        with pytest.raises(Unauthorized):
            self._accept(self.bob, escrow_id, ts=802)

        self._accept(self.genesis, escrow_id, ts=803)
        assert self._status(escrow_id) == STATUS_ACCEPTED

    # -----------------------
    # S16 — Directed with short open-expiry: accept before expiry; funding after expiry blocked
    # -----------------------

    def test_s16_directed_open_expiry_blocks_funding_after_expiry(self):
        t0 = 900
        expiry_ts = t0 + self.min_expiry_secs + 1
        escrow_id = self._open_directed_with_expiry(self.alice, self.bob, 14, 15, expiry_ts, ts=t0)

        self._accept(self.bob, escrow_id, ts=t0 + 1)
        assert self._status(escrow_id) == STATUS_ACCEPTED

        with pytest.raises(InvalidEscrow):
            self._fund_maker(self.alice, escrow_id, 14, ts=expiry_ts + 1)

    # -----------------------
    # S17 — Owner-only admin actions (set_fee_config)
    # -----------------------

    def test_s17_admin_owner_only_actions(self):
        # Non-owner should fail
        ctx_bob = self.create_context(caller_id=self.bob, timestamp=1000)
        with pytest.raises(Unauthorized):
            self.runner.call_public_method(self.contract_id, "set_fee_config", ctx_bob, self.fee_recipient, 50)

        # Owner succeeds
        ctx_owner = self.create_context(caller_id=self.protocol, timestamp=1001)
        self.runner.call_public_method(self.contract_id, "set_fee_config", ctx_owner, self.fee_recipient, 50)

        cfg = self.runner.call_view_method(self.contract_id, "get_config")
        assert cfg.protocol_fee_bps == 50

    # -----------------------
    # S18 — Views + counters + pagination sanity
    # -----------------------

    def test_s18_views_and_pagination_sanity(self):
        cfg = self.runner.call_view_method(self.contract_id, "get_config")
        assert cfg.protocol_fee_bps == self.protocol_fee_bps

        quote = self.runner.call_view_method(self.contract_id, "get_fee_quote", 100, 125)
        assert (quote.maker_fee, quote.taker_fee) == (1, 2)

        escrow_id = self._open_public(self.alice, 5, 7, ts=710)

        summary = self.runner.call_view_method(self.contract_id, "get_escrow", escrow_id)
        assert summary.maker == str(self.alice)
        assert summary.status == STATUS_OPEN

        full = self.runner.call_view_method(self.contract_id, "get_escrow_full", escrow_id, 710)
        assert full.maker == str(self.alice)
        assert full.is_directed is False
        assert full.status == STATUS_OPEN

        counters = self.runner.call_view_method(self.contract_id, "get_counters")
        assert counters.total_escrows >= 1
        assert counters.count_public >= 1

        page = self.runner.call_view_method(self.contract_id, "get_escrow_ids_page", 0, 10)
        assert page.cursor_in == 0
        assert page.limit == 10
        assert escrow_id in page.ids


    # -------------------------------------------
    # Unit Test Extras (UTE)
    # --------------------------------------------
        
    # -----------------------
    # UTE-01 — set_fee_config bounds + auth
    # -----------------------

    def test_ute_01_set_fee_config_bounds(self):
        # Non-owner cannot update
        ctx = self.create_context(caller_id=self.bob, timestamp=2000)
        with pytest.raises(Unauthorized):
            self.runner.call_public_method(
                self.contract_id, "set_fee_config", ctx, self.fee_recipient, 50
            )

        # Owner: negative fee
        ctx = self.create_context(caller_id=self.protocol, timestamp=2001)
        with pytest.raises(InvalidConfig):
            self.runner.call_public_method(
                self.contract_id, "set_fee_config", ctx, self.fee_recipient, -1
            )

        # Owner: fee above MAX_PROTOCOL_FEE_BPS
        with pytest.raises(InvalidConfig):
            self.runner.call_public_method(
                self.contract_id,
                "set_fee_config",
                ctx,
                self.fee_recipient,
                MAX_PROTOCOL_FEE_BPS + 1,
            )

        # Owner: valid update
        self.runner.call_public_method(
            self.contract_id, "set_fee_config", ctx, self.fee_recipient, 100
        )
 
    # -----------------------
    # UTE-02 — set_expiry_config bounds + auth
    # -----------------------

    def test_ute_02_set_expiry_config_bounds(self):
        # Non-owner blocked
        ctx = self.create_context(caller_id=self.bob, timestamp=2100)
        with pytest.raises(Unauthorized):
            self.runner.call_public_method(
                self.contract_id,
                "set_expiry_config",
                ctx,
                100,
                100,
                10,
                1000,
            )

        ctx = self.create_context(caller_id=self.protocol, timestamp=2101)

        # min_expiry_secs <= 0
        with pytest.raises(InvalidConfig):
            self.runner.call_public_method(
                self.contract_id,
                "set_expiry_config",
                ctx,
                100,
                100,
                0,
                1000,
            )

        # max < min
        with pytest.raises(InvalidConfig):
            self.runner.call_public_method(
                self.contract_id,
                "set_expiry_config",
                ctx,
                100,
                100,
                50,
                40,
            )

        # default_open_expiry_secs out of bounds
        with pytest.raises(InvalidConfig):
            self.runner.call_public_method(
                self.contract_id,
                "set_expiry_config",
                ctx,
                5,
                100,
                10,
                1000,
            )

        # valid update
        self.runner.call_public_method(
            self.contract_id,
            "set_expiry_config",
            ctx,
            120,
            120,
            60,
            3600,
        )

    # -----------------------
    # UTE-03 — accept_escrow already accepted by another taker
    # -----------------------
    
    def test_ute_03_accept_by_second_taker_fails(self):
        escrow_id = self._open_public(self.alice, 10, 20, ts=2200)

        self._accept(self.bob, escrow_id, ts=2201)

        with pytest.raises(InvalidEscrow):
            self._accept(self.genesis, escrow_id, ts=2202)    
    
    
    # -----------------------
    # UTE-04 — fund_maker invalid actions
    # -----------------------
 
    def test_ute_04_fund_maker_invalid_actions(self):
        escrow_id = self._open_public(self.alice, 10, 20, ts=2300)
        self._accept(self.bob, escrow_id, ts=2301)

        # Wrong token
        ctx = self.create_context(
            caller_id=self.alice,
            timestamp=2302,
            actions=[NCDepositAction(token_uid=self.token_t, amount=10)],
        )
        with pytest.raises(InvalidToken):
            self.runner.call_public_method(self.contract_id, "fund_maker", ctx, escrow_id)

        # Wrong amount
        ctx = self.create_context(
            caller_id=self.alice,
            timestamp=2303,
            actions=[NCDepositAction(token_uid=self.token_m, amount=9)],
        )
        with pytest.raises(InvalidActions):
            self.runner.call_public_method(self.contract_id, "fund_maker", ctx, escrow_id) 
 
 
    # -----------------------
    # UTE-05 — fund_taker invalid actions
    # -----------------------
    
    def test_ute_05_fund_taker_invalid_actions(self):
        escrow_id = self._open_public(self.alice, 10, 20, ts=2400)
        self._accept(self.bob, escrow_id, ts=2401)
        self._fund_maker(self.alice, escrow_id, 10, ts=2402)

        # Wrong token
        ctx = self.create_context(
            caller_id=self.bob,
            timestamp=2403,
            actions=[NCDepositAction(token_uid=self.token_m, amount=20)],
        )
        with pytest.raises(InvalidToken):
            self.runner.call_public_method(self.contract_id, "fund_taker", ctx, escrow_id)

        # Wrong amount
        ctx = self.create_context(
            caller_id=self.bob,
            timestamp=2404,
            actions=[NCDepositAction(token_uid=self.token_t, amount=19)],
        )
        with pytest.raises(InvalidActions):
            self.runner.call_public_method(self.contract_id, "fund_taker", ctx, escrow_id)    
    
    
    # -----------------------
    # UTE-06 — withdraw invalid actions
    # -----------------------
    
    def test_ute_06_withdraw_invalid_actions(self):
        escrow_id = self._open_public(self.alice, 10, 20, ts=2500)
        self._accept(self.bob, escrow_id, ts=2501)
        self._fund_maker(self.alice, escrow_id, 10, ts=2502)
        self._fund_taker(self.bob, escrow_id, 20, ts=2503)

        # Maker wrong token
        ctx = self.create_context(
            caller_id=self.alice,
            timestamp=2504,
            actions=[NCWithdrawalAction(token_uid=self.token_m, amount=19)],
        )
        with pytest.raises(InvalidActions):
            self.runner.call_public_method(self.contract_id, "withdraw", ctx, escrow_id)

        # Maker wrong amount
        ctx = self.create_context(
            caller_id=self.alice,
            timestamp=2505,
            actions=[NCWithdrawalAction(token_uid=self.token_t, amount=18)],
        )
        with pytest.raises(InvalidActions):
            self.runner.call_public_method(self.contract_id, "withdraw", ctx, escrow_id)    
    
    
    # -----------------------
    # UTE-07 — double withdraw / closed state guards
    # -----------------------
 
 
    def test_ute_07_double_withdraw_and_closed_state(self):
        escrow_id = self._open_public(self.alice, 10, 20, ts=2600)
        self._accept(self.bob, escrow_id, ts=2601)
        self._fund_maker(self.alice, escrow_id, 10, ts=2602)
        self._fund_taker(self.bob, escrow_id, 20, ts=2603)

        quote = self.runner.call_view_method(self.contract_id, "get_fee_quote", 10, 20)

        self._withdraw(self.alice, escrow_id, self.token_t, quote.maker_net_receive, ts=2604)

        with pytest.raises(InvalidEscrow):
            self._withdraw(self.alice, escrow_id, self.token_t, quote.maker_net_receive, ts=2605)

        self._withdraw(self.bob, escrow_id, self.token_m, quote.taker_net_receive, ts=2606)

        with pytest.raises(InvalidEscrow):
            self._refund(self.alice, escrow_id, self.token_m, 10, ts=2607) 
 
