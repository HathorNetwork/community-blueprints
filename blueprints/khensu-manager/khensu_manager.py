from typing import NamedTuple

from hathor import (
    Amount,
    Blueprint,
    BlueprintId,
    CallerId,
    Context,
    HATHOR_TOKEN_UID,
    NCAction,
    NCDepositAction,
    NCFail,
    NCFee,
    NCWithdrawalAction,
    Timestamp,
    TokenUid,
    ContractId,
    NCActionType,
    export,
    public,
    view,
)


# Custom exceptions
class InsufficientAmount(NCFail):
    pass


class Unauthorized(NCFail):
    pass


class InvalidState(NCFail):
    pass


class MigrationFailed(NCFail):
    pass


class TokenNotFound(NCFail):
    pass


class TokenExists(NCFail):
    pass


class InvalidParameters(NCFail):
    pass


class TransactionDenied(NCFail):
    pass


# Constants
BASIS_POINTS = 10000
FEE_TOKEN_VALUE = 1
MAX_FEE_RATE = 1000  # Maximum buy/sell/creator fee rate in basis points (10%)
MAX_POOL_FEE_RATE = 50
MAX_NAME_LENGTH = 30
MAX_SYMBOL_LENGTH = 5
MAX_DESCRIPTION_LENGTH = 500
NAME_ALLOWED_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
SYMBOL_ALLOWED_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class PlatformInfo(NamedTuple):
    """Consolidated platform data"""

    admin_address: str
    dozer_pool_manager_id: str
    buy_fee_rate: int
    sell_fee_rate: int
    creator_fee_rate: int
    default_pool_fee_rate: int
    default_target_market_cap: Amount
    default_graduation_fee: Amount
    default_token_total_supply: Amount
    collected_buy_fees: Amount
    collected_sell_fees: Amount
    collected_operation_fees: Amount
    lru_cache_capacity: int
    lru_cache_size: int


class TokenData(NamedTuple):
    """Consolidated token data stored in a single dict (used only within the contract)"""

    creator: CallerId
    token_name: str
    token_symbol: str
    image_link: str
    description: str
    twitter: str
    telegram: str
    website: str
    virtual_pool: Amount
    token_reserve: Amount
    target_market_cap: Amount
    graduation_fee: Amount
    total_supply: Amount
    total_volume: Amount
    transaction_count: int
    last_activity: Timestamp
    created_at: Timestamp
    is_migrated: bool
    pool_key: str
    constant_a: Amount
    constant_b: Amount
    constant_c: Amount


class TokenInfo(NamedTuple):
    """NamedTuple with data from a specific registered token for API responses (used outside the contract)"""

    creator: str
    token_name: str
    token_symbol: str
    image_link: str
    description: str
    twitter: str
    telegram: str
    website: str
    virtual_pool: Amount
    market_cap: Amount
    progress: int
    token_reserve: Amount
    target_market_cap: Amount
    graduation_fee: Amount
    total_supply: Amount
    total_volume: Amount
    transaction_count: int
    last_activity: Timestamp
    created_at: Timestamp
    is_migrated: bool
    pool_key: str


# Token data will be stored in separate dictionaries for each property
@export
class KhensuManager(Blueprint):
    """Singleton manager for Khensu token bonding curves."""

    # Version control
    contract_version: str

    # Administrative state
    admin_address: CallerId
    admin_set: set[CallerId]
    dozer_pool_manager_id: ContractId
    buy_fee_rate: int
    sell_fee_rate: int
    creator_fee_rate: int
    default_pool_fee_rate: int
    default_target_market_cap: Amount
    default_graduation_fee: Amount
    default_token_total_supply: Amount
    default_constant_a: Amount
    default_constant_b: Amount
    default_constant_c: Amount

    # Token registry
    all_tokens: list[TokenUid]
    symbol_dict: dict[str, list[TokenUid]]
    name_dict: dict[str, list[TokenUid]]
    user_creations: dict[CallerId, list[TokenUid]]  # Tokens created by a specific user
    graduated_tokens: list[TokenUid]

    # Consolidated token data
    tokens: dict[TokenUid, TokenData]

    # User balances from slippage and creator fees
    user_balance_tokens: dict[CallerId, list[TokenUid]]
    user_balances: dict[CallerId, dict[TokenUid, Amount]]

    # Platform statistics
    total_tokens_created: int
    total_tokens_migrated: int
    collected_buy_fees: Amount
    collected_sell_fees: Amount
    collected_operation_fees: Amount

    # LRU Cache for most recently accessed tokens
    lru_prev: dict[TokenUid, TokenUid]  # Previous pointer in doubly-linked list
    lru_next: dict[TokenUid, TokenUid]  # Next pointer in doubly-linked list
    lru_head: TokenUid  # Most recently used (head of list)
    lru_tail: TokenUid  # Least recently used (tail of list)
    lru_cache_capacity: int  # Maximum cache size
    lru_cache_size: int  # Current cache size
    lru_null_token: TokenUid  # Sentinel value to represent null

    @public
    def initialize(
        self,
        ctx: Context,
        dozer_pool_manager_id: ContractId,
        default_target_market_cap: Amount,
        default_graduation_fee: Amount,
        default_token_total_supply: Amount,
        buy_fee_rate: Amount,
        sell_fee_rate: Amount,
        creator_fee_rate: Amount,
        default_pool_fee_rate: int,
        lru_cache_capacity: int,
    ) -> None:
        """Initialize the KhensuManager contract."""
        caller_address = ctx.get_caller_address()
        assert caller_address is not None, "Caller address must be set"
        self.contract_version = "1.0.0"
        self.admin_address = caller_address
        self.admin_set = {caller_address}
        self.dozer_pool_manager_id = dozer_pool_manager_id

        # Validate fee rates and cache capacity
        if not 0 <= buy_fee_rate <= MAX_FEE_RATE:
            raise InvalidParameters("Invalid buy fee rate")
        if not 0 <= sell_fee_rate <= MAX_FEE_RATE:
            raise InvalidParameters("Invalid sell fee rate")
        if not 0 <= creator_fee_rate <= MAX_FEE_RATE:
            raise InvalidParameters("Invalid creator fee rate")
        if not 0 <= default_pool_fee_rate <= MAX_POOL_FEE_RATE:
            raise InvalidParameters("Invalid pool fee rate")
        if lru_cache_capacity <= 0:
            raise InvalidParameters("LRU cache capacity must be positive")

        # Default parameters for new tokens
        self.buy_fee_rate = buy_fee_rate
        self.sell_fee_rate = sell_fee_rate
        self.creator_fee_rate = creator_fee_rate
        self.default_pool_fee_rate = default_pool_fee_rate
        self.default_target_market_cap = default_target_market_cap
        self.default_graduation_fee = default_graduation_fee
        self.default_token_total_supply = default_token_total_supply

        # Validate curve parameters and compute constants
        constant_a, constant_b, constant_c = self._compute_curve_constants(
            default_target_market_cap,
            default_token_total_supply,
            default_graduation_fee,
        )
        self.default_constant_a = constant_a
        self.default_constant_b = constant_b
        self.default_constant_c = constant_c

        # Platform statistics
        self.total_tokens_created = 0
        self.total_tokens_migrated = 0
        self.collected_buy_fees = Amount(0)
        self.collected_sell_fees = Amount(0)
        self.collected_operation_fees = Amount(0)

        # LRU Cache initialization
        self.lru_null_token = HATHOR_TOKEN_UID  # type: ignore
        self.lru_head = self.lru_null_token
        self.lru_tail = self.lru_null_token
        self.lru_cache_capacity = lru_cache_capacity
        self.lru_cache_size = 0
        self.lru_prev = {}
        self.lru_next = {}

        # Initialize empty values
        self.all_tokens = []
        self.symbol_dict = {}
        self.name_dict = {}
        self.user_creations = {}
        self.graduated_tokens = []
        self.tokens = {}
        self.user_balance_tokens = {}
        self.user_balances = {}

    def _compute_curve_constants(
        self,
        target_market_cap: Amount,
        total_supply: Amount,
        graduation_fee: Amount,
    ) -> tuple[Amount, Amount, Amount]:
        """Validate bonding-curve parameters and compute constants a, b, c.

        Raises InvalidParameters if the parameters would produce a degenerate
        curve.
        """
        if target_market_cap <= 0:
            raise InvalidParameters("Invalid target market cap")
        if total_supply <= 0:
            raise InvalidParameters("Invalid token amount")
        if graduation_fee < FEE_TOKEN_VALUE:
            raise InvalidParameters("Invalid graduation fee")

        constant_c = 5 * (3 * target_market_cap - 5 * graduation_fee)
        if constant_c <= 0:
            raise InvalidParameters(
                "Invalid relation between market cap and graduation fee"
            )

        constant_a = 16 * total_supply * target_market_cap
        constant_b = (target_market_cap + 5 * graduation_fee) * (
            target_market_cap + 5 * graduation_fee
        )
        return Amount(constant_a), Amount(constant_b), Amount(constant_c)

    def _get_token_data(self, token_uid: TokenUid) -> TokenData:
        """Get the token data, raising error if not found."""
        if token_uid not in self.tokens:
            raise TokenNotFound(f"Token does not exist: {token_uid.hex()}")
        return self.tokens[token_uid]

    def _update_token_data(self, token_uid: TokenUid, **updates) -> None:
        """Update specific fields of token data."""
        token_data = self._get_token_data(token_uid)
        self.tokens[token_uid] = token_data._replace(**updates)

    def _get_token(self, token_uid: TokenUid) -> TokenInfo:
        """Get the token data formatted for API responses."""
        token_data = self._get_token_data(token_uid)
        market_cap = self._calculate_market_cap(token_uid)
        progress = self._calculate_curve_progress(token_uid)

        return TokenInfo(
            token_data.creator.hex(),
            token_data.token_name,
            token_data.token_symbol,
            token_data.image_link,
            token_data.description,
            token_data.twitter,
            token_data.telegram,
            token_data.website,
            token_data.virtual_pool,
            market_cap,
            progress,
            token_data.token_reserve,
            token_data.target_market_cap,
            token_data.graduation_fee,
            token_data.total_supply,
            token_data.total_volume,
            token_data.transaction_count,
            token_data.last_activity,
            token_data.created_at,
            token_data.is_migrated,
            token_data.pool_key,
        )

    def _validate_token_exists(self, token_uid: TokenUid) -> None:
        """Check if a token exists, raising error if not."""
        if token_uid not in self.tokens:
            raise TokenNotFound(f"Token does not exist: {token_uid.hex()}")

    def _only_admin(self, ctx: Context) -> None:
        """Validate that the caller is the platform admin."""
        if ctx.get_caller_address() not in self.admin_set:
            raise Unauthorized("Only admin can call this method")

    def _only_creator(self, ctx: Context) -> None:
        """Validate that the caller is the original contract creator.

        More restrictive than `_only_admin`: reserved for the highest-risk
        action (blueprint upgrade), which no delegated admin may perform.
        """
        if ctx.get_caller_address() != self.admin_address:
            raise Unauthorized("Only the contract creator can call this method")

    def _validate_not_migrated(self, token_uid: TokenUid) -> None:
        """Validate that a token has not been migrated."""
        token_data = self._get_token_data(token_uid)
        if token_data.is_migrated:
            raise InvalidState("Token has already migrated")

    def _calculate_fee(self, amount: Amount, fee_rate: int) -> Amount:
        """Calculate fee using ceiling division."""
        return Amount((amount * fee_rate + BASIS_POINTS - 1) // BASIS_POINTS)

    def _extract_fee(self, amount: Amount, fee_rate: int) -> Amount:
        """Extract fee from amount."""
        return Amount(
            (amount * fee_rate + fee_rate + BASIS_POINTS - 1)
            // (fee_rate + BASIS_POINTS)
        )

    def _validate_actions_in_out(
        self, ctx: Context, expected_in: TokenUid, expected_out: TokenUid
    ) -> tuple[NCDepositAction, NCWithdrawalAction]:
        """Get and validate deposit/withdrawal pair with expected token types."""
        action_in, action_out = self._get_actions_in_out(ctx)

        if action_in.token_uid != expected_in:
            raise InvalidState(f"Input token must be {expected_in.hex()}")
        if action_out.token_uid != expected_out:
            raise InvalidState(f"Output token must be {expected_out.hex()}")

        assert isinstance(action_in, NCDepositAction), "Invalid action type"
        assert isinstance(action_out, NCWithdrawalAction), "Invalid action type"

        return action_in, action_out

    def _calculate_market_cap(self, token_uid: TokenUid) -> Amount:
        """Calculate current market cap of a token.

        For non-migrated tokens: Uses bonding curve formula.
        For migrated tokens: Queries Dozer for token price and multiplies by 1 billion.
        """
        token_data = self._get_token_data(token_uid)

        # For migrated tokens, query Dozer for token price
        if token_data.is_migrated:
            dozer = self.syscall.get_contract(
                self.dozer_pool_manager_id, blueprint_id=None
            )
            token_price_in_htr = dozer.view().get_token_price_in_htr(token_uid)

            if token_price_in_htr > 0:
                # Market cap = token_price_in_htr * total_supply
                # token_price_in_htr has 8 decimals, total_supply has 2 decimals
                # We need result in HTR cents (2 decimals)
                # market_cap_htr_cents = (price_8dec * supply_2dec) / 10^8
                return Amount(
                    (token_price_in_htr * token_data.total_supply) // 100_000_000
                )
            else:
                # Fallback to target market cap if price not available
                return token_data.target_market_cap

        # For non-migrated tokens, use bonding curve formula
        # Market Cap = a * b * S / (a - c * Ts)^2
        # where S = total supply, Ts = tokens sold
        a = token_data.constant_a
        b = token_data.constant_b
        c = token_data.constant_c
        numerator = a * b * token_data.total_supply
        denominator = a - c * (token_data.total_supply - token_data.token_reserve)
        denominator = denominator * denominator
        return Amount(numerator // denominator)

    def _calculate_curve_progress(self, token_uid: TokenUid) -> int:
        """Calculate the progress of the bonding curve in basis points."""
        token_data = self._get_token_data(token_uid)
        if token_data.is_migrated:
            return 1 * BASIS_POINTS
        tokens_sold = token_data.total_supply - token_data.token_reserve
        numerator = 5 * token_data.constant_b * tokens_sold * BASIS_POINTS
        denominator = (token_data.target_market_cap + 5 * token_data.graduation_fee) * (
            token_data.constant_a - token_data.constant_c * tokens_sold
        )
        return min(max(numerator // denominator, 0), BASIS_POINTS)

    def _calculate_tokens_out(self, token_uid: TokenUid, htr_amount: Amount) -> Amount:
        """Calculate tokens to return for a given HTR input using bonding curve."""
        # Using bonding curve formula: T = H * (a - c*Ts)^2 / (a*b + c*H*(a - c*Ts))
        # where T = tokens out, H = HTR in, Ts = tokens sold
        token_data = self._get_token_data(token_uid)
        tokens_sold = token_data.total_supply - token_data.token_reserve
        aux = token_data.constant_a - token_data.constant_c * tokens_sold
        numerator = aux * aux * htr_amount
        denominator = (
            token_data.constant_a * token_data.constant_b
            + htr_amount * token_data.constant_c * aux
        )
        if denominator == 0:
            return Amount(0)
        return Amount(numerator // denominator)

    def _calculate_htr_needed(
        self, token_uid: TokenUid, token_amount: Amount
    ) -> Amount:
        """Calculate HTR needed for buying a given token input using bonding curve."""
        # Using inverse bonding curve: H = a*b*T / ((a - c*Ts) * (a - c*Ts - c*T))
        # where T = tokens in, Ts = tokens sold
        token_data = self._get_token_data(token_uid)
        tokens_sold = token_data.total_supply - token_data.token_reserve

        numerator = token_amount * token_data.constant_a * token_data.constant_b
        denominator = (token_data.constant_a - token_data.constant_c * tokens_sold) * (
            token_data.constant_a - token_data.constant_c * (tokens_sold + token_amount)
        )
        if denominator == 0:
            return Amount(0)
        # Ceiling division
        return Amount((numerator + denominator - 1) // denominator)

    def _calculate_htr_out(self, token_uid: TokenUid, token_amount: Amount) -> Amount:
        """Calculate HTR to return for a given token input using bonding curve."""
        # Using inverse bonding curve: H = a*b*T / ((a - c*Ts) * (a - c*Ts + c*T))
        # where T = tokens in, Ts = tokens sold
        token_data = self._get_token_data(token_uid)
        tokens_sold = token_data.total_supply - token_data.token_reserve

        numerator = token_amount * token_data.constant_a * token_data.constant_b
        denominator = (token_data.constant_a - token_data.constant_c * tokens_sold) * (
            token_data.constant_a - token_data.constant_c * (tokens_sold - token_amount)
        )
        if denominator == 0:
            return Amount(0)
        return Amount(numerator // denominator)

    def _calculate_tokens_needed(
        self, token_uid: TokenUid, htr_amount: Amount
    ) -> Amount:
        """Calculate tokens needed for a given HTR input using bonding curve."""
        # Using bonding curve formula: T = H * (a - c*Ts)^2 / (a*b - c*H*(a - c*Ts))
        # where T = tokens out, H = HTR in, Ts = tokens sold
        token_data = self._get_token_data(token_uid)
        tokens_sold = token_data.total_supply - token_data.token_reserve
        aux = token_data.constant_a - token_data.constant_c * tokens_sold
        numerator = aux * aux * htr_amount
        denominator = (
            token_data.constant_a * token_data.constant_b
            - htr_amount * token_data.constant_c * aux
        )
        if denominator == 0:
            return Amount(0)
        # Ceiling division
        return Amount((numerator + denominator - 1) // denominator)

    def _correct_curve_deviation(self, token_uid: TokenUid) -> None:
        """Removes residual HTR in the curve of a token after aproximations of buy and sell"""
        token_data = self._get_token_data(token_uid)
        tokens_sold = token_data.total_supply - token_data.token_reserve

        # Using inverse bonding curve: H = b*Ts / (a - c*Ts)
        # where Ts = Tokens sold, H = Maximum HTR expected in the pool
        numerator = tokens_sold * token_data.constant_b
        denominator = token_data.constant_a - token_data.constant_c * tokens_sold
        # Ceiling division
        max_possible_virtual_pool = Amount((numerator + denominator - 1) // denominator)

        if token_data.virtual_pool > max_possible_virtual_pool:
            self.collected_operation_fees = Amount(
                self.collected_operation_fees
                + token_data.virtual_pool
                - max_possible_virtual_pool
            )
            self._update_token_data(
                token_uid,
                virtual_pool=Amount(max_possible_virtual_pool),
            )

    def _get_action(self, ctx: Context, action_type: NCActionType) -> NCAction:
        """Get and validate single action"""
        if len(ctx.actions) != 1:
            raise NCFail("Expected single action")
        action_tuple = list(ctx.actions.values())[0]
        total_amount = Amount(0)
        for action in action_tuple:
            assert isinstance(action, NCDepositAction) or isinstance(
                action, NCWithdrawalAction
            ), "Invalid action type"
            total_amount += action.amount
            if action.type != action_type:
                raise NCFail(f"Expected {action_type} action")
        if action_type == NCActionType.DEPOSIT:
            return NCDepositAction(
                token_uid=action_tuple[0].token_uid, amount=total_amount
            )
        elif action_type == NCActionType.WITHDRAWAL:
            return NCWithdrawalAction(
                token_uid=action_tuple[0].token_uid, amount=total_amount
            )
        else:
            raise NCFail(f"Invalid action type: {action_type}")

    def _get_actions_in_in(self, ctx: Context) -> tuple[NCAction, NCAction]:
        """Return token_a and token_b actions. It also validates that both are deposits."""
        if len(ctx.actions) != 2:
            raise InvalidState("Expected exactly two tokens")

        action_htr = None
        action_token = None

        for action_tuple in ctx.actions.values():
            if len(action_tuple) != 1:
                raise InvalidParameters("Can only execute one action per token")
            if (
                action_tuple[0].type == NCActionType.DEPOSIT
                and action_tuple[0].token_uid == HATHOR_TOKEN_UID
            ):
                total_deposit_htr = Amount(0)
                for deposit in action_tuple:
                    assert isinstance(deposit, NCDepositAction), "Invalid action type"
                    total_deposit_htr += deposit.amount
                action_htr = NCDepositAction(
                    token_uid=action_tuple[0].token_uid, amount=total_deposit_htr
                )
            elif (
                action_tuple[0].type == NCActionType.DEPOSIT
                and action_tuple[0].token_uid != HATHOR_TOKEN_UID
            ):
                total_deposit_token = Amount(0)
                for deposit in action_tuple:
                    assert isinstance(deposit, NCDepositAction), "Invalid action type"
                    total_deposit_token += deposit.amount
                action_token = NCDepositAction(
                    token_uid=action_tuple[0].token_uid, amount=total_deposit_token
                )

        if not action_htr or not action_token:
            raise InvalidState("Expected HTR and token deposits")

        return action_htr, action_token

    def _get_actions_in_out(self, ctx: Context) -> tuple[NCAction, NCAction]:
        """Get and validate deposit/withdrawal pair."""
        if len(ctx.actions) != 2:
            raise InvalidState("Expected deposit and withdrawal of 2 different tokens")

        action_in = None
        action_out = None

        for action_tuple in ctx.actions.values():
            if len(action_tuple) != 1:
                raise InvalidParameters("Can only execute one action per token")
            if action_tuple[0].type == NCActionType.DEPOSIT:
                total_deposit = Amount(0)
                for deposit in action_tuple:
                    assert isinstance(deposit, NCDepositAction), "Invalid action type"
                    total_deposit += deposit.amount
                action_in = NCDepositAction(
                    token_uid=action_tuple[0].token_uid, amount=total_deposit
                )
            elif action_tuple[0].type == NCActionType.WITHDRAWAL:
                total_withdrawal = Amount(0)
                for withdrawal in action_tuple:
                    assert isinstance(
                        withdrawal, NCWithdrawalAction
                    ), "Invalid action type"
                    total_withdrawal += withdrawal.amount
                action_out = NCWithdrawalAction(
                    token_uid=action_tuple[0].token_uid, amount=total_withdrawal
                )

        if not action_in or not action_out:
            raise InvalidState("Must have one deposit and one withdrawal")

        return action_in, action_out

    def _calculate_price_impact(
        self, token_uid: TokenUid, final_reserve: Amount
    ) -> int:
        """Calculate price impact percentage for a transaction.

        Args:
            token_uid: The token identifier
            final_reserve: Token reserve after transaction

        Returns:
            Price impact as basis points (e.g., 250 = 2.5%)
        """
        self._validate_token_exists(token_uid)

        token_data = self._get_token_data(token_uid)

        numerator = (
            token_data.constant_c
            * (final_reserve - token_data.token_reserve)
            * (
                2 * token_data.constant_a
                - 2 * token_data.constant_c * token_data.total_supply
                + token_data.constant_c * (final_reserve + token_data.token_reserve)
            )
            * BASIS_POINTS
        )
        denominator = (
            token_data.constant_a
            - token_data.constant_c * token_data.total_supply
            + token_data.constant_c * final_reserve
        )
        denominator = denominator * denominator

        return abs(numerator // denominator)

    def _increase_user_balance(
        self, token_uid: TokenUid, address: CallerId, amount: Amount
    ) -> None:
        """Increase user balance for a token."""
        if amount < 0:
            raise InvalidParameters("Transaction cannot decrease balance")
        if address not in self.user_balances:
            self.user_balance_tokens[address] = []
            self.user_balances[address] = {}

        user_balance = self.user_balances[address]
        if token_uid not in user_balance:
            self.user_balance_tokens[address].append(token_uid)
        user_balance[token_uid] = Amount(
            user_balance.get(token_uid, Amount(0)) + amount
        )
        self.user_balances[address] = user_balance

    def _evict_lru_tail(self) -> None:
        """Evict the least recently used token from cache (O(1) operation)."""
        if self.lru_cache_size == 0:
            return

        tail_uid = self.lru_tail
        new_tail = self.lru_prev.get(tail_uid, self.lru_null_token)

        # Remove tail from dictionaries
        if tail_uid in self.lru_prev:
            del self.lru_prev[tail_uid]
        if tail_uid in self.lru_next:
            del self.lru_next[tail_uid]

        # Update new tail's next pointer
        if new_tail != self.lru_null_token:
            self.lru_next[new_tail] = self.lru_null_token

        # Update tail pointer
        self.lru_tail = new_tail

        # If we evicted the only element, update head too
        if tail_uid == self.lru_head:
            self.lru_head = self.lru_null_token

        # Decrement size
        self.lru_cache_size -= 1

    def _remove_from_lru_list(self, token_uid: TokenUid) -> None:
        """Remove token from its current position in LRU list (O(1) operation)."""
        prev_node = self.lru_prev.get(token_uid, self.lru_null_token)
        next_node = self.lru_next.get(token_uid, self.lru_null_token)

        # Update previous node's next pointer
        if prev_node != self.lru_null_token:
            self.lru_next[prev_node] = next_node
        else:
            # This was the head
            self.lru_head = next_node

        # Update next node's prev pointer
        if next_node != self.lru_null_token:
            self.lru_prev[next_node] = prev_node
        else:
            # This was the tail
            self.lru_tail = prev_node

    def _add_to_lru_head(self, token_uid: TokenUid) -> None:
        """Add token to the head of LRU list (most recent position, O(1) operation)."""
        # Set token's pointers
        self.lru_prev[token_uid] = self.lru_null_token
        self.lru_next[token_uid] = self.lru_head

        # Update old head's prev pointer
        if self.lru_head != self.lru_null_token:
            self.lru_prev[self.lru_head] = token_uid

        # Update head pointer
        self.lru_head = token_uid

        # If this is the first element, update tail too
        if self.lru_tail == self.lru_null_token:
            self.lru_tail = token_uid

    def update_lru(self, token_uid: TokenUid) -> None:
        """Update LRU cache by moving token to head (most recent). O(1) operation with no loops."""
        # Check if token already in cache
        token_in_cache = token_uid in self.lru_prev

        if token_in_cache:
            # Remove from current position
            self._remove_from_lru_list(token_uid)
            # Move to head (will be added below)
        else:
            # New token - check capacity
            if self.lru_cache_size >= self.lru_cache_capacity:
                # Evict least recently used (tail)
                self._evict_lru_tail()

            # Increment size for new token
            self.lru_cache_size += 1

        # Add/move token to head (most recent)
        self._add_to_lru_head(token_uid)

    def migrate_liquidity(self, token_uid: TokenUid) -> None:
        """Migrate a token's liquidity to a DEX when threshold is reached."""
        token_data = self._get_token_data(token_uid)

        if token_data.is_migrated:
            raise InvalidState("Token has already migrated")

        # Get relevant token data
        market_cap = self._calculate_market_cap(token_uid)

        # Check if market cap threshold is reached
        if market_cap < token_data.target_market_cap:
            raise InvalidState("Market cap threshold not reached")

        # Validate balances
        if token_data.token_reserve != token_data.total_supply // 5:
            raise NCFail("Invalid token reserve")

        liquidity_amount = token_data.target_market_cap // 5

        if token_data.virtual_pool - token_data.graduation_fee < liquidity_amount:
            raise NCFail("Insufficient HTR for migration")

        # Add liquidity to Dozer pool
        actions = [
            NCDepositAction(token_uid=HATHOR_TOKEN_UID, amount=liquidity_amount),
            NCDepositAction(token_uid=token_uid, amount=token_data.token_reserve),
        ]
        fees = [NCFee(token_uid=HATHOR_TOKEN_UID, amount=FEE_TOKEN_VALUE)]

        # Call Dozer Pool Manager to create pool
        dozer = self.syscall.get_contract(self.dozer_pool_manager_id, blueprint_id=None)
        pool_key = dozer.public(*actions, fees=fees).create_pool(
            self.default_pool_fee_rate
        )

        # Sign the pool to enable price calculations (KhensuManager must be authorized signer)
        dozer.public().sign_pool(
            HATHOR_TOKEN_UID, token_uid, self.default_pool_fee_rate
        )

        # Release the reservation now that the canonical pool exists, so other
        # fee-tier pools for this token can be created permissionlessly.
        dozer.public().release_pool_reservation(token_uid)

        # Store the pool key
        self._update_token_data(token_uid, is_migrated=True, pool_key=pool_key)

        self.graduated_tokens.append(token_uid)

        # Update collected graduation fees
        # (Prevents trapping residual money due to rounding on transactions)
        self.collected_operation_fees = Amount(
            self.collected_operation_fees
            + token_data.virtual_pool
            - liquidity_amount
            - FEE_TOKEN_VALUE
        )

        # Update platform statistics
        self.total_tokens_migrated += 1

    @public(allow_deposit=True)
    def register_token(
        self,
        ctx: Context,
        token_name: str,
        token_symbol: str,
        description: str,
        twitter: str,
        telegram: str,
        website: str,
        image_link: str,
    ) -> TokenUid:
        """Create a new token with the manager."""
        # Validate token metadata
        if not (1 <= len(token_name) <= MAX_NAME_LENGTH):
            raise InvalidParameters("Token name must be 1-30 characters")
        if not all(c in NAME_ALLOWED_CHARS for c in token_name):
            raise InvalidParameters(
                "Token name may only contain letters, numbers, and spaces"
            )
        if not (1 <= len(token_symbol) <= MAX_SYMBOL_LENGTH):
            raise InvalidParameters("Token symbol must be 1-5 characters")
        if not all(c in SYMBOL_ALLOWED_CHARS for c in token_symbol):
            raise InvalidParameters(
                "Token symbol may only contain uppercase letters and numbers"
            )
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise InvalidParameters("Description must be at most 500 characters")

        initial_token_reserve = self.default_token_total_supply

        token_uid = self.syscall.create_fee_token(
            token_name=token_name,
            token_symbol=token_symbol,
            amount=initial_token_reserve,
            mint_authority=False,
            melt_authority=False,
        )

        # Reserve the token's Dozer pool so nobody can front-run graduation by
        # pre-creating the pool (which would make migrate_liquidity revert).
        dozer = self.syscall.get_contract(self.dozer_pool_manager_id, blueprint_id=None)
        dozer.public().reserve_pool_creation(token_uid)

        # Validate the deposit needed to create a fee-based token
        action = self._get_action(ctx, NCActionType.DEPOSIT)
        assert isinstance(action, NCDepositAction), "Invalid action type"

        if action.token_uid != HATHOR_TOKEN_UID:
            raise NCFail("Can only deposit HTR")
        if action.amount != FEE_TOKEN_VALUE:
            raise NCFail("Invalid deposit amount")

        caller_address = ctx.get_caller_address()
        assert caller_address is not None, "Caller address must be set"

        if twitter and not twitter.startswith("https://"):
            twitter = ""
        if telegram and not telegram.startswith("https://"):
            telegram = ""
        if website and not website.startswith("https://"):
            website = ""

        # Store image hash if provided
        if not image_link or len(image_link) < 32:
            image_link = ""

        self.tokens[token_uid] = TokenData(
            creator=caller_address,
            token_name=token_name,
            token_symbol=token_symbol,
            image_link=image_link,
            description=description,
            twitter=twitter,
            telegram=telegram,
            website=website,
            virtual_pool=Amount(0),
            token_reserve=Amount(initial_token_reserve),
            target_market_cap=self.default_target_market_cap,
            graduation_fee=self.default_graduation_fee,
            total_supply=Amount(initial_token_reserve),
            total_volume=Amount(0),
            transaction_count=0,
            last_activity=Timestamp(ctx.block.timestamp),
            created_at=Timestamp(ctx.block.timestamp),
            is_migrated=False,
            pool_key="",
            constant_a=self.default_constant_a,
            constant_b=self.default_constant_b,
            constant_c=self.default_constant_c,
        )

        self.symbol_dict.get(token_symbol, []).append(token_uid)
        self.name_dict.get(token_name.upper(), []).append(token_uid)
        if caller_address not in self.user_creations:
            self.user_creations[caller_address] = []
        self.user_creations[caller_address].append(token_uid)
        self.all_tokens.append(token_uid)
        self.total_tokens_created += 1
        self.update_lru(token_uid)

        return token_uid

    @public(allow_deposit=True, allow_withdrawal=True)
    def buy_tokens(self, ctx: Context, token_uid: TokenUid) -> None:
        """Buy tokens using HTR."""
        self._validate_not_migrated(token_uid)

        action_in, action_out = self._validate_actions_in_out(
            ctx, HATHOR_TOKEN_UID, token_uid
        )

        # Calculate and apply buy fee (operates with ceiling division)
        fee_amount = self._extract_fee(
            Amount(action_in.amount), self.buy_fee_rate + self.creator_fee_rate
        )
        net_amount = Amount(action_in.amount - fee_amount)
        buy_fee_amount = self._calculate_fee(net_amount, self.buy_fee_rate)
        creator_fee_amount = fee_amount - buy_fee_amount

        # Verify if the payment is too low, making the fee equal to net_amount because of ceiling division
        if net_amount <= 0:
            raise TransactionDenied("Fee was not matched")

        token_data = self._get_token_data(token_uid)

        # Check if transaction will leave the curve with less than 20% of the total supply
        if token_data.token_reserve - action_out.amount < token_data.total_supply // 5:
            raise InsufficientAmount("Transaction beyond market cap")

        tokens_out = self._calculate_tokens_out(token_uid, net_amount)
        # Make sure the last purchase before graduation does not exceed the token reserve
        htr_needed = action_in.amount
        if tokens_out > token_data.token_reserve - token_data.total_supply // 5:
            tokens_out = Amount(token_data.token_reserve - token_data.total_supply // 5)
            net_amount = self._calculate_htr_needed(token_uid, tokens_out)
            buy_fee_amount = self._calculate_fee(Amount(net_amount), self.buy_fee_rate)
            creator_fee_amount = (
                self._calculate_fee(
                    Amount(net_amount), self.buy_fee_rate + self.creator_fee_rate
                )
                - buy_fee_amount
            )
            htr_needed = Amount(net_amount + buy_fee_amount + creator_fee_amount)

        # Calculate tokens to return
        if tokens_out == 0:
            raise TransactionDenied("Below minimum purchase")

        if action_out.amount > tokens_out:
            raise TransactionDenied("Payment does not match cost")

        # Handle slippage return if user requested less than available
        slippage = Amount(tokens_out - action_out.amount)
        caller_address = ctx.get_caller_address()
        assert caller_address is not None, "Caller address must be set"

        if slippage > 0:
            self._increase_user_balance(token_uid, caller_address, slippage)
        if htr_needed < action_in.amount:
            self._increase_user_balance(
                HATHOR_TOKEN_UID, caller_address, Amount(action_in.amount - htr_needed)
            )

        # Update collected fees
        self.collected_buy_fees = Amount(self.collected_buy_fees + buy_fee_amount)
        self._increase_user_balance(
            HATHOR_TOKEN_UID, token_data.creator, Amount(creator_fee_amount)
        )

        # Update token state

        self._update_token_data(
            token_uid,
            virtual_pool=Amount(token_data.virtual_pool + net_amount),
            token_reserve=Amount(token_data.token_reserve - tokens_out),
            total_volume=Amount(token_data.total_volume + htr_needed),
            transaction_count=token_data.transaction_count + 1,
            last_activity=Timestamp(ctx.block.timestamp),
        )

        # Update LRU cache
        self.update_lru(token_uid)

        # Remove possible residual HTR in the curve
        self._correct_curve_deviation(token_uid)

        # Check migration threshold
        # Only attempt migration if we've reached the target market cap
        token_data = self._get_token_data(token_uid)
        if (
            token_data.token_reserve == token_data.total_supply // 5
            and self._calculate_market_cap(token_uid) >= token_data.target_market_cap
            and not token_data.is_migrated
        ):
            self.migrate_liquidity(token_uid)

    @public(allow_deposit=True, allow_withdrawal=True)
    def sell_tokens(self, ctx: Context, token_uid: TokenUid) -> None:
        """Sell tokens for HTR."""
        self._validate_not_migrated(token_uid)

        action_in, action_out = self._validate_actions_in_out(
            ctx, token_uid, HATHOR_TOKEN_UID
        )

        if action_in.amount < 1:
            raise TransactionDenied("Below minimum sale")

        # Calculate HTR return
        htr_out = self._calculate_htr_out(token_uid, Amount(action_in.amount))

        # Defensive solvency guard: a token can never pay out more HTR than its own virtual pool holds.
        if htr_out > self._get_token_data(token_uid).virtual_pool:
            raise InsufficientAmount("Insufficient pool liquidity")

        # Apply sell fee
        fee_amount = self._calculate_fee(htr_out, self.sell_fee_rate)
        net_amount = htr_out - fee_amount

        # Verify if the amount sold is not too low, making the fee equal to net_amount because of ceiling division
        if net_amount < 0:
            raise TransactionDenied("Fee was not matched")

        if net_amount < action_out.amount:
            raise TransactionDenied("Selling price was not matched")

        # Update collected fees
        self.collected_sell_fees = Amount(self.collected_sell_fees + fee_amount)

        # Handle slippage return if user requested less than available
        slippage = Amount(net_amount - action_out.amount)
        caller_address = ctx.get_caller_address()
        assert caller_address is not None, "Caller address must be set"
        if slippage > 0:
            self._increase_user_balance(HATHOR_TOKEN_UID, caller_address, slippage)

        # Update token state
        token_data = self._get_token_data(token_uid)
        self._update_token_data(
            token_uid,
            virtual_pool=Amount(token_data.virtual_pool - htr_out),
            token_reserve=Amount(token_data.token_reserve + action_in.amount),
            total_volume=Amount(token_data.total_volume + net_amount),
            transaction_count=token_data.transaction_count + 1,
            last_activity=Timestamp(ctx.block.timestamp),
        )

        # Update LRU cache
        self.update_lru(token_uid)

        # Remove possible residual HTR in the curve
        self._correct_curve_deviation(token_uid)

    @public(allow_withdrawal=True)
    def withdraw_fees(self, ctx: Context) -> None:
        """Withdraw collected fees for a token."""
        self._only_admin(ctx)

        total_fees = (
            self.collected_buy_fees
            + self.collected_sell_fees
            + self.collected_operation_fees
        )
        if total_fees <= 0:
            raise InvalidState("No fees to withdraw")

        action = self._get_action(ctx, NCActionType.WITHDRAWAL)
        assert isinstance(action, NCWithdrawalAction), "Invalid action type"

        if action.token_uid != HATHOR_TOKEN_UID:
            raise NCFail("Can only withdraw HTR")
        withdraw_amount = action.amount
        if withdraw_amount > total_fees:
            raise NCFail("Invalid withdrawal amount")

        # Subtract fee counters
        remaining = withdraw_amount
        # Subtract from buy fees first
        deduct = min(remaining, self.collected_buy_fees)
        self.collected_buy_fees = Amount(self.collected_buy_fees - deduct)
        remaining -= deduct

        if remaining <= 0:
            return

        # Then subtract from sell fees
        deduct = min(remaining, self.collected_sell_fees)
        self.collected_sell_fees = Amount(self.collected_sell_fees - deduct)
        remaining -= deduct

        if remaining <= 0:
            return

        # Finally subtract from graduation fees
        deduct = min(remaining, self.collected_operation_fees)
        self.collected_operation_fees = Amount(self.collected_operation_fees - deduct)
        remaining -= deduct

    @public(allow_withdrawal=True)
    def withdraw_from_balance(self, ctx: Context) -> None:
        """Withdraw tokens from the balance of a specific user."""

        action = self._get_action(ctx, NCActionType.WITHDRAWAL)
        assert isinstance(action, NCWithdrawalAction), "Invalid action type"
        withdraw_amount = Amount(action.amount)

        user_address = ctx.get_caller_address()
        assert user_address is not None, "Caller address must be set"

        available_amount = Amount(
            self.get_user_token_balance(user_address, action.token_uid)
        )
        if withdraw_amount <= 0:
            raise InvalidParameters("Invalid withdrawal amount")
        if available_amount < withdraw_amount:
            raise InsufficientAmount("Insufficient token balance")

        remaining = Amount(available_amount - withdraw_amount)

        self.user_balances[user_address][action.token_uid] = remaining

    @public
    def change_buy_fee_rate(self, ctx: Context, buy_fee_rate: int) -> None:
        """Change the buy fee rate for all tokens."""
        self._only_admin(ctx)
        if buy_fee_rate > MAX_FEE_RATE or buy_fee_rate < 0:
            raise InvalidParameters("Invalid buy fee rate")
        self.buy_fee_rate = buy_fee_rate

    @public
    def change_sell_fee_rate(self, ctx: Context, sell_fee_rate: int) -> None:
        """Change the sell fee rate for all tokens."""
        self._only_admin(ctx)
        if sell_fee_rate > MAX_FEE_RATE or sell_fee_rate < 0:
            raise InvalidParameters("Invalid sell fee rate")
        self.sell_fee_rate = sell_fee_rate

    @public
    def change_creator_fee_rate(self, ctx: Context, creator_fee_rate: int) -> None:
        """Change the creator fee rate for all tokens."""
        self._only_admin(ctx)
        if creator_fee_rate > MAX_FEE_RATE or creator_fee_rate < 0:
            raise InvalidParameters("Invalid creator fee rate")
        self.creator_fee_rate = creator_fee_rate

    @public
    def change_pool_fee_rate(self, ctx: Context, default_pool_fee_rate: int) -> None:
        """Change the pool fee rate for all tokens."""
        self._only_admin(ctx)
        if default_pool_fee_rate > MAX_POOL_FEE_RATE or default_pool_fee_rate < 0:
            raise InvalidParameters("Invalid pool fee rate")
        self.default_pool_fee_rate = default_pool_fee_rate

    @public
    def change_bonding_curve(
        self,
        ctx: Context,
        target_market_cap: Amount,
        default_token_total_supply: Amount,
        default_graduation_fee: Amount,
    ) -> None:
        """Change the bonding curve parameter for new tokens."""
        self._only_admin(ctx)
        constant_a, constant_b, constant_c = self._compute_curve_constants(
            target_market_cap,
            default_token_total_supply,
            default_graduation_fee,
        )
        self.default_constant_a = constant_a
        self.default_constant_b = constant_b
        self.default_constant_c = constant_c
        self.default_target_market_cap = target_market_cap
        self.default_token_total_supply = default_token_total_supply
        self.default_graduation_fee = default_graduation_fee

    @public
    def add_admin(self, ctx: Context, new_admin: CallerId) -> None:
        """Gives admin rights to a new address."""
        self._only_admin(ctx)
        self.admin_set.add(new_admin)

    @public
    def remove_admin(self, ctx: Context, remove_admin: CallerId) -> None:
        """Removes admin rights from an address."""
        self._only_admin(ctx)
        if len(self.admin_set) == 1:
            raise InvalidState("Cannot remove only admin")
        if remove_admin == self.admin_address:
            raise InvalidParameters("Cannot remove contract creator")
        self.admin_set.remove(remove_admin)

    @public
    def change_lru_capacity(self, ctx: Context, new_capacity: int) -> None:
        """Change the LRU cache capacity (admin only)."""
        self._only_admin(ctx)
        if new_capacity <= 0:
            raise InvalidParameters("LRU cache capacity must be positive")

        # Evict tokens if new capacity is smaller than current size
        while self.lru_cache_size > new_capacity:
            self._evict_lru_tail()

        self.lru_cache_capacity = new_capacity

    @view
    def search(self, keyword: str, number: int, offset: int) -> str:
        """Search for a tokens with Symbol or Name matching the keyword. Te output has at most 200 tokens and offset at most 1,000,000"""
        LIMIT = 200
        OFFSET_LIMIT = 1000000
        keyword = keyword.upper().strip()
        number = max(number, 0)
        offset = max(offset, 0)
        offset = min(offset, OFFSET_LIMIT)

        symbol_list = []
        name_list = []

        if keyword in self.symbol_dict:
            symbol_list = self.symbol_dict[keyword]
        if keyword in self.name_dict:
            name_list = self.name_dict[keyword]

        results = []
        len_symbols = len(symbol_list)
        symbol_set = set()

        if offset < len_symbols:
            count_from_symbols = min(number, len_symbols - offset, LIMIT)
            for i in range(offset, offset + count_from_symbols):
                results.append(symbol_list[i].hex())
                symbol_set.add(symbol_list[i])

        if len(results) < min(number, LIMIT):
            remaining_needed = min(number, LIMIT) - len(results)

            names_to_skip = max(0, offset - len_symbols)

            for i in range(0, min(len(name_list), offset + remaining_needed)):
                item = name_list[i]
                if item in symbol_set:
                    continue

                if names_to_skip > 0:
                    names_to_skip -= 1
                    continue

                results.append(item.hex())
                remaining_needed -= 1

                if remaining_needed == 0:
                    break

        return " ".join(results)

    @view
    def get_token_info(self, token_uid: TokenUid) -> TokenInfo:
        """Get detailed information about a token."""
        return self._get_token(token_uid)

    @view
    def get_last_n_tokens(self, number: int, offset: TokenUid) -> str:
        """Get N most recently accessed tokens from LRU cache starting after offset. N <= 200."""
        LIMIT = 200
        number = max(number, 0)
        last_tokens = []
        current = self.lru_head
        if offset in self.tokens and offset != self.lru_null_token:
            current = self.lru_null_token
            if offset in self.lru_next:
                current = self.lru_next[offset]

        for _ in range(min(number, self.lru_cache_size, LIMIT)):
            if current == self.lru_null_token:
                break
            last_tokens.append(current.hex())
            if current in self.lru_next:
                current = self.lru_next[current]
            else:
                current = self.lru_null_token

        return " ".join(last_tokens)

    @view
    def get_newest_n_tokens(self, number: int, offset: int) -> str:
        """Get N newly created tokens after a given offset (reverse order). N <= 200."""
        LIMIT = 200
        number = max(number, 0)
        offset = max(offset, 0)
        n = len(self.all_tokens)

        available_tokens = max(0, n - offset)
        number = min(number, available_tokens, LIMIT)
        newest_tokens = []

        for i in range(-1 - offset, -1 - offset - number, -1):
            newest_tokens.append(self.all_tokens[i].hex())

        return " ".join(newest_tokens)

    @view
    def get_oldest_n_tokens(self, number: int, offset: int) -> str:
        """Get N oldest tokens after a given offset. N <= 200."""
        LIMIT = 200
        number = max(number, 0)
        offset = max(offset, 0)
        oldest_tokens = []
        n = len(self.all_tokens)

        for i in range(offset, min(offset + number, n, LIMIT)):
            oldest_tokens.append(self.all_tokens[i].hex())

        return " ".join(oldest_tokens)

    @view
    def get_recently_graduated_tokens(self, number: int, offset: int) -> str:
        """Get N recently graduated tokens (reverse order). N <= 200."""
        LIMIT = 200
        number = max(number, 0)
        offset = max(offset, 0)
        n = len(self.graduated_tokens)

        available_tokens = max(0, n - offset)
        number = min(number, available_tokens, LIMIT)
        recent_graduated_tokens = []

        for i in range(-1 - offset, -1 - offset - number, -1):
            recent_graduated_tokens.append(self.graduated_tokens[i].hex())

        return " ".join(recent_graduated_tokens)

    @view
    def get_tokens_created_by_user(
        self, user_address: CallerId, number: int, offset: int
    ) -> str:
        """Get N newest tokens created by a user after a given offset (reverse order). N <= 200."""
        LIMIT = 200
        number = max(number, 0)
        offset = max(offset, 0)
        newest_tokens = []
        token_list = []
        if user_address in self.user_creations:
            token_list = self.user_creations[user_address]
        n = len(token_list)

        available_tokens = max(0, n - offset)
        number = min(number, available_tokens, LIMIT)

        for i in range(-1 - offset, -1 - offset - number, -1):
            newest_tokens.append(token_list[i].hex())

        return " ".join(newest_tokens)

    @view
    def get_user_balance(self, user_address: CallerId, number: int, offset: int) -> str:
        """Get N token balances of a user after a given offset. N <= 200."""
        LIMIT = 200
        number = max(number, 1)
        offset = max(offset, 0)
        if user_address not in self.user_balances and offset == 0:
            return HATHOR_TOKEN_UID.hex() + "_" + "0"

        user_balance = []
        balance = 0
        if offset == 0:
            if HATHOR_TOKEN_UID in self.user_balances[user_address]:
                offset = 1
                balance = self.user_balances[user_address][HATHOR_TOKEN_UID]
            user_balance.append(HATHOR_TOKEN_UID.hex() + "_" + str(balance))

        n = len(self.user_balance_tokens[user_address])
        last_index = offset
        for i in range(
            offset,
            min(offset + (number - len(user_balance)), n, LIMIT - len(user_balance)),
        ):
            token_uid = self.user_balance_tokens[user_address][i]
            if token_uid == HATHOR_TOKEN_UID:
                continue
            balance = self.user_balances[user_address][token_uid]
            user_balance.append(token_uid.hex() + "_" + str(balance))
            last_index = i + 1

        if len(user_balance) < number and len(user_balance) < LIMIT and last_index < n:
            token_uid = self.user_balance_tokens[user_address][last_index]
            balance = self.user_balances[user_address][token_uid]
            user_balance.append(token_uid.hex() + "_" + str(balance))

        return " ".join(user_balance)

    @view
    def get_user_token_balance(self, address: CallerId, token_uid: TokenUid) -> Amount:
        """Get the balance of a user for a specific token."""
        if not token_uid == HATHOR_TOKEN_UID:
            self._validate_token_exists(token_uid)

        if (
            address not in self.user_balances
            or token_uid not in self.user_balances[address]
        ):
            return Amount(0)

        return self.user_balances[address][token_uid]

    @view
    def quote_buy(self, token_uid: TokenUid, htr_amount: Amount) -> dict[str, int]:
        """
        Quote buying tokens with HTR.

        The "recommended_htr_amount" is how many htr should be payed to buy the "amount_out" returned.
        It only differs from "htr_amout" when the provided value is invalid.
        """
        token_data = self._get_token_data(token_uid)

        if token_data.is_migrated:
            raise InvalidState("Contract has migrated")

        # Calculate and apply buy fee using ceiling division
        fee_amount = self._extract_fee(
            htr_amount, self.buy_fee_rate + self.creator_fee_rate
        )
        net_amount = Amount(htr_amount - fee_amount)

        tokens_out = self._calculate_tokens_out(token_uid, net_amount)
        tokens_to_graduate = Amount(
            token_data.token_reserve - token_data.total_supply // 5
        )

        recommended_htr_amount = htr_amount
        # Guarantee that the market cap will be met in order to graduate:
        if tokens_out >= tokens_to_graduate:
            tokens_out = tokens_to_graduate

            net_amount = self._calculate_htr_needed(token_uid, tokens_out)
            fee_amount = self._calculate_fee(
                net_amount, self.buy_fee_rate + self.creator_fee_rate
            )
            recommended_htr_amount = Amount(net_amount + fee_amount)

        price_impact = self._calculate_price_impact(
            token_uid, Amount(token_data.token_reserve - tokens_out)
        )

        return {
            "price_for_tokens": net_amount,
            "payed_fees": fee_amount,
            "total_payment": recommended_htr_amount,
            "amount_received": tokens_out,
            "price_impact": price_impact,
        }

    @view
    def quote_sell(self, token_uid: TokenUid, token_amount: Amount) -> dict[str, int]:
        """Quote selling tokens for HTR."""
        token_data = self._get_token_data(token_uid)

        if token_data.is_migrated:
            raise InvalidState("Contract has migrated")

        htr_out = self._calculate_htr_out(token_uid, token_amount)

        # Apply sell fee
        sell_fee_amount = self._calculate_fee(htr_out, self.sell_fee_rate)
        net_amount = Amount(htr_out - sell_fee_amount)

        # Calculate price impact
        price_impact = self._calculate_price_impact(
            token_uid, Amount(token_data.token_reserve + token_amount)
        )

        return {
            "tokens_sell_for": htr_out,
            "payed_fees": sell_fee_amount,
            "amount_received": net_amount,
            "tokens_sold": token_amount,
            "price_impact": price_impact,
        }

    @view
    def get_platform_stats(self) -> dict[str, int]:
        """Get platform-wide statistics."""
        return {
            "total_tokens_created": self.total_tokens_created,
            "total_tokens_migrated": self.total_tokens_migrated,
            "platform_fees_collected": self.collected_buy_fees
            + self.collected_sell_fees
            + self.collected_operation_fees,
        }

    @view
    def get_platform_info(self) -> PlatformInfo:
        """Get platform information available only for admins."""
        return PlatformInfo(
            self.admin_address.hex(),
            self.dozer_pool_manager_id.hex(),
            self.buy_fee_rate,
            self.sell_fee_rate,
            self.creator_fee_rate,
            self.default_pool_fee_rate,
            self.default_target_market_cap,
            self.default_graduation_fee,
            self.default_token_total_supply,
            self.collected_buy_fees,
            self.collected_sell_fees,
            self.collected_operation_fees,
            self.lru_cache_capacity,
            self.lru_cache_size,
        )

    @view
    def get_pool(self, token_uid: TokenUid) -> str:
        """Get the pool key for a migrated token."""
        token_data = self._get_token_data(token_uid)

        if not token_data.is_migrated:
            raise InvalidState("Token not migrated")

        return token_data.pool_key

    @view
    def front_quote_exact_tokens_for_tokens(
        self, token_uid: TokenUid, amount_in: Amount, token_in: TokenUid
    ) -> dict[str, Amount]:
        """Quote swap for exact input amount after token has migrated to Dozer pool.

        Args:
            token_uid: The token that was migrated
            amount_in: Exact amount of input tokens
            token_in: Token being swapped in (must be token_uid or HTR)

        Returns:
            Dict with 'amount_out' showing how many tokens will be received
        """
        token_data = self._get_token_data(token_uid)

        if not token_data.is_migrated:
            raise InvalidState("Token not migrated")

        if token_in not in (token_uid, HATHOR_TOKEN_UID):
            raise InvalidParameters("Invalid token to swap")

        # Get pool reserves from Dozer using the oasis pattern
        # Reserves are returned in sorted order by token UID
        reserve_a, reserve_b = (
            self.syscall.get_contract(self.dozer_pool_manager_id, blueprint_id=None)
            .view()
            .get_reserves(token_uid, HATHOR_TOKEN_UID, self.default_pool_fee_rate)
        )

        # Determine which reserve corresponds to which token based on sorting
        # If token_uid < HATHOR_TOKEN_UID, then reserve_a=token, reserve_b=HTR
        if token_uid < HATHOR_TOKEN_UID:
            reserve_token = reserve_a
            reserve_htr = reserve_b
        else:
            reserve_token = reserve_b
            reserve_htr = reserve_a

        # Determine which reserve is in/out based on token_in
        if token_in == token_uid:
            reserve_in, reserve_out = reserve_token, reserve_htr
        else:
            reserve_in, reserve_out = reserve_htr, reserve_token

        # Calculate amount out using Dozer's formula
        # fee_denominator is always 1000 in Dozer pools
        amount_out = (
            self.syscall.get_contract(self.dozer_pool_manager_id, blueprint_id=None)
            .view()
            .get_amount_out(
                amount_in, reserve_in, reserve_out, self.default_pool_fee_rate, 1000
            )
        )

        return {"amount_out": amount_out}

    @view
    def front_quote_tokens_for_exact_tokens(
        self, token_uid: TokenUid, amount_out: Amount, token_in: TokenUid
    ) -> dict[str, Amount]:
        """Quote swap for exact output amount after token has migrated to Dozer pool.

        Args:
            token_uid: The token that was migrated
            amount_out: Exact amount of output tokens desired
            token_in: Token being swapped in (must be token_uid or HTR)

        Returns:
            Dict with 'amount_in' showing how many input tokens are needed
        """
        token_data = self._get_token_data(token_uid)

        if not token_data.is_migrated:
            raise InvalidState("Token not migrated")

        if token_in not in (token_uid, HATHOR_TOKEN_UID):
            raise InvalidParameters("Invalid token to swap")

        # Get pool reserves from Dozer using the oasis pattern
        # Reserves are returned in sorted order by token UID
        reserve_a, reserve_b = (
            self.syscall.get_contract(self.dozer_pool_manager_id, blueprint_id=None)
            .view()
            .get_reserves(token_uid, HATHOR_TOKEN_UID, self.default_pool_fee_rate)
        )

        # Determine which reserve corresponds to which token based on sorting
        # If token_uid < HATHOR_TOKEN_UID, then reserve_a=token, reserve_b=HTR
        if token_uid < HATHOR_TOKEN_UID:
            reserve_token = reserve_a
            reserve_htr = reserve_b
        else:
            reserve_token = reserve_b
            reserve_htr = reserve_a

        # Determine which reserve is in/out based on token_in
        if token_in == token_uid:
            reserve_in, reserve_out = reserve_token, reserve_htr
        else:
            reserve_in, reserve_out = reserve_htr, reserve_token

        # Calculate amount in needed using Dozer's formula
        # fee_denominator is always 1000 in Dozer pools
        amount_in = (
            self.syscall.get_contract(self.dozer_pool_manager_id, blueprint_id=None)
            .view()
            .get_amount_in(
                amount_out, reserve_in, reserve_out, self.default_pool_fee_rate, 1000
            )
        )

        return {"amount_in": amount_in}

    @public
    def upgrade_contract(
        self, ctx: Context, new_blueprint_id: BlueprintId, new_version: str
    ) -> None:
        """Upgrade the contract to a new blueprint version.

        Args:
            ctx: Transaction context
            new_blueprint_id: The blueprint ID to upgrade to
            new_version: Version string for the new blueprint (e.g., "1.1.0")

        Raises:
            Unauthorized: If caller is not the contract creator
            InvalidVersion: If new version is not higher than current version
        """
        # Only the original contract creator can upgrade the blueprint.
        self._only_creator(ctx)

        # Validate version is newer
        if not self._is_version_higher(new_version, self.contract_version):
            raise InvalidParameters(
                f"New version {new_version} must be higher than current {self.contract_version}"
            )

        old_version = self.contract_version
        self.contract_version = new_version

        self.log.info(
            "upgrading contract",
            old_version=old_version,
            new_version=new_version,
            new_blueprint_id=str(new_blueprint_id),
            caller=str(ctx.caller_id),
        )

        # Perform the upgrade
        self.syscall.change_blueprint(new_blueprint_id)

    def _is_version_higher(self, new_version: str, current_version: str) -> bool:
        """Compare semantic versions (e.g., "1.2.3").

        Returns True if new_version > current_version.
        Returns False if versions are malformed or equal.
        """
        # Split versions by '.'
        new_parts_str = new_version.split(".")
        current_parts_str = current_version.split(".")

        # Check if all parts are valid integers
        new_parts: list[int] = []
        for part in new_parts_str:
            # Simple check: all characters must be digits
            if not part or not all(c in "0123456789" for c in part):
                return False  # Invalid format
            new_parts.append(int(part))

        current_parts: list[int] = []
        for part in current_parts_str:
            if not part or not all(c in "0123456789" for c in part):
                return False  # Invalid format
            current_parts.append(int(part))

        # Pad shorter version with zeros
        max_len = (
            len(new_parts)
            if len(new_parts) > len(current_parts)
            else len(current_parts)
        )
        while len(new_parts) < max_len:
            new_parts.append(0)
        while len(current_parts) < max_len:
            current_parts.append(0)

        # Compare versions
        return new_parts > current_parts

    @view
    def get_contract_version(self) -> str:
        """Get the current contract version.

        Returns:
            Version string (e.g., "1.0.0")
        """
        return self.contract_version
