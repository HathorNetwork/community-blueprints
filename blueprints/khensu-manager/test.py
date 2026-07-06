import inspect
import math
import os
from hathor.crypto.util import decode_address
from hathor.nanocontracts.blueprints.khensu_manager import BASIS_POINTS
from hathor.nanocontracts.context import Context
from hathor.nanocontracts.exception import NCFail
from hathor.nanocontracts.types import (
    Address,
    Amount,
    TokenUid,
    NCDepositAction,
    NCWithdrawalAction,
)
from hathor.conf.get_settings import HathorSettings
from hathor.wallet.keypair import KeyPair
from hathor.util import not_none
from hathor_tests.nanocontracts.blueprints.unittest import BlueprintTestCase
from hathor.nanocontracts.blueprints import khensu_manager, dozer_pool_manager

settings = HathorSettings()
HTR_UID = TokenUid(settings.HATHOR_TOKEN_UID)

FEE_TOKEN_VALUE = 1

DEFAULT_MARKET_CAP = Amount(6900000_00)  # 6,900,000 HTR (around $69.000)
INITIAL_TOKEN_RESERVE = Amount(1000000000_00)  # 1 billion tokens created
BUY_FEE_RATE = Amount(100)  # 1%
SELL_FEE_RATE = Amount(300)  # 3%
CREATOR_FEE_RATE = Amount(100)  # 1%
POOL_FEE_RATE = Amount(10)
DEFAULT_GRADUATION_FEE = Amount(100000_00)  # 100,000 HTR (around $1,000)
LRU_CACHE_CAPACITY = 150  # Default LRU cache capacity

INFINITY = INITIAL_TOKEN_RESERVE * DEFAULT_MARKET_CAP


class KhensuManagerTestCase(BlueprintTestCase):
    def setUp(self):
        super().setUp()

        # Set up KhensuManager contract
        # self.blueprint_id_khensu = self.gen_random_blueprint_id()
        self.blueprint_id_khensu = self.register_blueprint_file(
            inspect.getfile(khensu_manager)
        )
        self.manager_id = self.gen_random_contract_id()

        # self.register_blueprint_class(self.blueprint_id_khensu, KhensuManager)

        # Set up Dozer Pool Manager contract
        # self.blueprint_id_dozer = self.gen_random_blueprint_id()
        self.blueprint_id_dozer = self.register_blueprint_file(
            inspect.getfile(dozer_pool_manager)
        )
        self.dozer_pool_manager_id = self.gen_random_contract_id()

        # self.register_blueprint_class(self.blueprint_id_dozer, DozerPoolManager)

        # Setup admin and user addresses
        self.admin_address = Address(self._get_any_address()[0])
        self.user_address = Address(self._get_any_address()[0])

        # Initialize base tx for contexts
        self.tx = self.get_genesis_tx()

        self.token1_uid = None
        self.token2_uid = None
        self.manager_storage = None

    def _get_any_address(self) -> tuple[bytes, KeyPair]:
        """Generate a random address and keypair for testing"""
        password = os.urandom(12)
        key = KeyPair.create(password)
        address_b58 = key.address
        address_bytes = decode_address(not_none(address_b58))
        return address_bytes, key

    def get_current_timestamp(self):
        return int(self.clock.seconds())

    def _initialize_dozer(self):
        """Initialize the DozerPoolManager contract"""
        context = self.create_context(caller_id=self.admin_address)
        self.runner.create_contract(
            self.dozer_pool_manager_id,
            self.blueprint_id_dozer,
            context,
        )

        # Create and sign a pool USD/HTR
        deposit_htr = NCDepositAction(token_uid=HTR_UID, amount=1000000)
        usd_uid = self.gen_random_token_uid()
        deposit_usd = NCDepositAction(token_uid=usd_uid, amount=10000)
        ctx = self.create_context(
            caller_id=self.admin_address,
            actions=[deposit_htr, deposit_usd],
        )
        self.runner.call_public_method(
            self.dozer_pool_manager_id,
            "create_pool",
            ctx,
            POOL_FEE_RATE,
        )

        ctx = self.create_context(
            caller_id=self.admin_address,
            actions=[],
        )
        self.runner.call_public_method(
            self.dozer_pool_manager_id,
            "sign_pool",
            ctx,
            HTR_UID,
            usd_uid,
            POOL_FEE_RATE,
        )

        ctx = self.create_context(
            caller_id=self.admin_address,
            actions=[],
        )
        self.runner.call_public_method(
            self.dozer_pool_manager_id,
            "set_htr_usd_pool",
            ctx,
            HTR_UID,
            usd_uid,
            POOL_FEE_RATE,
        )

    def _initialize_manager(self) -> Context:
        """Initialize KhensuManager contract"""
        ctx = self.create_context(caller_id=self.admin_address)

        self._initialize_dozer()

        self.runner.create_contract(
            self.manager_id,
            self.blueprint_id_khensu,
            ctx,
            self.dozer_pool_manager_id,
            DEFAULT_MARKET_CAP,
            DEFAULT_GRADUATION_FEE,
            INITIAL_TOKEN_RESERVE,
            BUY_FEE_RATE,
            SELL_FEE_RATE,
            CREATOR_FEE_RATE,
            POOL_FEE_RATE,
            LRU_CACHE_CAPACITY,
        )

        ctx = self.create_context(
            caller_id=self.admin_address,
            actions=[],
        )

        self.runner.call_public_method(
            self.dozer_pool_manager_id,
            "add_authorized_signer",
            ctx,
            self.manager_id,
        )

        self.manager_storage = self.runner.get_storage(self.manager_id)
        return ctx

    def _register_token(
        self, token_name: str, token_symbol: str, creator_address=None
    ) -> TokenUid:
        """Register a new token with the manager"""
        if creator_address is None:
            creator_address = self.admin_address

        action = NCDepositAction(token_uid=HTR_UID, amount=int(FEE_TOKEN_VALUE))

        ctx = self.create_context(
            caller_id=creator_address,
            actions=[action],
        )

        token_uid = self.runner.call_public_method(
            self.manager_id,
            "register_token",
            ctx,
            token_name,
            token_symbol,
            "",
            "",
            "",
            "",
            "",
        )

        return token_uid

    def test_initialize(self) -> None:
        """Test basic initialization"""
        self._initialize_manager()

        storage = self.manager_storage
        self.assertIsNotNone(storage)

        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        platform_stats = self.runner.call_view_method(
            self.manager_id, "get_platform_stats"
        )

        self.assertEqual(admin_info.admin_address, self.admin_address.hex())
        self.assertEqual(admin_info.buy_fee_rate, BUY_FEE_RATE)
        self.assertEqual(admin_info.sell_fee_rate, SELL_FEE_RATE)
        self.assertEqual(admin_info.default_target_market_cap, DEFAULT_MARKET_CAP)
        self.assertEqual(admin_info.default_graduation_fee, DEFAULT_GRADUATION_FEE)
        self.assertEqual(platform_stats["total_tokens_created"], 0)
        self.assertEqual(platform_stats["total_tokens_migrated"], 0)

    def test_register_token(self) -> None:
        """Test token registration"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        platform_stats = self.runner.call_view_method(
            self.manager_id, "get_platform_stats"
        )
        self.assertEqual(platform_stats["total_tokens_created"], 1)

        # Check token exists in the registry
        all_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 1, HTR_UID
        )
        self.assertSubstring(str(self.token1_uid.hex()), all_tokens)

        fetched_token_uid = self.runner.call_view_method(
            self.manager_id, "search", "TK1", 1, 0
        )
        self.assertEqual(str(self.token1_uid.hex()), fetched_token_uid)

        fetched_token_uid = self.runner.call_view_method(
            self.manager_id, "search", "token1", 1, 0
        )
        self.assertEqual(str(self.token1_uid.hex()), fetched_token_uid)

        # Check token data using get_token_info
        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )

        self.assertEqual(token_info.creator, self.admin_address.hex())
        self.assertEqual(token_info.progress, 0)
        self.assertEqual(
            token_info.token_reserve,
            INITIAL_TOKEN_RESERVE,
        )
        self.assertEqual(token_info.is_migrated, False)

    def test_register_token_duplicate(self) -> None:
        """Test registering a duplicate token fails"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        # Try to register the same token again
        with self.assertRaises(NCFail):
            self._register_token("token1", "TK1")

    def test_buy_tokens(self) -> None:
        """Test buying tokens with HTR"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        initial_token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )

        pay_for_tokens = 1000000
        buy_fee = math.ceil(pay_for_tokens * (BUY_FEE_RATE) / BASIS_POINTS)
        creator_fee = (
            math.ceil(pay_for_tokens * (BUY_FEE_RATE + CREATOR_FEE_RATE) / BASIS_POINTS)
            - buy_fee
        )
        amount_in = pay_for_tokens + buy_fee + creator_fee

        # Calculate expected tokens out
        quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in
        )
        expected_out = quote["amount_received"]

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=expected_out)
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx, self.token1_uid
        )

        # Verify state changes
        # Check transaction count and volume in token statistics
        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )

        self.assertEqual(token_info.transaction_count, 1)
        self.assertEqual(token_info.total_volume, amount_in)
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.collected_buy_fees, buy_fee)

        # Check token reserve decreased and virtual pool increased
        self.assertEqual(
            token_info.token_reserve, initial_token_info.token_reserve - expected_out
        )
        final_raised = token_info.virtual_pool
        htr_collected_from_deviation = admin_info.collected_operation_fees
        self.assertEqual(final_raised + htr_collected_from_deviation, pay_for_tokens)

        # --------------------------------------------------------
        # Now execute the same process, but withdrawing less tokens than available to simulate slippage protection
        initial_token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )
        quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in
        )
        expected_out = quote["amount_received"]
        requested_out = expected_out // 2

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=requested_out)
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx, self.token1_uid
        )

        # Verify state changes
        # Check transaction count and volume in token statistics
        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )

        self.assertEqual(token_info.transaction_count, 2)
        self.assertEqual(token_info.total_volume, 2 * amount_in)
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.collected_buy_fees, 2 * buy_fee)

        # Check token reserve decreased and virtual pool increased
        self.assertEqual(
            token_info.token_reserve, initial_token_info.token_reserve - expected_out
        )
        final_raised = token_info.virtual_pool
        htr_collected_from_deviation = admin_info.collected_operation_fees
        self.assertEqual(
            final_raised + htr_collected_from_deviation, 2 * pay_for_tokens
        )

        # The slippage protection should be in the user balance
        token_balance = self.runner.call_view_method(
            self.manager_id,
            "get_user_token_balance",
            self.user_address,
            self.token1_uid,
        )
        self.assertEqual(token_balance, expected_out - requested_out)

        # --------------------------------------------------------
        # Now test buying more than available and checkin the balance

        extra_htr_amount = 123456

        quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, INFINITY
        )

        deposit = NCDepositAction(
            token_uid=HTR_UID, amount=quote["total_payment"] + extra_htr_amount
        )
        # No withdrawal, so the tokens should be on balance
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=0)
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx, self.token1_uid
        )

        final_token_balance = self.runner.call_view_method(
            self.manager_id,
            "get_user_token_balance",
            self.user_address,
            self.token1_uid,
        )
        htr_balance = self.runner.call_view_method(
            self.manager_id,
            "get_user_token_balance",
            self.user_address,
            HTR_UID,
        )
        self.assertEqual(final_token_balance - token_balance, quote["amount_received"])
        self.assertEqual(extra_htr_amount, htr_balance)

    def test_sell_tokens(self) -> None:
        """Test selling tokens for HTR"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        # Defining values expected for the test
        pay_for_tokens = 1000000
        buy_fee = math.ceil(pay_for_tokens * (BUY_FEE_RATE) / BASIS_POINTS)
        creator_fee = (
            math.ceil(pay_for_tokens * (BUY_FEE_RATE + CREATOR_FEE_RATE) / BASIS_POINTS)
            - buy_fee
        )
        buy_amount = pay_for_tokens + buy_fee + creator_fee
        max_fee_for_sell = math.ceil(pay_for_tokens * SELL_FEE_RATE / BASIS_POINTS)
        max_amount_received_for_sell = pay_for_tokens - max_fee_for_sell

        # First buy some tokens to ensure the contract has HTR
        buy_quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, buy_amount
        )
        buy_tokens = buy_quote["amount_received"]

        deposit = NCDepositAction(token_uid=HTR_UID, amount=buy_amount)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=buy_tokens)
        buy_ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", buy_ctx, self.token1_uid
        )

        initial_token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )

        # Now sell all of the tokens
        amount_in = buy_tokens

        # Calculate expected HTR out
        quote = self.runner.call_view_method(
            self.manager_id, "quote_sell", self.token1_uid, amount_in
        )

        htr_received = quote["amount_received"]
        fee_for_sell = quote["payed_fees"]

        self.assertGreaterEqual(max_amount_received_for_sell, htr_received)
        self.assertGreaterEqual(max_fee_for_sell, fee_for_sell)

        deposit = NCDepositAction(token_uid=self.token1_uid, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=HTR_UID, amount=htr_received)
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "sell_tokens", ctx, self.token1_uid
        )

        # Check transaction count and volume in token statistics
        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )

        self.assertEqual(
            token_info.transaction_count - initial_token_info.transaction_count, 1
        )

        self.assertEqual(token_info.total_volume, buy_amount + htr_received)
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(fee_for_sell, admin_info.collected_sell_fees)

        # Get the current pool and reserve values
        htr_collected_from_deviation = admin_info.collected_operation_fees
        token_reserve = token_info.token_reserve

        # The pool should be empty, because all tokens previously bought were sold
        self.assertEqual(token_info.virtual_pool, 0)

        self.assertEqual(
            htr_collected_from_deviation,
            initial_token_info.virtual_pool - htr_received - fee_for_sell,
        )
        self.assertEqual(token_reserve, initial_token_info.token_reserve + amount_in)

        # Now buy and sell again, but withdraw no tokens to simulate slippage protection

        deposit = NCDepositAction(token_uid=HTR_UID, amount=buy_amount)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=buy_tokens)
        buy_ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )
        self.runner.call_public_method(
            self.manager_id, "buy_tokens", buy_ctx, self.token1_uid
        )

        amount_in = buy_tokens // 5

        quote = self.runner.call_view_method(
            self.manager_id, "quote_sell", self.token1_uid, amount_in
        )

        deposit = NCDepositAction(token_uid=self.token1_uid, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=HTR_UID, amount=0)
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "sell_tokens", ctx, self.token1_uid
        )

        htr_balance = self.runner.call_view_method(
            self.manager_id,
            "get_user_token_balance",
            self.user_address,
            HTR_UID,
        )
        self.assertEqual(quote["amount_received"], htr_balance)

    def test_transaction_values(self) -> None:
        """Test values when buying and selling tokens"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1", self.user_address)

        testing_values = 500000
        payed_htr = math.ceil(
            testing_values * (1 + (CREATOR_FEE_RATE + BUY_FEE_RATE) / BASIS_POINTS)
        )
        last_token_purchase = None

        target_raised_htr = DEFAULT_MARKET_CAP // 5 + DEFAULT_GRADUATION_FEE

        total_tokens_purchased = 0

        for i in range((target_raised_htr - 1) // testing_values):
            # Each iterations should start from a different point in the curve
            if i > 0:
                start_purchase = payed_htr
                start_quote = self.runner.call_view_method(
                    self.manager_id, "quote_buy", self.token1_uid, start_purchase
                )
                deposit = NCDepositAction(token_uid=HTR_UID, amount=start_purchase)
                withdrawal = NCWithdrawalAction(
                    token_uid=self.token1_uid, amount=start_quote["amount_received"]
                )
                first_buy_ctx = self.create_context(
                    caller_id=self.user_address,
                    actions=[deposit, withdrawal],
                )

                self.runner.call_public_method(
                    self.manager_id, "buy_tokens", first_buy_ctx, self.token1_uid
                )

                total_tokens_purchased += start_quote["amount_received"]

            # Calculate how the virtual pool should change for a purchase
            change_on_virtual_pool = testing_values

            # Store how many tokens were purchased
            buy_quote = self.runner.call_view_method(
                self.manager_id, "quote_buy", self.token1_uid, payed_htr
            )
            tokens_exchanged = buy_quote["amount_received"]

            # Make sure the price per token increased
            if last_token_purchase:
                self.assertLess(tokens_exchanged, last_token_purchase)
            last_token_purchase = tokens_exchanged

            initial_token_info = self.runner.call_view_method(
                self.manager_id, "get_token_info", self.token1_uid
            )

            initial_admin_info = self.runner.call_view_method(
                self.manager_id, "get_platform_info"
            )

            initial_creator_balance = self.runner.call_view_method(
                self.manager_id, "get_user_token_balance", self.user_address, HTR_UID
            )

            deposit = NCDepositAction(token_uid=HTR_UID, amount=payed_htr)
            withdrawal = NCWithdrawalAction(
                token_uid=self.token1_uid, amount=tokens_exchanged
            )
            buy_ctx = self.create_context(
                caller_id=self.user_address,
                actions=[deposit, withdrawal],
            )

            total_tokens_purchased += tokens_exchanged

            self.runner.call_public_method(
                self.manager_id, "buy_tokens", buy_ctx, self.token1_uid
            )

            mid_admin_info = self.runner.call_view_method(
                self.manager_id, "get_platform_info"
            )

            mid_token_info = self.runner.call_view_method(
                self.manager_id, "get_token_info", self.token1_uid
            )

            mid_creator_balance = self.runner.call_view_method(
                self.manager_id, "get_user_token_balance", self.user_address, HTR_UID
            )

            real_buy_fee = (
                mid_admin_info.collected_buy_fees
                - initial_admin_info.collected_buy_fees
            )
            real_creator_reward = mid_creator_balance - initial_creator_balance
            collected_from_aproximations = (
                mid_admin_info.collected_operation_fees
                - initial_admin_info.collected_operation_fees
            )

            self.assertEqual(
                payed_htr,
                mid_token_info.virtual_pool
                - initial_token_info.virtual_pool
                + real_buy_fee
                + real_creator_reward
                + collected_from_aproximations,
            )

            # In the contract, the progress is calculated using floor division, but the virtual pool is maintained by the _correct_curve_deviation using ceiling division.
            # For that reason, the calculation may differ by 1
            self.assertGreaterEqual(
                1,
                abs(
                    (mid_token_info.virtual_pool * BASIS_POINTS // target_raised_htr)
                    - mid_token_info.progress
                ),
            )

            # Check if the total tokens available and the total tokens purchased total to 80% the total token supply

            maximum_buy_quote = self.runner.call_view_method(
                self.manager_id, "quote_buy", self.token1_uid, INFINITY
            )

            self.assertEqual(
                maximum_buy_quote["amount_received"],
                int(0.8 * INITIAL_TOKEN_RESERVE - total_tokens_purchased),
            )

            # Calculate how many HTR the user will receive for selling all his tokens
            # The final value can be less than the calculated due to ceiling division on both buy and sell methods
            # The difference between the real value and the expected one should be added to the virtual pool (no HTR is lost)
            should_sell_for = (
                change_on_virtual_pool * (BASIS_POINTS - SELL_FEE_RATE) // BASIS_POINTS
            )

            # Sell all the tokens purchased previously
            sell_quote = self.runner.call_view_method(
                self.manager_id, "quote_sell", self.token1_uid, tokens_exchanged
            )

            deposit = NCDepositAction(
                token_uid=self.token1_uid, amount=tokens_exchanged
            )
            withdrawal = NCWithdrawalAction(
                token_uid=HTR_UID, amount=sell_quote["amount_received"]
            )
            sell_ctx = self.create_context(
                caller_id=self.user_address,
                actions=[deposit, withdrawal],
            )

            self.runner.call_public_method(
                self.manager_id, "sell_tokens", sell_ctx, self.token1_uid
            )

            total_tokens_purchased -= tokens_exchanged

            final_token_info = self.runner.call_view_method(
                self.manager_id, "get_token_info", self.token1_uid
            )

            final_admin_info = self.runner.call_view_method(
                self.manager_id, "get_platform_info"
            )

            real_sell_fee = (
                final_admin_info.collected_sell_fees
                - mid_admin_info.collected_sell_fees
            )
            collected_from_aproximations = (
                final_admin_info.collected_operation_fees
                - initial_admin_info.collected_operation_fees
            )

            self.assertEqual(
                final_token_info.virtual_pool, initial_token_info.virtual_pool
            )
            self.assertEqual(
                payed_htr,
                sell_quote["amount_received"]
                + real_buy_fee
                + real_sell_fee
                + real_creator_reward
                + collected_from_aproximations,
            )

            # Verify slippage is minimal (due to ceiling division in buy/sell)
            self.assertGreaterEqual(should_sell_for, sell_quote["amount_received"])

    def test_bonding_curve(self) -> None:
        """Test the progress of the bonding curve as the token is purchased or sold"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1", self.user_address)

        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )

        self.assertEqual(token_info.progress, 0)

    def _reach_migration_threshold(self, token_uid):
        """Helper to reach migration threshold through multiple purchases"""

        # Get token info to access target_market_cap and virtual_pool
        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", token_uid
        )

        progress = token_info.progress
        while progress < BASIS_POINTS:
            amount_in = 4000000

            quote = self.runner.call_view_method(
                self.manager_id, "quote_buy", token_uid, amount_in
            )
            should_go_in = int(quote["total_payment"])
            expected_out = int(quote["amount_received"])

            deposit = NCDepositAction(token_uid=HTR_UID, amount=should_go_in)
            withdrawal = NCWithdrawalAction(token_uid=token_uid, amount=expected_out)
            ctx = self.create_context(
                caller_id=self.user_address,
                actions=[deposit, withdrawal],
            )

            self.runner.call_public_method(
                self.manager_id, "buy_tokens", ctx, token_uid
            )

            # Update token data after each transaction
            token_info = self.runner.call_view_method(
                self.manager_id, "get_token_info", token_uid
            )
            progress = token_info.progress

    def test_migration(self) -> None:
        """Test token migration to Dozer Pool"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        # Test migration if Khensu cannot sign a pool (should fail)
        ctx = self.create_context(
            caller_id=self.admin_address,
            actions=[],
        )

        self.runner.call_public_method(
            self.dozer_pool_manager_id,
            "remove_authorized_signer",
            ctx,
            self.manager_id,
        )

        with self.assertNCFail("Unauthorized"):
            self._reach_migration_threshold(self.token1_uid)

        # Make sure no pool was created for the token

        token_pools = self.runner.call_view_method(
            self.dozer_pool_manager_id,
            "get_pools_for_token",
            self.token1_uid,
        )

        self.assertEqual(token_pools, [])

        ctx = self.create_context(
            caller_id=self.admin_address,
            actions=[],
        )

        self.runner.call_public_method(
            self.dozer_pool_manager_id,
            "add_authorized_signer",
            ctx,
            self.manager_id,
        )

        # Get initial graduation fees
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        initial_graduation_fees = admin_info.collected_operation_fees

        self._reach_migration_threshold(self.token1_uid)

        # Verify migration state

        # Check if token is migrated using get_token_info
        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )
        self.assertTrue(token_info.is_migrated)
        platform_stats = self.runner.call_view_method(
            self.manager_id, "get_platform_stats"
        )
        self.assertEqual(token_info.market_cap, DEFAULT_MARKET_CAP)
        self.assertEqual(token_info.progress, BASIS_POINTS)
        self.assertEqual(platform_stats["total_tokens_migrated"], 1)
        self.assertIsNotNone(token_info.pool_key)

        # Check Pool Key
        token_pools = self.runner.call_view_method(
            self.dozer_pool_manager_id, "get_pools_for_token", self.token1_uid
        )
        self.assertTrue(token_info.pool_key in token_pools)

        # Check if pool was signed
        pool_info = self.runner.call_view_method(
            self.dozer_pool_manager_id, "pool_info", token_info.pool_key
        )
        self.assertTrue(pool_info.is_signed)

        # Verify graduation fees were collected
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        final_graduation_fees = admin_info.collected_operation_fees
        self.assertGreater(final_graduation_fees, initial_graduation_fees)

        # Try to get quotes - should fail
        with self.assertNCFail("InvalidState"):
            self.runner.call_view_method(
                self.manager_id, "quote_buy", self.token1_uid, 100000
            )

        with self.assertNCFail("InvalidState"):
            self.runner.call_view_method(
                self.manager_id, "quote_sell", self.token1_uid, 100000
            )

        # Try to buy and sell - should fail
        deposit = NCDepositAction(token_uid=HTR_UID, amount=10)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=0)
        buy_ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )
        with self.assertNCFail("InvalidState"):
            self.runner.call_public_method(
                self.manager_id, "buy_tokens", buy_ctx, self.token1_uid
            )

        deposit = NCDepositAction(token_uid=self.token1_uid, amount=100)
        withdrawal = NCWithdrawalAction(token_uid=HTR_UID, amount=0)
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        with self.assertNCFail("InvalidState"):
            self.runner.call_public_method(
                self.manager_id, "sell_tokens", ctx, self.token1_uid
            )

    def test_withdraw_fees(self) -> None:
        """Test fee withdrawal functionality"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        # Generate fees by making trades
        amount_in = 500000
        quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in
        )
        expected_out = quote["amount_received"]

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=expected_out)
        ctx_buy = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx_buy, self.token1_uid
        )

        # Verify fees were collected
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        collected_buy_fees = admin_info.collected_buy_fees
        self.assertGreater(collected_buy_fees, 0)

        # Non-admin should not be able to withdraw fees
        withdrawal = NCWithdrawalAction(token_uid=HTR_UID, amount=collected_buy_fees)
        ctx_non_admin = self.create_context(
            caller_id=self.user_address,
            actions=[withdrawal],
        )

        with self.assertNCFail("Unauthorized"):
            self.runner.call_public_method(
                self.manager_id, "withdraw_fees", ctx_non_admin
            )

        # Admin should be able to withdraw fees
        withdrawal = NCWithdrawalAction(token_uid=HTR_UID, amount=collected_buy_fees)
        ctx_admin = self.create_context(
            caller_id=self.admin_address,
            actions=[withdrawal],
        )

        self.runner.call_public_method(self.manager_id, "withdraw_fees", ctx_admin)

        # Verify fees were reset
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.collected_buy_fees, 0)

    def test_withdraw_fees_all_buckets(self) -> None:
        """Drain buy, sell, and operation (graduation) fees in one withdrawal."""
        self._initialize_manager()

        # token1 -> graduate: populates operation (graduation) fees + buy fees
        token1 = self._register_token("token1", "TK1")
        self._reach_migration_threshold(token1)

        # token2 -> buy then sell back: populates sell fees (and more buy fees)
        token2 = self._register_token("token2", "TK2")
        amount_in = 5_000_000
        buy_quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", token2, amount_in
        )
        expected_out = int(buy_quote["amount_received"])
        buy_ctx = self.create_context(
            caller_id=self.user_address,
            actions=[
                NCDepositAction(
                    token_uid=HTR_UID, amount=int(buy_quote["total_payment"])
                ),
                NCWithdrawalAction(token_uid=token2, amount=expected_out),
            ],
        )
        self.runner.call_public_method(self.manager_id, "buy_tokens", buy_ctx, token2)

        sell_amount = expected_out // 2
        sell_quote = self.runner.call_view_method(
            self.manager_id, "quote_sell", token2, sell_amount
        )
        sell_ctx = self.create_context(
            caller_id=self.user_address,
            actions=[
                NCDepositAction(token_uid=token2, amount=sell_amount),
                NCWithdrawalAction(
                    token_uid=HTR_UID, amount=int(sell_quote["amount_received"])
                ),
            ],
        )
        self.runner.call_public_method(self.manager_id, "sell_tokens", sell_ctx, token2)

        # All three buckets should be populated
        info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertGreater(info.collected_buy_fees, 0)
        self.assertGreater(info.collected_sell_fees, 0)
        self.assertGreater(info.collected_operation_fees, 0)

        total = (
            info.collected_buy_fees
            + info.collected_sell_fees
            + info.collected_operation_fees
        )

        # A single full withdrawal must drain the cascade across all three buckets
        ctx_admin = self.create_context(
            caller_id=self.admin_address,
            actions=[NCWithdrawalAction(token_uid=HTR_UID, amount=total)],
        )
        self.runner.call_public_method(self.manager_id, "withdraw_fees", ctx_admin)

        info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(info.collected_buy_fees, 0)
        self.assertEqual(info.collected_sell_fees, 0)
        self.assertEqual(info.collected_operation_fees, 0)

    def test_withdraw_fees_errors(self) -> None:
        """withdraw_fees rejects empty treasury, wrong token, and over-withdrawal."""
        self._initialize_manager()
        token1 = self._register_token("token1", "TK1")

        # Empty treasury: no trades yet -> no fees to withdraw
        with self.assertNCFail("InvalidState", "No fees to withdraw"):
            ctx = self.create_context(
                caller_id=self.admin_address,
                actions=[NCWithdrawalAction(token_uid=HTR_UID, amount=1)],
            )
            self.runner.call_public_method(self.manager_id, "withdraw_fees", ctx)

        # Generate fees with a buy
        amount_in = 500000
        quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", token1, amount_in
        )
        buy_ctx = self.create_context(
            caller_id=self.user_address,
            actions=[
                NCDepositAction(token_uid=HTR_UID, amount=int(quote["total_payment"])),
                NCWithdrawalAction(
                    token_uid=token1, amount=int(quote["amount_received"])
                ),
            ],
        )
        self.runner.call_public_method(self.manager_id, "buy_tokens", buy_ctx, token1)

        info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        total = (
            info.collected_buy_fees
            + info.collected_sell_fees
            + info.collected_operation_fees
        )

        # Wrong token: must be HTR
        with self.assertNCFail("NCFail", "Can only withdraw HTR"):
            ctx = self.create_context(
                caller_id=self.admin_address,
                actions=[NCWithdrawalAction(token_uid=token1, amount=1)],
            )
            self.runner.call_public_method(self.manager_id, "withdraw_fees", ctx)

        # Over-withdrawal beyond collected fees
        with self.assertNCFail("NCFail", "Invalid withdrawal amount"):
            ctx = self.create_context(
                caller_id=self.admin_address,
                actions=[NCWithdrawalAction(token_uid=HTR_UID, amount=total + 1)],
            )
            self.runner.call_public_method(self.manager_id, "withdraw_fees", ctx)

    def test_change_parameters(self) -> None:
        """Test changing contract parameters"""
        self._initialize_manager()

        ctx = self.create_context(caller_id=self.admin_address)

        # Change buy fee rate
        new_buy_fee = 300  # 3%
        self.runner.call_public_method(
            self.manager_id, "change_buy_fee_rate", ctx, new_buy_fee
        )

        # Change sell fee rate
        new_sell_fee = 400  # 4%
        self.runner.call_public_method(
            self.manager_id, "change_sell_fee_rate", ctx, new_sell_fee
        )

        # Change creator fee rate
        new_creator_fee = 200  # 2%
        self.runner.call_public_method(
            self.manager_id, "change_creator_fee_rate", ctx, new_creator_fee
        )

        # Change pool fee rate
        new_pool_fee = 40
        self.runner.call_public_method(
            self.manager_id, "change_pool_fee_rate", ctx, new_pool_fee
        )

        # Change bonding curve parameters
        new_target_cap = 80000
        new_token_total_supply = 1100000000
        new_graduation_fee = 2000

        self.runner.call_public_method(
            self.manager_id,
            "change_bonding_curve",
            ctx,
            new_target_cap,
            new_token_total_supply,
            new_graduation_fee,
        )

        # Verify parameters were changed
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.buy_fee_rate, new_buy_fee)
        self.assertEqual(admin_info.sell_fee_rate, new_sell_fee)
        self.assertEqual(admin_info.creator_fee_rate, new_creator_fee)
        self.assertEqual(admin_info.default_graduation_fee, new_graduation_fee)
        self.assertEqual(admin_info.default_target_market_cap, new_target_cap)
        self.assertEqual(admin_info.default_token_total_supply, new_token_total_supply)
        self.assertEqual(admin_info.default_pool_fee_rate, new_pool_fee)

        # Non-admin should not be able to change parameters
        ctx_non_admin = self.create_context(caller_id=self.user_address)

        with self.assertNCFail("Unauthorized"):
            self.runner.call_public_method(
                self.manager_id, "change_buy_fee_rate", ctx_non_admin, 500
            )

        with self.assertNCFail("Unauthorized"):
            self.runner.call_public_method(
                self.manager_id, "change_sell_fee_rate", ctx_non_admin, 500
            )

        with self.assertNCFail("Unauthorized"):
            self.runner.call_public_method(
                self.manager_id, "change_creator_fee_rate", ctx_non_admin, 500
            )

        with self.assertNCFail("Unauthorized"):
            self.runner.call_public_method(
                self.manager_id,
                "change_bonding_curve",
                ctx_non_admin,
                new_target_cap + 1,
                new_token_total_supply + 1,
                new_graduation_fee + 1,
            )

        # Invalid values should fail
        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id, "change_buy_fee_rate", ctx, -1
            )

        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id, "change_sell_fee_rate", ctx, -1
            )

        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id, "change_creator_fee_rate", ctx, -1
            )

        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id, "change_creator_fee_rate", ctx, 1001
            )

        # Test invalid bonding curve parameters
        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id,
                "change_bonding_curve",
                ctx,
                0,  # Invalid target market cap
                new_token_total_supply,
                new_graduation_fee,
            )

        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id,
                "change_bonding_curve",
                ctx,
                new_target_cap,
                0,  # Invalid token total supply
                new_graduation_fee,
            )

        with self.assertRaises(NCFail):
            self.runner.call_public_method(
                self.manager_id,
                "change_bonding_curve",
                ctx,
                new_target_cap,
                new_token_total_supply,
                -1,  # Invalid graduation fee
            )

    def test_manage_admin(self) -> None:
        """Test platform admin rights"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1", self.admin_address)

        new_admin = Address(self._get_any_address()[0])

        ctx = self.create_context(caller_id=self.admin_address)

        self.runner.call_public_method(self.manager_id, "add_admin", ctx, new_admin)

        # New admin should be able to manage the token
        ctx_new_admin = self.create_context(caller_id=new_admin)

        self.runner.call_public_method(
            self.manager_id, "change_buy_fee_rate", ctx_new_admin, 10
        )

        # Original admin cannot be removed
        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id,
                "remove_admin",
                ctx,
                self.admin_address,
            )

        # Remove the newly added admin
        self.runner.call_public_method(
            self.manager_id,
            "remove_admin",
            ctx,
            new_admin,
        )

        # Removed admin should no longer be able to manage the token
        with self.assertNCFail("Unauthorized"):
            self.runner.call_public_method(
                self.manager_id, "change_buy_fee_rate", ctx_new_admin, 10
            )

    def test_upgrade_only_creator(self) -> None:
        """Only the original contract creator may upgrade the blueprint."""
        self._initialize_manager()

        # Add a delegated admin (not the creator)
        new_admin = Address(self._get_any_address()[0])
        ctx_creator = self.create_context(caller_id=self.admin_address)
        self.runner.call_public_method(
            self.manager_id, "add_admin", ctx_creator, new_admin
        )

        # The delegated admin can manage parameters...
        ctx_new_admin = self.create_context(caller_id=new_admin)
        self.runner.call_public_method(
            self.manager_id, "change_buy_fee_rate", ctx_new_admin, 10
        )

        # ...but must NOT be able to upgrade the blueprint
        with self.assertNCFail("Unauthorized"):
            self.runner.call_public_method(
                self.manager_id,
                "upgrade_contract",
                ctx_new_admin,
                self.blueprint_id_khensu,
                "2.0.0",
            )

        # The creator can upgrade
        self.runner.call_public_method(
            self.manager_id,
            "upgrade_contract",
            ctx_creator,
            self.blueprint_id_khensu,
            "2.0.0",
        )
        version = self.runner.call_view_method(
            self.manager_id, "get_contract_version"
        )
        self.assertEqual(version, "2.0.0")

    def test_multi_token_management(self) -> None:
        """Test managing multiple tokens"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")
        self.token2_uid = self._register_token("token2", "TK2")

        # Verify both tokens are registered
        all_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 2, HTR_UID
        )
        self.assertSubstring(str(self.token1_uid.hex()), all_tokens)
        self.assertSubstring(str(self.token2_uid.hex()), all_tokens)

        # Verify that token with same symbol cannot be created
        with self.assertNCFail("NCTokenAlreadyExists"):
            self._register_token("token12", "TK1")

        # Buy tokens for each
        amount_in = 100000

        # Token 1
        quote1 = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in
        )
        expected_out1 = quote1["amount_received"]

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=expected_out1)
        ctx1 = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx1, self.token1_uid
        )

        # Token 2
        quote2 = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token2_uid, amount_in
        )
        expected_out2 = quote2["amount_received"]

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=self.token2_uid, amount=expected_out2)
        ctx2 = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx2, self.token2_uid
        )

        # Verify both tokens have updated state
        token1_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )
        token2_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token2_uid
        )

        self.assertEqual(token1_info.transaction_count, 1)
        self.assertEqual(token2_info.transaction_count, 1)

        # Get all tokens
        all_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 2, HTR_UID
        )

        self.assertSubstring(str(self.token1_uid.hex()), all_tokens)
        self.assertSubstring(str(self.token2_uid.hex()), all_tokens)

        # Get platform stats
        stats = self.runner.call_view_method(self.manager_id, "get_platform_stats")

        self.assertEqual(stats["total_tokens_created"], 2)
        self.assertEqual(stats["total_tokens_migrated"], 0)
        self.assertGreater(stats["platform_fees_collected"], 0)

    def test_quote_methods(self) -> None:
        """Test quote methods for buy and sell"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")
        token1_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )

        # Test quote_buy
        buy_amount = INFINITY
        buy_quote1 = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, buy_amount
        )

        self.assertIn("price_for_tokens", buy_quote1)
        self.assertIn("payed_fees", buy_quote1)
        self.assertIn("total_payment", buy_quote1)
        self.assertIn("amount_received", buy_quote1)
        self.assertIn("price_impact", buy_quote1)
        self.assertGreater(buy_amount, buy_quote1["total_payment"])
        self.assertEqual(
            buy_quote1["amount_received"], int(0.8 * INITIAL_TOKEN_RESERVE)
        )
        self.assertEqual(
            buy_quote1["price_for_tokens"] + buy_quote1["payed_fees"],
            buy_quote1["total_payment"],
        )
        # The price impact should be compatible with the target market cap value, in relation to the initial value
        self.assertLessEqual(
            (DEFAULT_MARKET_CAP - token1_info.market_cap)
            * BASIS_POINTS
            // token1_info.market_cap
            - buy_quote1["price_impact"],
            1,
        )

        buy_amount = buy_quote1["total_payment"]
        buy_quote2 = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, buy_amount
        )
        self.assertEqual(buy_amount, buy_quote2["total_payment"])
        self.assertEqual(buy_quote1["amount_received"], buy_quote2["amount_received"])
        self.assertEqual(buy_quote1["price_impact"], buy_quote2["price_impact"])

        buy_amount = buy_amount - 1
        buy_quote3 = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, buy_amount
        )
        self.assertGreater(buy_quote1["amount_received"], buy_quote3["amount_received"])

        # Test quote_sell
        token_amount = 100000
        sell_quote = self.runner.call_view_method(
            self.manager_id, "quote_sell", self.token1_uid, token_amount
        )

        self.assertIn("tokens_sell_for", sell_quote)
        self.assertIn("payed_fees", sell_quote)
        self.assertIn("amount_received", sell_quote)
        self.assertIn("tokens_sold", sell_quote)
        self.assertIn("price_impact", sell_quote)

        self.assertEqual(
            sell_quote["tokens_sell_for"] - sell_quote["payed_fees"],
            sell_quote["amount_received"],
        )

    def test_get_token_info(self) -> None:
        """Test getting token information"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )

        # Verify values
        self.assertEqual(token_info.creator, self.admin_address.hex())
        self.assertEqual(token_info.progress, 0)
        self.assertEqual(token_info.token_reserve, INITIAL_TOKEN_RESERVE)
        self.assertEqual(token_info.total_supply, INITIAL_TOKEN_RESERVE)
        self.assertEqual(token_info.is_migrated, False)

        # Test non-existent token
        random_token_uid = self.gen_random_token_uid()
        with self.assertNCFail("TokenNotFound"):
            self.runner.call_view_method(
                self.manager_id, "get_token_info", random_token_uid
            )

    def test_user_balances(self) -> None:
        """Test user balance tracking from slippage"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        # Initially zero balance
        token_balance = self.runner.call_view_method(
            self.manager_id,
            "get_user_token_balance",
            self.user_address,
            self.token1_uid,
        )
        htr_balance = self.runner.call_view_method(
            self.manager_id, "get_user_token_balance", self.user_address, HTR_UID
        )

        self.assertEqual(token_balance, 0)
        self.assertEqual(htr_balance, 0)

        # Buy tokens with slippage
        amount_in = 100000
        quote_buy = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in
        )

        # Request less than available (to create slippage)
        expected_out = int(quote_buy["amount_received"] * 0.9)  # 90% of available

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=expected_out)
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx, self.token1_uid
        )

        # Check updated balance (should have slippage amount)
        first_balance = self.runner.call_view_method(
            self.manager_id,
            "get_user_token_balance",
            self.user_address,
            self.token1_uid,
        )
        self.assertEqual(first_balance, quote_buy["amount_received"] - expected_out)

        # Repeat the process for sell_tokens

        sell_amount = int(expected_out * 0.5)

        quote_sell = self.runner.call_view_method(
            self.manager_id, "quote_sell", self.token1_uid, sell_amount
        )

        decreased_output = int(quote_sell["amount_received"] * 0.8)  # 80% of available

        deposit = NCDepositAction(token_uid=self.token1_uid, amount=sell_amount)
        withdrawal = NCWithdrawalAction(token_uid=HTR_UID, amount=decreased_output)
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "sell_tokens", ctx, self.token1_uid
        )

        # Check updated balance (should have slippage amount)
        second_balance = self.runner.call_view_method(
            self.manager_id, "get_user_token_balance", self.user_address, HTR_UID
        )
        self.assertEqual(
            second_balance, quote_sell["amount_received"] - decreased_output
        )

    def test_creator_fee_balance(self) -> None:
        """Test that creator fees are tracked in token creator's HTR balance"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1", self.admin_address)

        # Check initial creator balance is zero
        creator_htr_balance = self.runner.call_view_method(
            self.manager_id, "get_user_token_balance", self.admin_address, HTR_UID
        )
        self.assertEqual(creator_htr_balance, 0)

        # Buy tokens (different user buying)
        pay_for_tokens = 1000000
        buy_fee = math.ceil(pay_for_tokens * (BUY_FEE_RATE) / BASIS_POINTS)
        creator_fee = (
            math.ceil(pay_for_tokens * (BUY_FEE_RATE + CREATOR_FEE_RATE) / BASIS_POINTS)
            - buy_fee
        )
        amount_in = pay_for_tokens + buy_fee + creator_fee

        quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in
        )

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(
            token_uid=self.token1_uid, amount=quote["amount_received"]
        )
        ctx = self.create_context(
            caller_id=self.user_address,  # Different user from creator
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx, self.token1_uid
        )

        # Creator should have received creator fee
        creator_htr_balance = self.runner.call_view_method(
            self.manager_id, "get_user_token_balance", self.admin_address, HTR_UID
        )
        self.assertEqual(creator_htr_balance, creator_fee)

        # Buyer should NOT have any HTR balance (only token slippage if any)
        buyer_htr_balance = self.runner.call_view_method(
            self.manager_id, "get_user_token_balance", self.user_address, HTR_UID
        )
        self.assertEqual(buyer_htr_balance, 0)

    def test_lru_cache_initialization(self) -> None:
        """Test LRU cache is properly initialized"""
        self._initialize_manager()

        # Check LRU cache capacity
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.lru_cache_capacity, LRU_CACHE_CAPACITY)

        # Check initial LRU cache size is 0
        self.assertEqual(admin_info.lru_cache_size, 0)

    def test_lru_cache_updates_on_operations(self) -> None:
        """Test LRU cache updates when tokens are registered and traded"""
        self._initialize_manager()

        # Register first token
        self.token1_uid = self._register_token("token1", "TK1")

        # LRU cache size should be 1
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.lru_cache_size, 1)

        # get_last_n_tokens should return token1
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 1, HTR_UID
        )
        self.assertEqual(last_tokens, self.token1_uid.hex())

        # Register second token
        self.token2_uid = self._register_token("token2", "TK2")

        # LRU cache size should be 2
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.lru_cache_size, 2)

        # get_last_n_tokens should return token2 first (most recent)
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 2, HTR_UID
        )
        tokens_list = last_tokens.split()
        self.assertEqual(tokens_list[0], self.token2_uid.hex())
        self.assertEqual(tokens_list[1], self.token1_uid.hex())

        # Buy token1 - should move it to front of LRU
        amount_in = 100000
        quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in
        )

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(
            token_uid=self.token1_uid, amount=quote["amount_received"]
        )
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx, self.token1_uid
        )

        # Now token1 should be first (most recent)
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 2, HTR_UID
        )
        tokens_list = last_tokens.split()
        self.assertEqual(tokens_list[0], self.token1_uid.hex())
        self.assertEqual(tokens_list[1], self.token2_uid.hex())

    def test_lru_cache_capacity_and_eviction(self) -> None:
        """Test LRU cache eviction when capacity is reached"""
        self._initialize_manager()

        # Set a small capacity for testing
        ctx = self.create_context(caller_id=self.admin_address)

        # Change capacity to 3
        self.runner.call_public_method(self.manager_id, "change_lru_capacity", ctx, 3)

        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.lru_cache_capacity, 3)

        # Register 3 tokens
        token1 = self._register_token("token1", "TK1")
        token2 = self._register_token("token2", "TK2")
        token3 = self._register_token("token3", "TK3")

        # Cache size should be 3
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.lru_cache_size, 3)

        # get_last_n_tokens should return all 3 in reverse order
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 3, HTR_UID
        )
        tokens_list = last_tokens.split()
        self.assertEqual(len(tokens_list), 3)
        self.assertEqual(tokens_list[0], token3.hex())
        self.assertEqual(tokens_list[1], token2.hex())
        self.assertEqual(tokens_list[2], token1.hex())

        # Register 4th token - should evict token1 (oldest)
        token4 = self._register_token("token4", "TK4")

        # Cache size should still be 3
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.lru_cache_size, 3)

        # get_last_n_tokens should NOT contain token1 anymore
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 4, HTR_UID
        )
        tokens_list = last_tokens.split()
        self.assertEqual(len(tokens_list), 3)
        self.assertNotIn(token1.hex(), tokens_list)
        self.assertEqual(tokens_list[0], token4.hex())
        self.assertEqual(tokens_list[1], token3.hex())
        self.assertEqual(tokens_list[2], token2.hex())

    def test_change_lru_capacity(self) -> None:
        """Test changing LRU cache capacity"""
        self._initialize_manager()

        # Register 5 tokens
        tokens = []
        for i in range(5):
            token = self._register_token(f"token{i}", f"TK{i}")
            tokens.append(token)

        # Cache size should be 5
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.lru_cache_size, 5)

        # Reduce capacity to 3 (should evict 2 oldest)
        ctx = self.create_context(caller_id=self.admin_address)

        self.runner.call_public_method(self.manager_id, "change_lru_capacity", ctx, 3)

        # Cache size should now be 3
        ctx = self.create_context(caller_id=self.admin_address)
        admin_info = self.runner.call_view_method(self.manager_id, "get_platform_info")
        self.assertEqual(admin_info.lru_cache_size, 3)
        self.assertEqual(admin_info.lru_cache_capacity, 3)

        # get_last_n_tokens should return only 3 most recent
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 5, HTR_UID
        )
        tokens_list = last_tokens.split()
        self.assertEqual(len(tokens_list), 3)
        # Should contain token4, token3, token2 (most recent 3)
        self.assertEqual(tokens_list[0], tokens[4].hex())
        self.assertEqual(tokens_list[1], tokens[3].hex())
        self.assertEqual(tokens_list[2], tokens[2].hex())

        # Non-admin should not be able to change capacity
        ctx_non_admin = self.create_context(caller_id=self.user_address)

        with self.assertNCFail("Unauthorized"):
            self.runner.call_public_method(
                self.manager_id, "change_lru_capacity", ctx_non_admin, 10
            )

        # Invalid capacity should fail
        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id, "change_lru_capacity", ctx, 0
            )

        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id, "change_lru_capacity", ctx, -1
            )

    def test_lru_get_last_n_tokens(self) -> None:
        """Test get_last_n_tokens returns tokens in LRU order and supports pagination"""
        self._initialize_manager()

        # Register 5 tokens
        tokens = []
        for i in range(5):
            token = self._register_token(f"token{i}", f"TK{i}")
            tokens.append(token)

        # Initial order: token4, token3, token2, token1, token0 (reverse registration order)
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 5, HTR_UID
        )
        tokens_list = last_tokens.split()
        self.assertEqual(len(tokens_list), 5)
        self.assertEqual(tokens_list[0], tokens[4].hex())
        self.assertEqual(tokens_list[1], tokens[3].hex())
        self.assertEqual(tokens_list[2], tokens[2].hex())
        self.assertEqual(tokens_list[3], tokens[1].hex())
        self.assertEqual(tokens_list[4], tokens[0].hex())

        # Buy token1 - moves it to front
        amount_in = 100000
        quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", tokens[1], amount_in
        )

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(
            token_uid=tokens[1], amount=quote["amount_received"]
        )
        ctx_buy = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx_buy, tokens[1]
        )

        # New order: token1, token4, token3, token2, token0
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 5, HTR_UID
        )
        tokens_list = last_tokens.split()
        self.assertEqual(tokens_list[0], tokens[1].hex())
        self.assertEqual(tokens_list[1], tokens[4].hex())
        self.assertEqual(tokens_list[2], tokens[3].hex())
        self.assertEqual(tokens_list[3], tokens[2].hex())
        self.assertEqual(tokens_list[4], tokens[0].hex())

        # Buy token2 - moves it to front
        quote = self.runner.call_view_method(
            self.manager_id, "quote_buy", tokens[2], amount_in
        )

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(
            token_uid=tokens[2], amount=quote["amount_received"]
        )
        ctx_buy = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx_buy, tokens[2]
        )

        # New order: token2, token1, token4, token3, token0
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 5, HTR_UID
        )
        tokens_list = last_tokens.split()
        self.assertEqual(tokens_list[0], tokens[2].hex())
        self.assertEqual(tokens_list[1], tokens[1].hex())
        self.assertEqual(tokens_list[2], tokens[4].hex())
        self.assertEqual(tokens_list[3], tokens[3].hex())
        self.assertEqual(tokens_list[4], tokens[0].hex())

        # Test pagination with offset - get first 2 tokens
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 2, HTR_UID
        )
        tokens_list = last_tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], tokens[2].hex())  # token2 (most recent)
        self.assertEqual(tokens_list[1], tokens[1].hex())  # token1

        # Get next 2 tokens using offset (skip token2)
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 2, tokens[2]
        )
        tokens_list = last_tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], tokens[1].hex())  # token1
        self.assertEqual(tokens_list[1], tokens[4].hex())  # token4

        # Get next 2 tokens using offset (skip token2 and token1)
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 2, tokens[1]
        )
        tokens_list = last_tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], tokens[4].hex())  # token4
        self.assertEqual(tokens_list[1], tokens[3].hex())  # token3

        # Get remaining token using offset
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 5, tokens[4]
        )
        tokens_list = last_tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], tokens[3].hex())  # token3
        self.assertEqual(tokens_list[1], tokens[0].hex())  # token0

        # Test getting fewer tokens than available
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 1, HTR_UID
        )
        self.assertEqual(last_tokens, tokens[2].hex())

        # Test getting 0 tokens
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 0, HTR_UID
        )
        self.assertEqual(last_tokens, "")

        # Test negative number (should return empty)
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", -1, HTR_UID
        )
        self.assertEqual(last_tokens, "")

        # Test with invalid offset (token not in LRU)
        random_token_uid = self.gen_random_token_uid()
        last_tokens = self.runner.call_view_method(
            self.manager_id, "get_last_n_tokens", 3, random_token_uid
        )
        # Should return all tokens from head since offset is invalid
        tokens_list = last_tokens.split()
        self.assertEqual(len(tokens_list), 3)
        self.assertEqual(tokens_list[0], tokens[2].hex())

    def test_get_newest_n_tokens(self) -> None:
        """Test get_newest_n_tokens returns newly created tokens in reverse chronological order"""
        self._initialize_manager()

        # Register 5 tokens
        tokens = []
        for i in range(5):
            token = self._register_token(f"token{i}", f"TK{i}")
            tokens.append(token)

        # Get all tokens (newest first)
        newest_tokens = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", 5, 0
        )
        tokens_list = newest_tokens.split()
        self.assertEqual(len(tokens_list), 5)
        # Should be in reverse order (newest first)
        self.assertEqual(tokens_list[0], tokens[4].hex())
        self.assertEqual(tokens_list[1], tokens[3].hex())
        self.assertEqual(tokens_list[2], tokens[2].hex())
        self.assertEqual(tokens_list[3], tokens[1].hex())
        self.assertEqual(tokens_list[4], tokens[0].hex())

        # Get first 2 newest tokens
        newest_tokens = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", 2, 0
        )
        tokens_list = newest_tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], tokens[4].hex())
        self.assertEqual(tokens_list[1], tokens[3].hex())

        # Get next 2 tokens with offset=2
        newest_tokens = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", 2, 2
        )
        tokens_list = newest_tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], tokens[2].hex())
        self.assertEqual(tokens_list[1], tokens[1].hex())

        # Get remaining token with offset=4
        newest_tokens = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", 2, 4
        )
        tokens_list = newest_tokens.split()
        self.assertEqual(len(tokens_list), 1)
        self.assertEqual(tokens_list[0], tokens[0].hex())

        # Test getting 0 tokens
        newest_tokens = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", 0, 0
        )
        self.assertEqual(newest_tokens, "")

        # Test negative number (should return empty)
        newest_tokens = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", -5, 0
        )
        self.assertEqual(newest_tokens, "")

        # Test negative offset (should ignore offset)
        newest_tokens = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", 2, -1
        )
        correct_output = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", 2, -1
        )
        self.assertEqual(newest_tokens, correct_output)

        # Test offset beyond list size
        newest_tokens = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", 5, 10
        )
        self.assertEqual(newest_tokens, "")

        # Test large number with offset
        newest_tokens = self.runner.call_view_method(
            self.manager_id, "get_newest_n_tokens", 100, 1
        )
        tokens_list = newest_tokens.split()
        # Should only return remaining 4 tokens (offset=1 skips the newest)
        self.assertEqual(len(tokens_list), 4)

    def test_get_oldest_n_tokens(self) -> None:
        """Test get_oldest_n_tokens returns oldest created tokens in chronological order"""
        self._initialize_manager()

        # Register 5 tokens
        tokens = []
        for i in range(5):
            token = self._register_token(f"token{i}", f"TK{i}")
            tokens.append(token)

        # Get all tokens (oldest first)
        oldest_tokens = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", 5, 0
        )
        tokens_list = oldest_tokens.split()
        self.assertEqual(len(tokens_list), 5)
        # Should be in chronological order (oldest first)
        self.assertEqual(tokens_list[0], tokens[0].hex())
        self.assertEqual(tokens_list[1], tokens[1].hex())
        self.assertEqual(tokens_list[2], tokens[2].hex())
        self.assertEqual(tokens_list[3], tokens[3].hex())
        self.assertEqual(tokens_list[4], tokens[4].hex())

        # Get first 2 oldest tokens
        oldest_tokens = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", 2, 0
        )
        tokens_list = oldest_tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], tokens[0].hex())
        self.assertEqual(tokens_list[1], tokens[1].hex())

        # Get next 2 tokens with offset=2
        oldest_tokens = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", 2, 2
        )
        tokens_list = oldest_tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], tokens[2].hex())
        self.assertEqual(tokens_list[1], tokens[3].hex())

        # Get remaining token with offset=4
        oldest_tokens = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", 2, 4
        )
        tokens_list = oldest_tokens.split()
        self.assertEqual(len(tokens_list), 1)
        self.assertEqual(tokens_list[0], tokens[4].hex())

        # Test getting 0 tokens
        oldest_tokens = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", 0, 0
        )
        self.assertEqual(oldest_tokens, "")

        # Test negative number (should return empty)
        oldest_tokens = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", -5, 0
        )
        self.assertEqual(oldest_tokens, "")

        # Test negative offset (should ignore the offset)
        oldest_tokens = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", 2, -1
        )
        corrent_output = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", 2, 0
        )
        self.assertEqual(oldest_tokens, corrent_output)

        # Test offset beyond list size
        oldest_tokens = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", 5, 10
        )
        self.assertEqual(oldest_tokens, "")

        # Test large number with offset
        oldest_tokens = self.runner.call_view_method(
            self.manager_id, "get_oldest_n_tokens", 100, 1
        )
        tokens_list = oldest_tokens.split()
        # Should only return remaining 4 tokens (offset=1 skips the oldest)
        self.assertEqual(len(tokens_list), 4)

    def test_post_migration_quotes(self) -> None:
        """Test front_quote methods work correctly after token migration"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        # Before migration, these methods should fail
        with self.assertNCFail("InvalidState"):
            self.runner.call_view_method(
                self.manager_id,
                "front_quote_exact_tokens_for_tokens",
                self.token1_uid,
                100000,
                HTR_UID,
            )

        with self.assertNCFail("InvalidState"):
            self.runner.call_view_method(
                self.manager_id,
                "front_quote_tokens_for_exact_tokens",
                self.token1_uid,
                100000,
                HTR_UID,
            )

        # Reach migration threshold
        self._reach_migration_threshold(self.token1_uid)

        # Verify token is migrated and get pool reserves
        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )
        self.assertTrue(token_info.is_migrated)

        # After migration, the Dozer pool reserves are ordered by token UID
        # Get the actual reserves from Dozer to know the correct ordering
        reserves = self.runner.call_view_method(
            self.dozer_pool_manager_id,
            "get_reserves",
            self.token1_uid,
            HTR_UID,
            10,  # FEE
        )
        reserve_a, reserve_b = reserves

        # Determine which is token and which is HTR based on ordering
        # Tokens are ordered: if token1_uid < HTR_UID, then reserve_a=token, reserve_b=HTR
        if self.token1_uid < HTR_UID:
            reserve_token = reserve_a
            reserve_htr = reserve_b
        else:
            reserve_token = reserve_b
            reserve_htr = reserve_a

        # Dozer fee: 10/1000 = 1%
        fee_numerator = 10
        fee_denominator = 1000
        fee_multiplier = fee_denominator - fee_numerator  # 990

        # Test 1: front_quote_exact_tokens_for_tokens for buying (HTR -> Token)
        # Given exact HTR in, calculate token out
        htr_amount = 50000
        # Formula: amount_out = (reserve_out * amount_in * (1000-10)) // (reserve_in * 1000 + amount_in * (1000-10))
        expected_token_out = (reserve_token * htr_amount * fee_multiplier) // (
            reserve_htr * fee_denominator + htr_amount * fee_multiplier
        )

        quote_buy = self.runner.call_view_method(
            self.manager_id,
            "front_quote_exact_tokens_for_tokens",
            self.token1_uid,
            htr_amount,
            HTR_UID,
        )

        self.assertIn("amount_out", quote_buy)
        self.assertEqual(quote_buy["amount_out"], expected_token_out)

        # Test 2: front_quote_exact_tokens_for_tokens for selling (Token -> HTR)
        # Given exact token in, calculate HTR out
        token_amount = 10000
        expected_htr_out = (reserve_htr * token_amount * fee_multiplier) // (
            reserve_token * fee_denominator + token_amount * fee_multiplier
        )

        quote_sell = self.runner.call_view_method(
            self.manager_id,
            "front_quote_exact_tokens_for_tokens",
            self.token1_uid,
            token_amount,
            self.token1_uid,
        )

        self.assertIn("amount_out", quote_sell)
        self.assertEqual(quote_sell["amount_out"], expected_htr_out)

        # Test 3: front_quote_tokens_for_exact_tokens for buying (HTR -> Token)
        # Given exact token out desired, calculate HTR in needed
        desired_tokens = 5000
        # Formula: amount_in = ceil_div(reserve_in * amount_out * fee_denominator, (reserve_out - amount_out) * fee_multiplier)
        numerator = reserve_htr * desired_tokens * fee_denominator
        denominator = (reserve_token - desired_tokens) * fee_multiplier
        # Ceiling division
        expected_htr_in = (numerator + denominator - 1) // denominator

        quote_buy_exact = self.runner.call_view_method(
            self.manager_id,
            "front_quote_tokens_for_exact_tokens",
            self.token1_uid,
            desired_tokens,
            HTR_UID,
        )

        self.assertIn("amount_in", quote_buy_exact)
        self.assertEqual(quote_buy_exact["amount_in"], expected_htr_in)

        # Test 4: front_quote_tokens_for_exact_tokens for selling (Token -> HTR)
        # Given exact HTR out desired, calculate token in needed
        desired_htr = 5000
        numerator = reserve_token * desired_htr * fee_denominator
        denominator = (reserve_htr - desired_htr) * fee_multiplier
        # Ceiling division
        expected_token_in = (numerator + denominator - 1) // denominator

        quote_sell_exact = self.runner.call_view_method(
            self.manager_id,
            "front_quote_tokens_for_exact_tokens",
            self.token1_uid,
            desired_htr,
            self.token1_uid,
        )

        self.assertIn("amount_in", quote_sell_exact)
        self.assertEqual(quote_sell_exact["amount_in"], expected_token_in)

        # Test with invalid token_in parameter
        random_token = self.gen_random_token_uid()
        with self.assertNCFail("InvalidParameters"):
            self.runner.call_view_method(
                self.manager_id,
                "front_quote_exact_tokens_for_tokens",
                self.token1_uid,
                100000,
                random_token,
            )

        with self.assertNCFail("InvalidParameters"):
            self.runner.call_view_method(
                self.manager_id,
                "front_quote_tokens_for_exact_tokens",
                self.token1_uid,
                100000,
                random_token,
            )

    def test_post_migration_quote_non_existent_token(self) -> None:
        """Test post-migration quote methods fail for non-existent tokens"""
        self._initialize_manager()

        random_token_uid = self.gen_random_token_uid()

        with self.assertNCFail("TokenNotFound"):
            self.runner.call_view_method(
                self.manager_id,
                "front_quote_exact_tokens_for_tokens",
                random_token_uid,
                100000,
                HTR_UID,
            )

        with self.assertNCFail("TokenNotFound"):
            self.runner.call_view_method(
                self.manager_id,
                "front_quote_tokens_for_exact_tokens",
                random_token_uid,
                100000,
                HTR_UID,
            )

    def test_withdraw_from_balance(self) -> None:
        """Test withdrawing tokens from user slippage balance"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        # Buy tokens with slippage to create a balance
        amount_in = 100000
        quote_buy = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in
        )

        # Request less than available (to create slippage)
        expected_out = int(quote_buy["amount_received"] * 0.9)  # 90% of available
        slippage_amount = quote_buy["amount_received"] - expected_out

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=expected_out)
        ctx = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )

        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx, self.token1_uid
        )

        # Verify slippage was recorded
        balance_before = self.runner.call_view_method(
            self.manager_id,
            "get_user_token_balance",
            self.user_address,
            self.token1_uid,
        )
        self.assertEqual(balance_before, slippage_amount)

        # Withdraw partial amount from balance
        partial_withdrawal = slippage_amount // 2
        withdrawal_action = NCWithdrawalAction(
            token_uid=self.token1_uid, amount=partial_withdrawal
        )
        ctx_withdraw = self.create_context(
            caller_id=self.user_address,
            actions=[withdrawal_action],
        )

        self.runner.call_public_method(
            self.manager_id, "withdraw_from_balance", ctx_withdraw
        )

        # Verify balance decreased
        balance_after = self.runner.call_view_method(
            self.manager_id,
            "get_user_token_balance",
            self.user_address,
            self.token1_uid,
        )
        self.assertEqual(balance_after, slippage_amount - partial_withdrawal)

        # Withdraw remaining balance
        remaining = balance_after
        withdrawal_action = NCWithdrawalAction(
            token_uid=self.token1_uid, amount=remaining
        )
        ctx_withdraw_all = self.create_context(
            caller_id=self.user_address,
            actions=[withdrawal_action],
        )

        self.runner.call_public_method(
            self.manager_id, "withdraw_from_balance", ctx_withdraw_all
        )

        # Verify balance is now zero
        final_balance = self.runner.call_view_method(
            self.manager_id,
            "get_user_token_balance",
            self.user_address,
            self.token1_uid,
        )
        self.assertEqual(final_balance, 0)

        # Test trying to withdraw more than balance
        withdrawal_action = NCWithdrawalAction(token_uid=self.token1_uid, amount=100)
        ctx_over_withdraw = self.create_context(
            caller_id=self.user_address,
            actions=[withdrawal_action],
        )

        with self.assertNCFail("InsufficientAmount"):
            self.runner.call_public_method(
                self.manager_id, "withdraw_from_balance", ctx_over_withdraw
            )

        # Test trying to withdraw zero amount
        withdrawal_action = NCWithdrawalAction(token_uid=self.token1_uid, amount=0)
        ctx_zero_withdraw = self.create_context(
            caller_id=self.user_address,
            actions=[withdrawal_action],
        )

        with self.assertNCFail("InvalidParameters"):
            self.runner.call_public_method(
                self.manager_id, "withdraw_from_balance", ctx_zero_withdraw
            )

    def test_get_recently_graduated_tokens(self) -> None:
        """Test get_recently_graduated_tokens returns graduated tokens in reverse order"""
        self._initialize_manager()

        # Initially no graduated tokens
        graduated = self.runner.call_view_method(
            self.manager_id, "get_recently_graduated_tokens", 5, 0
        )
        self.assertEqual(graduated, "")

        # Create and migrate first token
        self.token1_uid = self._register_token("token1", "TK1")
        self._reach_migration_threshold(self.token1_uid)

        # Verify token1 is in graduated list
        graduated = self.runner.call_view_method(
            self.manager_id, "get_recently_graduated_tokens", 5, 0
        )
        self.assertEqual(graduated, self.token1_uid.hex())

        # Create and migrate second token
        self.token2_uid = self._register_token("token2", "TK2")
        self._reach_migration_threshold(self.token2_uid)

        # Verify both tokens are in graduated list (newest first)
        graduated = self.runner.call_view_method(
            self.manager_id, "get_recently_graduated_tokens", 5, 0
        )
        tokens_list = graduated.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], self.token2_uid.hex())  # Most recent first
        self.assertEqual(tokens_list[1], self.token1_uid.hex())

        # Test pagination - get first token only
        graduated = self.runner.call_view_method(
            self.manager_id, "get_recently_graduated_tokens", 1, 0
        )
        self.assertEqual(graduated, self.token2_uid.hex())

        # Test pagination - skip first, get second
        graduated = self.runner.call_view_method(
            self.manager_id, "get_recently_graduated_tokens", 1, 1
        )
        self.assertEqual(graduated, self.token1_uid.hex())

        # Test offset beyond list
        graduated = self.runner.call_view_method(
            self.manager_id, "get_recently_graduated_tokens", 5, 10
        )
        self.assertEqual(graduated, "")

        # Test with 0 number
        graduated = self.runner.call_view_method(
            self.manager_id, "get_recently_graduated_tokens", 0, 0
        )
        self.assertEqual(graduated, "")

        # Test negative number (should return empty)
        graduated = self.runner.call_view_method(
            self.manager_id, "get_recently_graduated_tokens", -1, 0
        )
        self.assertEqual(graduated, "")

    def test_get_tokens_created_by_user(self) -> None:
        """Test get_tokens_created_by_user returns user's tokens in reverse order"""
        self._initialize_manager()

        # Initially no tokens created by user
        tokens = self.runner.call_view_method(
            self.manager_id, "get_tokens_created_by_user", self.user_address, 5, 0
        )
        self.assertEqual(tokens, "")

        # Create tokens with different creators
        token1 = self._register_token("token1", "TK1", self.admin_address)
        token2 = self._register_token("token2", "TK2", self.user_address)
        token3 = self._register_token("token3", "TK3", self.user_address)
        token4 = self._register_token("token4", "TK4", self.admin_address)

        # Get tokens created by user_address (should be token2, token3)
        tokens = self.runner.call_view_method(
            self.manager_id, "get_tokens_created_by_user", self.user_address, 5, 0
        )
        tokens_list = tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], token3.hex())  # Most recent first
        self.assertEqual(tokens_list[1], token2.hex())

        # Get tokens created by admin_address (should be token1, token4)
        tokens = self.runner.call_view_method(
            self.manager_id, "get_tokens_created_by_user", self.admin_address, 5, 0
        )
        tokens_list = tokens.split()
        self.assertEqual(len(tokens_list), 2)
        self.assertEqual(tokens_list[0], token4.hex())  # Most recent first
        self.assertEqual(tokens_list[1], token1.hex())

        # Test pagination - get 1 token with offset
        tokens = self.runner.call_view_method(
            self.manager_id, "get_tokens_created_by_user", self.user_address, 1, 0
        )
        self.assertEqual(tokens, token3.hex())

        tokens = self.runner.call_view_method(
            self.manager_id, "get_tokens_created_by_user", self.user_address, 1, 1
        )
        self.assertEqual(tokens, token2.hex())

        # Test offset beyond list
        tokens = self.runner.call_view_method(
            self.manager_id, "get_tokens_created_by_user", self.user_address, 5, 10
        )
        self.assertEqual(tokens, "")

        # Test with non-existent user
        random_address = Address(self._get_any_address()[0])
        tokens = self.runner.call_view_method(
            self.manager_id, "get_tokens_created_by_user", random_address, 5, 0
        )
        self.assertEqual(tokens, "")

        # Test with 0 number
        tokens = self.runner.call_view_method(
            self.manager_id, "get_tokens_created_by_user", self.user_address, 0, 0
        )
        self.assertEqual(tokens, "")

        # Test negative number (should return empty)
        tokens = self.runner.call_view_method(
            self.manager_id, "get_tokens_created_by_user", self.user_address, -1, 0
        )
        self.assertEqual(tokens, "")

    def test_get_user_balance(self) -> None:
        """Test get_user_balance returns all token balances for a user"""
        self._initialize_manager()

        # Create token with user_address as creator so they receive creator fees
        self.token1_uid = self._register_token("token1", "TK1", self.user_address)
        # Create token with admin as creator
        self.token2_uid = self._register_token("token2", "TK2", self.admin_address)

        # Initially user has no balance (default HTR with 0)
        balance = self.runner.call_view_method(
            self.manager_id, "get_user_balance", self.user_address, 2, 0
        )
        self.assertEqual(balance, HTR_UID.hex() + "_0")

        # Another user buys token1 - creator (user_address) should receive creator fee
        buyer_address = Address(self._get_any_address()[0])
        pay_for_tokens = 1000000
        buy_fee = math.ceil(pay_for_tokens * (BUY_FEE_RATE) / BASIS_POINTS)
        creator_fee = (
            math.ceil(pay_for_tokens * (BUY_FEE_RATE + CREATOR_FEE_RATE) / BASIS_POINTS)
            - buy_fee
        )
        amount_in = pay_for_tokens + buy_fee + creator_fee

        quote1 = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in
        )
        expected_out1 = quote1["amount_received"]

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=self.token1_uid, amount=expected_out1)
        ctx1 = self.create_context(
            caller_id=buyer_address,
            actions=[deposit, withdrawal],
        )
        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx1, self.token1_uid
        )

        # Check that creator (user_address) received the creator fee in their HTR balance
        balance = self.runner.call_view_method(
            self.manager_id, "get_user_balance", self.user_address, 100, 0
        )

        # Parse the balance - should have HTR with creator fee
        htr_balance = None
        token_hex, amount = balance.split("_")
        if token_hex == HTR_UID.hex():
            htr_balance = int(amount)

        self.assertEqual(htr_balance, creator_fee)

        # Now user_address buys token2 with slippage - they should accumulate token slippage
        quote2 = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token2_uid, amount_in
        )
        expected_out2 = int(
            quote2["amount_received"] * 0.9
        )  # Request 90% to create slippage
        slippage2 = quote2["amount_received"] - expected_out2

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in)
        withdrawal = NCWithdrawalAction(token_uid=self.token2_uid, amount=expected_out2)
        ctx2 = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )
        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx2, self.token2_uid
        )

        # Get user balance - should have HTR (from creator fee) and token2 (from slippage)
        balance = self.runner.call_view_method(
            self.manager_id, "get_user_balance", self.user_address, 100, 0
        )

        # Parse the balance string
        balance_parts = balance.split()
        balance_dict = {}
        for part in balance_parts:
            token_hex, amount = part.split("_")
            balance_dict[token_hex] = int(amount)

        # Check HTR balance still has the creator fee
        self.assertIn(HTR_UID.hex(), balance_dict)
        self.assertEqual(balance_dict[HTR_UID.hex()], creator_fee)

        # Check token2 slippage is tracked
        self.assertIn(self.token2_uid.hex(), balance_dict)
        self.assertEqual(balance_dict[self.token2_uid.hex()], slippage2)

        # Another buyer purchases token1 again - creator should accumulate more fees
        pay_for_tokens_2 = 2000000
        buy_fee_2 = math.ceil(pay_for_tokens_2 * (BUY_FEE_RATE) / BASIS_POINTS)
        creator_fee_2 = (
            math.ceil(
                pay_for_tokens_2 * (BUY_FEE_RATE + CREATOR_FEE_RATE) / BASIS_POINTS
            )
            - buy_fee_2
        )
        amount_in_2 = pay_for_tokens_2 + buy_fee_2 + creator_fee_2

        quote3 = self.runner.call_view_method(
            self.manager_id, "quote_buy", self.token1_uid, amount_in_2
        )

        deposit = NCDepositAction(token_uid=HTR_UID, amount=amount_in_2)
        withdrawal = NCWithdrawalAction(
            token_uid=self.token1_uid, amount=quote3["amount_received"]
        )
        ctx3 = self.create_context(
            caller_id=buyer_address,
            actions=[deposit, withdrawal],
        )
        self.runner.call_public_method(
            self.manager_id, "buy_tokens", ctx3, self.token1_uid
        )

        # Calculate second creator fee
        total_expected_creator_fee = creator_fee + creator_fee_2

        # Check accumulated creator fees
        balance = self.runner.call_view_method(
            self.manager_id, "get_user_balance", self.user_address, 100, 0
        )

        balance_parts = balance.split()
        for part in balance_parts:
            token_hex, amount = part.split("_")
            if token_hex == HTR_UID.hex():
                self.assertEqual(int(amount), total_expected_creator_fee)
                break

        # Create HTR slippage by selling tokens
        sell_amount = expected_out2 // 2
        sell_quote = self.runner.call_view_method(
            self.manager_id, "quote_sell", self.token2_uid, sell_amount
        )
        reduced_htr_out = int(sell_quote["amount_received"] * 0.9)
        htr_slippage = sell_quote["amount_received"] - reduced_htr_out

        deposit = NCDepositAction(token_uid=self.token2_uid, amount=sell_amount)
        withdrawal = NCWithdrawalAction(token_uid=HTR_UID, amount=reduced_htr_out)
        ctx_sell = self.create_context(
            caller_id=self.user_address,
            actions=[deposit, withdrawal],
        )
        self.runner.call_public_method(
            self.manager_id, "sell_tokens", ctx_sell, self.token2_uid
        )

        # Get user balance - HTR should now have creator fees + sell slippage
        balance = self.runner.call_view_method(
            self.manager_id, "get_user_balance", self.user_address, 100, 0
        )

        balance_parts = balance.split()
        for part in balance_parts:
            token_hex, amount = part.split("_")
            if token_hex == HTR_UID.hex():
                self.assertEqual(int(amount), total_expected_creator_fee + htr_slippage)
                break

    def test_get_pool(self) -> None:
        """Test get_pool returns pool key for migrated tokens"""
        self._initialize_manager()
        self.token1_uid = self._register_token("token1", "TK1")

        # Before migration, get_pool should fail
        with self.assertNCFail("InvalidState"):
            self.runner.call_view_method(self.manager_id, "get_pool", self.token1_uid)

        # Migrate the token
        self._reach_migration_threshold(self.token1_uid)

        # Verify token is migrated
        token_info = self.runner.call_view_method(
            self.manager_id, "get_token_info", self.token1_uid
        )
        self.assertTrue(token_info.is_migrated)

        # Now get_pool should return the pool key
        pool_key = self.runner.call_view_method(
            self.manager_id, "get_pool", self.token1_uid
        )
        self.assertIsNotNone(pool_key)
        self.assertEqual(pool_key, token_info.pool_key)

        # Verify pool key exists in Dozer
        token_pools = self.runner.call_view_method(
            self.dozer_pool_manager_id, "get_pools_for_token", self.token1_uid
        )
        self.assertIn(pool_key, token_pools)

        # Test with non-existent token
        random_token_uid = self.gen_random_token_uid()
        with self.assertNCFail("TokenNotFound"):
            self.runner.call_view_method(self.manager_id, "get_pool", random_token_uid)
