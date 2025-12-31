from typing import NamedTuple
from hathor import (
    Address,
    Blueprint,
    Context,
    NCDepositAction,
    NCWithdrawalAction,
    NCFail,
    TokenUid,
    export,
    public,
    view,
)

#
# === OTC ESCROW SWAP BLUEPRINT ===
#
# Production OTC escrow nano-contract for swapping two tokens between a maker and a taker.
#
# Features:
# - Public escrows and directed escrows (maker can restrict the taker identity)
# - Stage-based expiry (OPEN/ACCEPTED use open expiry; FUNDED_MAKER uses maker-funded expiry)
# - Maker-first funding order
# - Cancel-before-funding (maker-only)
# - Settlement withdrawals with protocol fees (bps, ceil rounding)
# - Refunds after expiry (no fees)
# - Website-friendly views, counters, and escrow-id pagination
#
# === FEE CONSTANTS ===
#

MAX_PROTOCOL_FEE_BPS = 200  # 2.00%


#
# === EXPIRY CONSTANTS (defaults; can be overridden at initialize / by owner) ===
#

DEFAULT_OPEN_EXPIRY_SECS = 30 * 24 * 60 * 60          # 30 days
DEFAULT_MAKER_FUNDED_EXPIRY_SECS = 7 * 24 * 60 * 60   # 7 days
DEFAULT_MIN_EXPIRY_SECS = 60                           # 1 minute
DEFAULT_MAX_EXPIRY_SECS = 365 * 24 * 60 * 60          # 365 days


#
# === STATUS CONSTANTS ===
#

STATUS_OPEN = 0            # maker set terms, no taker yet
STATUS_ACCEPTED = 1        # taker recorded, not funded
STATUS_FUNDED_MAKER = 2
STATUS_FUNDED_BOTH = 3
STATUS_EXECUTED = 4        # terminal: maker and taker withdrew swap outputs
STATUS_REFUNDED = 5        # terminal: all funded sides refunded after expiry
STATUS_CANCELLED = -2      # maker cancelled before any funding


#
# === VIEW RETURN TYPES (JSON-friendly) ===
#

class EscrowDetails(NamedTuple):
    maker: str          # base58 string
    taker: str          # base58 string or "" if none yet
    maker_token: str    # token uid hex
    maker_amount: int
    taker_token: str    # token uid hex
    taker_amount: int
    maker_funded: bool
    taker_funded: bool
    maker_withdrawn: bool
    taker_withdrawn: bool
    is_cancelled: bool
    status: int         # -1 means "escrow not found"


class EscrowDetailsFull(NamedTuple):
    maker: str
    taker: str
    maker_token: str
    maker_amount: int
    taker_token: str
    taker_amount: int
    maker_funded: bool
    taker_funded: bool
    maker_withdrawn: bool
    taker_withdrawn: bool
    maker_refunded: bool
    taker_refunded: bool

 # --- Expiry (stage-based) ---
    open_expiry_timestamp: int
    maker_funded_expiry_timestamp: int
    is_open_expired: bool
    is_maker_funded_expired: bool
    is_expired: bool

    is_directed: bool
    directed_taker: str

    is_cancelled: bool
    is_refunded: bool
    status: int


class ConfigView(NamedTuple):
    owner: str
    fee_recipient: str
    protocol_fee_bps: int
    default_open_expiry_secs: int
    default_maker_funded_expiry_secs: int
    min_expiry_secs: int
    max_expiry_secs: int


class FeeQuoteView(NamedTuple):
    maker_fee: int
    taker_fee: int
    maker_net_receive: int  # maker receives taker_token net of taker_fee
    taker_net_receive: int  # taker receives maker_token net of maker_fee


class EscrowIdsPage(NamedTuple):
    cursor_in: int
    limit: int
    next_cursor: int
    ids: list[int]

class CountersView(NamedTuple):
    total_escrows: int
    count_open: int
    count_accepted: int
    count_funded_maker: int
    count_funded_both: int
    count_executed: int
    count_refunded: int
    count_cancelled: int
    count_public: int
    count_directed: int


#
# === CUSTOM FAIL TYPES ===
#

class EscrowError(NCFail):
    """Base class for escrow-related failures."""


class InvalidConfig(EscrowError):
    """Invalid initialization or configuration parameters."""


class Unauthorized(EscrowError):
    """Caller lacks permission for this operation."""


class InvalidEscrow(EscrowError):
    """Invalid escrow state or parameters."""


class InvalidActions(EscrowError):
    """Invalid deposit/withdrawal actions."""


class InvalidToken(EscrowError):
    """Invalid token for a given side."""


@export
class OtcEscrowSwap(Blueprint):
    """
    Minimal 1-for-1 OTC escrow for swapping two tokens between a maker and a taker.

    Identity model:
      - owner/dev: caller identity at initialize()
      - maker: caller identity at open_escrow/open_escrow_directed
      - taker: caller identity at accept_escrow

    Fees model:
      - protocol_fee_bps is per-contract-instance configurable, bounded by MAX_PROTOCOL_FEE_BPS
      - fee_recipient is the ONLY identity allowed to withdraw aggregated protocol fees
      - protocol fees are realized on withdraw() settlement (not on refunds)

    Expiry model (stage-based):
      - open_expiry_timestamp applies to STATUS_OPEN / STATUS_ACCEPTED
      - maker_funded_expiry_timestamp applies to STATUS_FUNDED_MAKER
      - once STATUS_FUNDED_BOTH, expiry is no longer checked (settlement expected)
      - refund() is allowed when the escrow is expired for its current stage.
    """

 # === Contract-level roles/config ===
    owner: Address
    fee_recipient: Address
    protocol_fee_bps: int

 # Expiry config
    default_open_expiry_secs: int
    default_maker_funded_expiry_secs: int
    min_expiry_secs: int
    max_expiry_secs: int

 # === Per-escrow state ===
    makers: dict[int, Address]
    takers: dict[int, Address]

 # Directed escrow addon
    is_directed: dict[int, bool]            # escrow_id -> True if directed
    directed_takers: dict[int, Address]     # escrow_id -> allowed taker if directed

    maker_tokens: dict[int, TokenUid]
    maker_amounts: dict[int, int]

    taker_tokens: dict[int, TokenUid]
    taker_amounts: dict[int, int]

    maker_funded: dict[int, bool]
    taker_funded: dict[int, bool]

    maker_withdrawn: dict[int, bool]
    taker_withdrawn: dict[int, bool]

    maker_refunded: dict[int, bool]
    taker_refunded: dict[int, bool]

 # Stage expiries (unix seconds; 0 means not set)
    open_expiry_timestamps: dict[int, int]
    maker_funded_expiry_timestamps: dict[int, int]

    statuses: dict[int, int]
    next_escrow_id: int

 # For website paging
    escrow_ids: list[int]

 # === Counters (website stats) ===
    total_escrows: int
    count_open: int
    count_accepted: int
    count_funded_maker: int
    count_funded_both: int
    count_executed: int
    count_refunded: int
    count_cancelled: int
    count_public: int
    count_directed: int

 # === Aggregated protocol fee balances (per token uid) ===
    protocol_fee_balances: dict[TokenUid, int]

 #
 # === INITIALIZE ===
 #

    @public
    def initialize(
        self,
        ctx: Context,
        fee_recipient: Address,
        protocol_fee_bps: int,
        default_open_expiry_secs: int,
        default_maker_funded_expiry_secs: int,
        min_expiry_secs: int,
        max_expiry_secs: int,
    ) -> None:
        """
        Initializes contract storage and configuration.

        Roles:
          - owner/dev inferred from caller identity at initialize()
          - fee_recipient set explicitly

        Bounds:
          - 0 <= protocol_fee_bps <= MAX_PROTOCOL_FEE_BPS
          - expiry seconds are bounded and must satisfy: 0 < min <= default <= max
        """
        owner = self._get_caller_id(ctx)

        if protocol_fee_bps < 0 or protocol_fee_bps > MAX_PROTOCOL_FEE_BPS:
            raise InvalidConfig("protocol_fee_bps out of bounds")

 # Expiry config validation
        if min_expiry_secs <= 0:
            raise InvalidConfig("min_expiry_secs must be > 0")
        if max_expiry_secs < min_expiry_secs:
            raise InvalidConfig("max_expiry_secs must be >= min_expiry_secs")

        if default_open_expiry_secs < min_expiry_secs or default_open_expiry_secs > max_expiry_secs:
            raise InvalidConfig("default_open_expiry_secs out of bounds")
        if default_maker_funded_expiry_secs < min_expiry_secs or default_maker_funded_expiry_secs > max_expiry_secs:
            raise InvalidConfig("default_maker_funded_expiry_secs out of bounds")

        self.owner = owner
        self.fee_recipient = fee_recipient
        self.protocol_fee_bps = protocol_fee_bps

        self.default_open_expiry_secs = default_open_expiry_secs
        self.default_maker_funded_expiry_secs = default_maker_funded_expiry_secs
        self.min_expiry_secs = min_expiry_secs
        self.max_expiry_secs = max_expiry_secs

 # --- Core escrow storage ---
        self.makers = {}
        self.takers = {}

 # --- Directed escrow addon storage ---
        self.is_directed = {}
        self.directed_takers = {}

        self.maker_tokens = {}
        self.maker_amounts = {}

        self.taker_tokens = {}
        self.taker_amounts = {}

        self.maker_funded = {}
        self.taker_funded = {}

        self.maker_withdrawn = {}
        self.taker_withdrawn = {}

        self.maker_refunded = {}
        self.taker_refunded = {}

        self.open_expiry_timestamps = {}
        self.maker_funded_expiry_timestamps = {}

        self.statuses = {}
        self.next_escrow_id = 0

        self.escrow_ids = []

 # --- Counters ---
        self.total_escrows = 0
        self.count_open = 0
        self.count_accepted = 0
        self.count_funded_maker = 0
        self.count_funded_both = 0
        self.count_executed = 0
        self.count_refunded = 0
        self.count_cancelled = 0
        self.count_public = 0
        self.count_directed = 0

        self.protocol_fee_balances = {}

 #
 # === OWNER-ONLY ADMIN ===
 #

    @public
    def set_fee_config(self, ctx: Context, fee_recipient: Address, protocol_fee_bps: int) -> None:
        """Owner-only: update fee recipient and protocol fee rate within bounds."""
        caller = self._get_caller_id(ctx)
        if caller != self.owner:
            raise Unauthorized("Only the contract owner can update fee configuration")

        if protocol_fee_bps < 0 or protocol_fee_bps > MAX_PROTOCOL_FEE_BPS:
            raise InvalidConfig("protocol_fee_bps out of bounds")

        self.fee_recipient = fee_recipient
        self.protocol_fee_bps = protocol_fee_bps

    @public
    def set_expiry_config(
        self,
        ctx: Context,
        default_open_expiry_secs: int,
        default_maker_funded_expiry_secs: int,
        min_expiry_secs: int,
        max_expiry_secs: int,
    ) -> None:
        """Owner-only: update expiry defaults and bounds."""
        caller = self._get_caller_id(ctx)
        if caller != self.owner:
            raise Unauthorized("Only the contract owner can update expiry configuration")

        if min_expiry_secs <= 0:
            raise InvalidConfig("min_expiry_secs must be > 0")
        if max_expiry_secs < min_expiry_secs:
            raise InvalidConfig("max_expiry_secs must be >= min_expiry_secs")

        if default_open_expiry_secs < min_expiry_secs or default_open_expiry_secs > max_expiry_secs:
            raise InvalidConfig("default_open_expiry_secs out of bounds")
        if default_maker_funded_expiry_secs < min_expiry_secs or default_maker_funded_expiry_secs > max_expiry_secs:
            raise InvalidConfig("default_maker_funded_expiry_secs out of bounds")

        self.default_open_expiry_secs = default_open_expiry_secs
        self.default_maker_funded_expiry_secs = default_maker_funded_expiry_secs
        self.min_expiry_secs = min_expiry_secs
        self.max_expiry_secs = max_expiry_secs

 #
 # === INTERNAL HELPERS ===
 #

    def _get_caller_id(self, ctx: Context) -> Address:
        """Returns the caller identity (CallerID)."""
        caller = ctx.get_caller_address()
        if caller is None:
            raise InvalidEscrow("Caller identity is not available")
        return caller

    def _ceil_fee(self, amount: int) -> int:
        """Ceil(amount * bps / 10_000) using integer math."""
        bps = self.protocol_fee_bps
        if bps <= 0 or amount <= 0:
            return 0
        return (amount * bps + 9999) // 10000

    def _inc_status_counter(self, status: int, delta: int) -> None:
        if delta == 0:
            return
        if status == STATUS_OPEN:
            self.count_open += delta
        elif status == STATUS_ACCEPTED:
            self.count_accepted += delta
        elif status == STATUS_FUNDED_MAKER:
            self.count_funded_maker += delta
        elif status == STATUS_FUNDED_BOTH:
            self.count_funded_both += delta
        elif status == STATUS_EXECUTED:
            self.count_executed += delta
        elif status == STATUS_REFUNDED:
            self.count_refunded += delta
        elif status == STATUS_CANCELLED:
            self.count_cancelled += delta

    def _set_status(self, escrow_id: int, new_status: int) -> None:
        """Set escrow status and keep counters consistent."""
        old_status = self.statuses.get(escrow_id)
        if old_status == new_status:
            return
        if old_status is not None:
            self._inc_status_counter(old_status, -1)
        self.statuses[escrow_id] = new_status
        self._inc_status_counter(new_status, 1)

    def _maybe_finalize_status(self, escrow_id: int) -> None:
        """Set STATUS_EXECUTED once maker and taker have withdrawn their swap outputs."""
        if self.maker_withdrawn.get(escrow_id, False) and self.taker_withdrawn.get(escrow_id, False):
            self._set_status(escrow_id, STATUS_EXECUTED)

    def _process_withdraw(self, ctx: Context, token_uid: TokenUid, expected_amount: int) -> None:
        """Validate that this call withdraws exactly expected_amount of token_uid."""
        if set(ctx.actions.keys()) != {token_uid}:
            raise InvalidActions("Withdraw must operate on exactly one expected token")

        action = ctx.get_single_action(token_uid)
        if not isinstance(action, NCWithdrawalAction):
            raise InvalidActions("Expected a withdrawal action")
        if action.amount != expected_amount:
            raise InvalidActions("Incorrect withdrawal amount")

    def _validate_expiry_timestamp_or_default(self, ctx: Context, expiry_timestamp: int) -> int:
        """
        Normalize expiry_timestamp:
          - if expiry_timestamp == 0: use now + default_open_expiry_secs
          - else: validate it is within [now+min, now+max]
        Returns an absolute unix timestamp.
        """
        now = ctx.block.timestamp
        if expiry_timestamp == 0:
            return now + self.default_open_expiry_secs

        if expiry_timestamp < 0:
            raise InvalidConfig("Expiry timestamp must be >= 0")

        delta = expiry_timestamp - now
        if delta < self.min_expiry_secs:
            raise InvalidConfig("Expiry timestamp is below min_expiry_secs from now")
        if delta > self.max_expiry_secs:
            raise InvalidConfig("Expiry timestamp exceeds max_expiry_secs from now")
        return expiry_timestamp

    def _is_open_expired(self, ctx: Context, escrow_id: int) -> bool:
        ts = self.open_expiry_timestamps.get(escrow_id, 0)
        return (ts > 0) and (ctx.block.timestamp >= ts)

    def _is_maker_funded_expired(self, ctx: Context, escrow_id: int) -> bool:
        ts = self.maker_funded_expiry_timestamps.get(escrow_id, 0)
        return (ts > 0) and (ctx.block.timestamp >= ts)

    def _is_expired_for_current_stage(self, ctx: Context, escrow_id: int) -> bool:
        status = self.statuses.get(escrow_id, -999)
        if status in (STATUS_OPEN, STATUS_ACCEPTED):
            return self._is_open_expired(ctx, escrow_id)
        if status == STATUS_FUNDED_MAKER:
            return self._is_maker_funded_expired(ctx, escrow_id)
        # FUNDED_BOTH and later do not check expiry for settlement, but refund is blocked anyway by status checks.
        return False

    def _assert_not_expired_for_actions(self, ctx: Context, escrow_id: int) -> None:
        """
        For "forward" actions (accept, funding, withdraw), enforce stage expiry.
        """
        if self._is_expired_for_current_stage(ctx, escrow_id):
            raise InvalidEscrow("Escrow has expired")

    def _assert_exists(self, escrow_id: int) -> None:
        if escrow_id < 0:
            raise InvalidEscrow("Escrow ID must be non-negative")
        if escrow_id >= self.next_escrow_id:
            raise InvalidEscrow("Escrow ID does not exist")

 #
 # === OPEN ESCROW (PUBLIC) ===
 #

    @public
    def open_escrow(
        self,
        ctx: Context,
        maker_token: TokenUid,
        maker_amount: int,
        taker_token: TokenUid,
        taker_amount: int,
    ) -> int:
        """
        Open escrow using the contract's default open expiry.

        NOTE: Open escrows always get an expiry by default.
        """
        return self.open_escrow_with_expiry(
            ctx=ctx,
            maker_token=maker_token,
            maker_amount=maker_amount,
            taker_token=taker_token,
            taker_amount=taker_amount,
            expiry_timestamp=0,  # 0 = use default
        )

    @public
    def open_escrow_with_expiry(
        self,
        ctx: Context,
        maker_token: TokenUid,
        maker_amount: int,
        taker_token: TokenUid,
        taker_amount: int,
        expiry_timestamp: int,
    ) -> int:
        """
        Open escrow with an explicit expiry timestamp.

        Convention:
          - expiry_timestamp == 0 => use default_open_expiry_secs from "now"
          - else => absolute unix timestamp, validated against min/max bounds
        """
        maker = self._get_caller_id(ctx)

        if maker_amount <= 0:
            raise InvalidConfig("Maker amount must be > 0")
        if taker_amount <= 0:
            raise InvalidConfig("Taker amount must be > 0")
        if maker_token == taker_token:
            raise InvalidConfig("Maker and taker tokens must differ")

        open_expiry_ts = self._validate_expiry_timestamp_or_default(ctx, expiry_timestamp)

        escrow_id = self.next_escrow_id
        self.makers[escrow_id] = maker

        # Public escrow: not directed
        self.is_directed[escrow_id] = False
        if escrow_id in self.directed_takers:
            del self.directed_takers[escrow_id]
        if escrow_id in self.takers:
            del self.takers[escrow_id]

        self.maker_tokens[escrow_id] = maker_token
        self.maker_amounts[escrow_id] = maker_amount

        self.taker_tokens[escrow_id] = taker_token
        self.taker_amounts[escrow_id] = taker_amount

        self.maker_funded[escrow_id] = False
        self.taker_funded[escrow_id] = False

        self.maker_withdrawn[escrow_id] = False
        self.taker_withdrawn[escrow_id] = False

        self.maker_refunded[escrow_id] = False
        self.taker_refunded[escrow_id] = False

        self.open_expiry_timestamps[escrow_id] = open_expiry_ts
        self.maker_funded_expiry_timestamps[escrow_id] = 0

        self._set_status(escrow_id, STATUS_OPEN)

        self.next_escrow_id = escrow_id + 1
        self.escrow_ids.append(escrow_id)

 # Counters
        self.total_escrows += 1
        self.count_public += 1
        return escrow_id

 #
 # === OPEN ESCROW (DIRECTED) ===
 #

    @public
    def open_escrow_directed(
        self,
        ctx: Context,
        maker_token: TokenUid,
        maker_amount: int,
        taker_token: TokenUid,
        taker_amount: int,
        directed_taker: Address,
    ) -> int:
        """Open directed escrow using the contract's default open expiry."""
        return self.open_escrow_directed_with_expiry(
            ctx=ctx,
            maker_token=maker_token,
            maker_amount=maker_amount,
            taker_token=taker_token,
            taker_amount=taker_amount,
            expiry_timestamp=0,  # 0 = use default
            directed_taker=directed_taker,
        )

    @public
    def open_escrow_directed_with_expiry(
        self,
        ctx: Context,
        maker_token: TokenUid,
        maker_amount: int,
        taker_token: TokenUid,
        taker_amount: int,
        expiry_timestamp: int,
        directed_taker: Address,
    ) -> int:
        """
        Open directed escrow with an explicit expiry timestamp.

        Convention:
          - expiry_timestamp == 0 => use default_open_expiry_secs from "now"
          - else => absolute unix timestamp, validated against min/max bounds
        """
        maker = self._get_caller_id(ctx)

        if directed_taker == maker:
            raise InvalidConfig("Maker and directed taker must be different identities")
        if maker_amount <= 0:
            raise InvalidConfig("Maker amount must be > 0")
        if taker_amount <= 0:
            raise InvalidConfig("Taker amount must be > 0")
        if maker_token == taker_token:
            raise InvalidConfig("Maker and taker tokens must differ")

        open_expiry_ts = self._validate_expiry_timestamp_or_default(ctx, expiry_timestamp)

        escrow_id = self.next_escrow_id
        self.makers[escrow_id] = maker

        if escrow_id in self.takers:
            del self.takers[escrow_id]

        self.is_directed[escrow_id] = True
        self.directed_takers[escrow_id] = directed_taker

        self.maker_tokens[escrow_id] = maker_token
        self.maker_amounts[escrow_id] = maker_amount

        self.taker_tokens[escrow_id] = taker_token
        self.taker_amounts[escrow_id] = taker_amount

        self.maker_funded[escrow_id] = False
        self.taker_funded[escrow_id] = False

        self.maker_withdrawn[escrow_id] = False
        self.taker_withdrawn[escrow_id] = False

        self.maker_refunded[escrow_id] = False
        self.taker_refunded[escrow_id] = False

        self.open_expiry_timestamps[escrow_id] = open_expiry_ts
        self.maker_funded_expiry_timestamps[escrow_id] = 0

        self._set_status(escrow_id, STATUS_OPEN)

        self.next_escrow_id = escrow_id + 1
        self.escrow_ids.append(escrow_id)

 # Counters
        self.total_escrows += 1
        self.count_directed += 1
        return escrow_id

 #
 # === DIRECTED TAKER ADMIN (MAKER-ONLY, OPEN ONLY) ===
 #

    @public
    def set_directed_taker(self, ctx: Context, escrow_id: int, new_directed_taker: Address) -> None:
        """Maker-only: update directed taker identity while escrow is still OPEN."""
        self._assert_exists(escrow_id)

        caller = self._get_caller_id(ctx)
        maker = self.makers[escrow_id]
        if caller != maker:
            raise Unauthorized("Only maker can update directed taker")

        if not self.is_directed.get(escrow_id, False):
            raise InvalidEscrow("Escrow is not directed")

        status = self.statuses[escrow_id]
        if status != STATUS_OPEN:
            raise InvalidEscrow("Directed taker can only be updated while escrow is OPEN")

        self._assert_not_expired_for_actions(ctx, escrow_id)

        if new_directed_taker == maker:
            raise InvalidConfig("Maker and directed taker must be different identities")

        self.directed_takers[escrow_id] = new_directed_taker

 # Defensive: ensure no taker is recorded while still OPEN
        if escrow_id in self.takers:
            del self.takers[escrow_id]

 #
 # === ACCEPT ESCROW (TAKER = CALLERID) ===
 #

    @public
    def accept_escrow(self, ctx: Context, escrow_id: int) -> None:
        """The taker accepts the terms; no tokens move here."""
        self._assert_exists(escrow_id)

        taker = self._get_caller_id(ctx)
        maker = self.makers[escrow_id]

 # Directed escrow gate
        if self.is_directed.get(escrow_id, False):
            directed = self.directed_takers.get(escrow_id)
            if directed is None:
                raise InvalidEscrow("Directed taker not configured")
            if taker != directed:
                raise Unauthorized("Only the directed taker can accept this escrow")

        if taker == maker:
            raise InvalidConfig("Maker and taker must be different identities")

        status = self.statuses[escrow_id]
        if status == STATUS_CANCELLED:
            raise InvalidEscrow("Escrow has been cancelled")

        self._assert_not_expired_for_actions(ctx, escrow_id)

        if status not in (STATUS_OPEN, STATUS_FUNDED_MAKER, STATUS_ACCEPTED):
            raise InvalidEscrow("Escrow is not in an acceptable state")

        existing_taker = self.takers.get(escrow_id)
        if existing_taker is None:
            self.takers[escrow_id] = taker
        else:
            if taker != existing_taker:
                raise InvalidEscrow("Escrow already accepted by another taker")

        if status == STATUS_OPEN:
            self._set_status(escrow_id, STATUS_ACCEPTED)

 #
 # === CANCEL BEFORE FUNDING (MAKER-ONLY) ===
 #

    @public
    def cancel_before_funding(self, ctx: Context, escrow_id: int) -> None:
        """Maker-only cancellation before any funding has occurred."""
        self._assert_exists(escrow_id)

        caller = self._get_caller_id(ctx)
        if caller != self.makers[escrow_id]:
            raise Unauthorized("Only maker can cancel this escrow")

        status = self.statuses[escrow_id]
        if status not in (STATUS_OPEN, STATUS_ACCEPTED):
            raise InvalidEscrow("Escrow cannot be cancelled in its current state")

        if self.maker_funded[escrow_id] or self.taker_funded[escrow_id]:
            raise InvalidEscrow("Cannot cancel after funding has occurred")

        self._set_status(escrow_id, STATUS_CANCELLED)

 #
 # === FUNDING METHODS ===
 #

    @public(allow_deposit=True)
    def fund_maker(self, ctx: Context, escrow_id: int) -> None:
        """Maker deposits maker_token into the contract."""
        self._assert_exists(escrow_id)

        status = self.statuses[escrow_id]
        if status == STATUS_CANCELLED:
            raise InvalidEscrow("Escrow has been cancelled")
        if status not in (STATUS_OPEN, STATUS_ACCEPTED):
            raise InvalidEscrow("Escrow is not in a state that allows maker funding")

        self._assert_not_expired_for_actions(ctx, escrow_id)

        if self.maker_funded[escrow_id]:
            raise InvalidEscrow("Maker side is already funded")

        caller = self._get_caller_id(ctx)
        if caller != self.makers[escrow_id]:
            raise Unauthorized("Only maker can fund maker side")

        maker_amount = self.maker_amounts[escrow_id]
        expected_token = self.maker_tokens[escrow_id]

        if set(ctx.actions.keys()) != {expected_token}:
            raise InvalidToken("Deposit must include exactly the expected token")

        action = ctx.get_single_action(expected_token)
        if not isinstance(action, NCDepositAction):
            raise InvalidActions("Maker funding must be a deposit")
        if action.amount != maker_amount:
            raise InvalidActions("Incorrect maker deposit amount")

        self.maker_funded[escrow_id] = True
        self._set_status(escrow_id, STATUS_FUNDED_MAKER)

 # Set maker-funded expiry timestamp relative to now (bounded by config).
        self.maker_funded_expiry_timestamps[escrow_id] = ctx.block.timestamp + self.default_maker_funded_expiry_secs

    @public(allow_deposit=True)
    def fund_taker(self, ctx: Context, escrow_id: int) -> None:
        """Taker deposits taker_token into the contract."""
        self._assert_exists(escrow_id)

        status = self.statuses[escrow_id]
        if status == STATUS_CANCELLED:
            raise InvalidEscrow("Escrow has been cancelled")
        if status != STATUS_FUNDED_MAKER:
            raise InvalidEscrow("Maker must fund before taker can fund")

        self._assert_not_expired_for_actions(ctx, escrow_id)

        if self.taker_funded[escrow_id]:
            raise InvalidEscrow("Taker side is already funded")

        caller = self._get_caller_id(ctx)

 # Directed escrow gate: only directed taker may fund.
        if self.is_directed.get(escrow_id, False):
            directed = self.directed_takers.get(escrow_id)
            if directed is None:
                raise InvalidEscrow("Directed taker not configured")
            if caller != directed:
                raise Unauthorized("Only the directed taker can fund taker side")

        taker = self.takers.get(escrow_id)
        if taker is None:
            raise InvalidEscrow("Escrow has not been accepted by a taker")
        if caller != taker:
            raise Unauthorized("Only taker can fund taker side")

        taker_amount = self.taker_amounts[escrow_id]
        expected_token = self.taker_tokens[escrow_id]

        if set(ctx.actions.keys()) != {expected_token}:
            raise InvalidToken("Deposit must include exactly the expected token")

        action = ctx.get_single_action(expected_token)
        if not isinstance(action, NCDepositAction):
            raise InvalidActions("Taker funding must be a deposit")
        if action.amount != taker_amount:
            raise InvalidActions("Incorrect taker deposit amount")

        self.taker_funded[escrow_id] = True
        self._set_status(escrow_id, STATUS_FUNDED_BOTH)

 #
 # === WITHDRAW (SWAP COMPLETION + FEES) ===
 #

    @public(allow_withdrawal=True)
    def withdraw(self, ctx: Context, escrow_id: int) -> None:
        """
        Single withdraw() entrypoint.

        Roles:
          - Maker withdraws taker_token net of taker_fee.
          - Taker withdraws maker_token net of maker_fee.
          - Fee recipient withdraws aggregated protocol fees per token (across escrows).
        """
        if escrow_id < 0:
            raise InvalidEscrow("Escrow ID must be non-negative")

        caller = self._get_caller_id(ctx)

 # --- Protocol fee recipient path (aggregated, per token) ---
        if caller == self.fee_recipient:
            action_tokens = set(ctx.actions.keys())
            if len(action_tokens) != 1:
                raise InvalidActions("Withdraw must operate on exactly one expected token")
            token_uid = next(iter(action_tokens))
            balance = self.protocol_fee_balances.get(token_uid, 0)
            if balance <= 0:
                raise InvalidEscrow("No protocol fees available for this token")

            self._process_withdraw(ctx, token_uid, balance)
            self.protocol_fee_balances[token_uid] = 0
            return

 # --- Maker / Taker withdrawals are escrow-specific ---
        self._assert_exists(escrow_id)

        status = self.statuses[escrow_id]
        if status == STATUS_CANCELLED:
            raise InvalidEscrow("Escrow has been cancelled")
        if status in (STATUS_EXECUTED, STATUS_REFUNDED):
            raise InvalidEscrow("Escrow is already closed")

 # Settlement path checks stage expiry only until FUNDED_BOTH is reached.
        if status != STATUS_FUNDED_BOTH:
            raise InvalidEscrow("Escrow is not fully funded")

        maker = self.makers[escrow_id]
        taker = self.takers.get(escrow_id)
        if taker is None:
            raise InvalidEscrow("Escrow has not been accepted by a taker")

        maker_fee = self._ceil_fee(self.maker_amounts[escrow_id])
        taker_fee = self._ceil_fee(self.taker_amounts[escrow_id])

 # --- Maker withdraws taker_token net of taker_fee ---
        if caller == maker:
            if self.maker_withdrawn[escrow_id]:
                raise InvalidEscrow("Maker has already withdrawn")

            target_token = self.taker_tokens[escrow_id]
            target_amount = self.taker_amounts[escrow_id] - taker_fee
            if target_amount < 0:
                raise InvalidEscrow("Fee exceeds taker amount")

            self._process_withdraw(ctx, target_token, target_amount)
            self.maker_withdrawn[escrow_id] = True

            if taker_fee > 0:
                self.protocol_fee_balances[target_token] = self.protocol_fee_balances.get(target_token, 0) + taker_fee

            self._maybe_finalize_status(escrow_id)
            return

 # --- Taker withdraws maker_token net of maker_fee ---
        if caller == taker:
            if self.taker_withdrawn[escrow_id]:
                raise InvalidEscrow("Taker has already withdrawn")

            target_token = self.maker_tokens[escrow_id]
            target_amount = self.maker_amounts[escrow_id] - maker_fee
            if target_amount < 0:
                raise InvalidEscrow("Fee exceeds maker amount")

            self._process_withdraw(ctx, target_token, target_amount)
            self.taker_withdrawn[escrow_id] = True

            if maker_fee > 0:
                self.protocol_fee_balances[target_token] = self.protocol_fee_balances.get(target_token, 0) + maker_fee

            self._maybe_finalize_status(escrow_id)
            return

        raise Unauthorized("Caller is neither maker, taker, nor fee recipient")

 #
 # === REFUND (AFTER EXPIRY) ===
 #

    @public(allow_withdrawal=True)
    def refund(self, ctx: Context, escrow_id: int) -> None:
        """
        Refund deposits after expiry (stage-based).

        - Maker can refund their maker deposit if maker_funded and not maker_refunded.
        - Taker can refund their taker deposit if taker_funded and not taker_refunded.
        - Each side withdraws only their own deposited token.
        - No protocol fees are charged on refunds.
        """
        self._assert_exists(escrow_id)

        status = self.statuses[escrow_id]
        if status == STATUS_CANCELLED:
            raise InvalidEscrow("Escrow has been cancelled")
        if status in (STATUS_EXECUTED, STATUS_REFUNDED):
            raise InvalidEscrow("Escrow is already closed")

        if not self._is_expired_for_current_stage(ctx, escrow_id):
            raise InvalidEscrow("Escrow has not expired")

        caller = self._get_caller_id(ctx)

        if caller == self.makers[escrow_id]:
            if not self.maker_funded[escrow_id]:
                raise InvalidEscrow("Maker side is not funded")
            if self.maker_refunded[escrow_id]:
                raise InvalidEscrow("Maker has already been refunded")
            if self.maker_withdrawn[escrow_id]:
                raise InvalidEscrow("Maker has already withdrawn")

            token_uid = self.maker_tokens[escrow_id]
            amount = self.maker_amounts[escrow_id]
            self._process_withdraw(ctx, token_uid, amount)
            self.maker_refunded[escrow_id] = True

        elif caller == self.takers.get(escrow_id):
            if not self.taker_funded[escrow_id]:
                raise InvalidEscrow("Taker side is not funded")
            if self.taker_refunded[escrow_id]:
                raise InvalidEscrow("Taker has already been refunded")
            if self.taker_withdrawn[escrow_id]:
                raise InvalidEscrow("Taker has already withdrawn")

            token_uid = self.taker_tokens[escrow_id]
            amount = self.taker_amounts[escrow_id]
            self._process_withdraw(ctx, token_uid, amount)
            self.taker_refunded[escrow_id] = True

        else:
            raise Unauthorized("Caller is neither maker nor taker for this escrow")

        maker_done = (not self.maker_funded[escrow_id]) or self.maker_refunded[escrow_id]
        taker_done = (not self.taker_funded[escrow_id]) or self.taker_refunded[escrow_id]
        if maker_done and taker_done:
            self._set_status(escrow_id, STATUS_REFUNDED)

 #
 # === VIEWS ===
 #

    @view
    def get_config(self) -> ConfigView:
        return ConfigView(
            owner=str(self.owner),
            fee_recipient=str(self.fee_recipient),
            protocol_fee_bps=self.protocol_fee_bps,
            default_open_expiry_secs=self.default_open_expiry_secs,
            default_maker_funded_expiry_secs=self.default_maker_funded_expiry_secs,
            min_expiry_secs=self.min_expiry_secs,
            max_expiry_secs=self.max_expiry_secs,
        )

    @view
    def get_protocol_fee_balance(self, token_uid: TokenUid) -> int:
        """Return the aggregated protocol fee balance for a given token uid."""
        return self.protocol_fee_balances.get(token_uid, 0)

    @view
    def get_fee_quote(self, maker_amount: int, taker_amount: int) -> FeeQuoteView:
        """Quote protocol fees given hypothetical amounts (base units)."""
        if maker_amount < 0 or taker_amount < 0:
            raise InvalidConfig("Amounts must be non-negative")

        maker_fee = self._ceil_fee(maker_amount)
        taker_fee = self._ceil_fee(taker_amount)

        maker_net_receive = taker_amount - taker_fee
        taker_net_receive = maker_amount - maker_fee

        if maker_net_receive < 0 or taker_net_receive < 0:
            raise InvalidConfig("Fee exceeds amount")

        return FeeQuoteView(
            maker_fee=maker_fee,
            taker_fee=taker_fee,
            maker_net_receive=maker_net_receive,
            taker_net_receive=taker_net_receive,
        )

    @view
    def get_escrow(self, escrow_id: int) -> EscrowDetails:
        """Safe, JSON-friendly view (summary)."""
        if escrow_id < 0:
            return EscrowDetails(
                maker="",
                taker="",
                maker_token="",
                maker_amount=0,
                taker_token="",
                taker_amount=0,
                maker_funded=False,
                taker_funded=False,
                maker_withdrawn=False,
                taker_withdrawn=False,
                is_cancelled=False,
                status=-1,
            )

        maker_addr = self.makers.get(escrow_id)
        if maker_addr is None:
            return EscrowDetails(
                maker="",
                taker="",
                maker_token="",
                maker_amount=0,
                taker_token="",
                taker_amount=0,
                maker_funded=False,
                taker_funded=False,
                maker_withdrawn=False,
                taker_withdrawn=False,
                is_cancelled=False,
                status=-1,
            )

        taker_addr = self.takers.get(escrow_id)
        maker_token = self.maker_tokens[escrow_id]
        taker_token = self.taker_tokens[escrow_id]
        status = self.statuses[escrow_id]

        return EscrowDetails(
            maker=str(maker_addr),
            taker="" if taker_addr is None else str(taker_addr),
            maker_token=maker_token.hex(),
            maker_amount=self.maker_amounts[escrow_id],
            taker_token=taker_token.hex(),
            taker_amount=self.taker_amounts[escrow_id],
            maker_funded=self.maker_funded[escrow_id],
            taker_funded=self.taker_funded[escrow_id],
            maker_withdrawn=self.maker_withdrawn[escrow_id],
            taker_withdrawn=self.taker_withdrawn[escrow_id],
            is_cancelled=(status == STATUS_CANCELLED),
            status=status,
        )

    @view
    def get_escrow_full(self, escrow_id: int, current_timestamp: int) -> EscrowDetailsFull:
        """
        Extended view including stage expiry state.

        NOTE: @view cannot access Context, so caller must pass current_timestamp.
        """
        if escrow_id < 0:
            return EscrowDetailsFull(
                maker="",
                taker="",
                maker_token="",
                maker_amount=0,
                taker_token="",
                taker_amount=0,
                maker_funded=False,
                taker_funded=False,
                maker_withdrawn=False,
                taker_withdrawn=False,
                maker_refunded=False,
                taker_refunded=False,
                open_expiry_timestamp=0,
                maker_funded_expiry_timestamp=0,
                is_open_expired=False,
                is_maker_funded_expired=False,
                is_expired=False,
                is_directed=False,
                directed_taker="",
                is_cancelled=False,
                is_refunded=False,
                status=-1,
            )

        maker_addr = self.makers.get(escrow_id)
        if maker_addr is None:
            return EscrowDetailsFull(
                maker="",
                taker="",
                maker_token="",
                maker_amount=0,
                taker_token="",
                taker_amount=0,
                maker_funded=False,
                taker_funded=False,
                maker_withdrawn=False,
                taker_withdrawn=False,
                maker_refunded=False,
                taker_refunded=False,
                open_expiry_timestamp=0,
                maker_funded_expiry_timestamp=0,
                is_open_expired=False,
                is_maker_funded_expired=False,
                is_expired=False,
                is_directed=False,
                directed_taker="",
                is_cancelled=False,
                is_refunded=False,
                status=-1,
            )

        taker_addr = self.takers.get(escrow_id)
        maker_token = self.maker_tokens[escrow_id]
        taker_token = self.taker_tokens[escrow_id]
        status = self.statuses[escrow_id]

        open_ts = self.open_expiry_timestamps.get(escrow_id, 0)
        mf_ts = self.maker_funded_expiry_timestamps.get(escrow_id, 0)

        is_open_expired = (open_ts > 0) and (current_timestamp >= open_ts)
        is_mf_expired = (mf_ts > 0) and (current_timestamp >= mf_ts)

 # expired "for stage"
        is_expired = False
        if status in (STATUS_OPEN, STATUS_ACCEPTED):
            is_expired = is_open_expired
        elif status == STATUS_FUNDED_MAKER:
            is_expired = is_mf_expired

        directed = self.is_directed.get(escrow_id, False)
        directed_taker_addr = self.directed_takers.get(escrow_id)

        return EscrowDetailsFull(
            maker=str(maker_addr),
            taker="" if taker_addr is None else str(taker_addr),
            maker_token=maker_token.hex(),
            maker_amount=self.maker_amounts[escrow_id],
            taker_token=taker_token.hex(),
            taker_amount=self.taker_amounts[escrow_id],
            maker_funded=self.maker_funded[escrow_id],
            taker_funded=self.taker_funded[escrow_id],
            maker_withdrawn=self.maker_withdrawn[escrow_id],
            taker_withdrawn=self.taker_withdrawn[escrow_id],
            maker_refunded=self.maker_refunded.get(escrow_id, False),
            taker_refunded=self.taker_refunded.get(escrow_id, False),
            open_expiry_timestamp=open_ts,
            maker_funded_expiry_timestamp=mf_ts,
            is_open_expired=is_open_expired,
            is_maker_funded_expired=is_mf_expired,
            is_expired=is_expired,
            is_directed=directed,
            directed_taker="" if directed_taker_addr is None else str(directed_taker_addr),
            is_cancelled=(status == STATUS_CANCELLED),
            is_refunded=(status == STATUS_REFUNDED),
            status=status,
        )


    @view
    def get_escrow_exists(self, escrow_id: int) -> bool:
        """Return True if an escrow exists (has a maker recorded)."""
        if escrow_id < 0:
            return False
        return self.makers.get(escrow_id) is not None

    @view
    def get_escrow_status(self, escrow_id: int) -> int:
        """Return escrow status, or -1 if escrow not found."""
        if escrow_id < 0:
            return -1
        if self.makers.get(escrow_id) is None:
            return -1
        return self.statuses.get(escrow_id, -1)

    @view
    def get_counters(self) -> CountersView:
        """Return lightweight counters suitable for website stats."""
        return CountersView(
            total_escrows=self.total_escrows,
            count_open=self.count_open,
            count_accepted=self.count_accepted,
            count_funded_maker=self.count_funded_maker,
            count_funded_both=self.count_funded_both,
            count_executed=self.count_executed,
            count_refunded=self.count_refunded,
            count_cancelled=self.count_cancelled,
            count_public=self.count_public,
            count_directed=self.count_directed,
        )

    @view
    def get_escrow_ids_page(self, cursor: int, limit: int) -> EscrowIdsPage:
        """
        Return a page of escrow IDs suitable for website pagination.

        - cursor is an index into the escrow_ids array (NOT an escrow_id)
        - next_cursor is 0 when no more data

        NOTE: Avoid list slicing in PythonVM (some environments reject slicing on typed lists).
        """
        if cursor < 0:
            cursor = 0
        if limit <= 0:
            raise InvalidConfig("limit must be > 0")
        if limit > 200:
            raise InvalidConfig("limit too large")

        total = len(self.escrow_ids)
        if cursor >= total:
            return EscrowIdsPage(cursor_in=cursor, limit=limit, next_cursor=0, ids=[])

        end = cursor + limit
        if end > total:
            end = total

        ids: list[int] = []
        i = cursor
        while i < end:
            ids.append(self.escrow_ids[i])
            i += 1

        next_cursor = 0 if end >= total else end
        return EscrowIdsPage(cursor_in=cursor, limit=limit, next_cursor=next_cursor, ids=ids)
