from hathor import (
    Address,
    Blueprint,
    Context,
    HATHOR_TOKEN_UID,
    NCDepositAction,
    NCFail,
    NCWithdrawalAction,
    Timestamp,
    export,
    public,
    view,
)

CREATION_FEE = 1000  # 10 HTR in cents
TIMEOUT_SECONDS = 60 * 60 * 24 * 30  # 30 days
EMPTY_ADDRESS = Address(b"\x00" * 25)


class InvalidPrice(NCFail):
    pass


class LotteryClosed(NCFail):
    pass


class InsufficientFunds(NCFail):
    pass


class Unauthorized(NCFail):
    pass


@export
class Lottery(Blueprint):
    # Single lottery state - top-level fields for API compatibility
    description: str
    price: int
    commission: int
    pot: int
    state: str
    creator: Address
    creation_timestamp: Timestamp
    participants: list[Address]
    winner: Address

    # Payout tracking
    creator_payout: int
    winner_payout: int

    def _get_single_action(self, ctx: Context):
        actions = ctx.actions.get(HATHOR_TOKEN_UID)
        if actions is None or len(actions) != 1:
            return None
        return actions[0]

    @public(allow_deposit=True)
    def initialize(self, ctx: Context, description: str, ticket_price: int, commission_percent: int) -> None:
        if ticket_price <= 0:
            raise InvalidPrice("Ticket price must be positive.")
        if not (0 <= commission_percent <= 100):
            raise InvalidPrice("Commission must be between 0 and 100.")

        # Require 10 HTR creation fee
        action = self._get_single_action(ctx)
        if not isinstance(action, NCDepositAction):
            raise InsufficientFunds("10 HTR creation fee required.")
        if action.amount < CREATION_FEE:
            raise InsufficientFunds(f"Creation fee too low. Required: {CREATION_FEE}")

        self.description = description
        self.price = ticket_price
        self.commission = commission_percent
        self.pot = 0
        self.state = "OPEN"
        self.creator = ctx.get_caller_address()
        self.creation_timestamp = ctx.block.timestamp
        self.participants = []
        self.winner = EMPTY_ADDRESS
        self.creator_payout = action.amount  # Fee stays in contract, claimable by creator
        self.winner_payout = 0

        event_data = (
            f'{{"event": "LotteryCreated", "creator": "{self.creator.hex()}", "fee": {action.amount}}}'
        )
        self.syscall.emit_event(event_data.encode("utf-8"))

    @public(allow_deposit=True)
    def buy_ticket(self, ctx: Context) -> None:
        if self.state != "OPEN":
            raise LotteryClosed("Lottery is closed.")

        action = self._get_single_action(ctx)
        if not isinstance(action, NCDepositAction):
            raise InsufficientFunds("Payment required.")

        if action.amount < self.price:
            raise InsufficientFunds(f"Amount too low. Required: {self.price}")

        buyer = ctx.get_caller_address()
        self.participants.append(buyer)
        self.pot += action.amount

        event_data = (
            f'{{"event": "TicketBought", "buyer": "{buyer.hex()}", "count": {len(self.participants)}}}'
        )
        self.syscall.emit_event(event_data.encode("utf-8"))

    @public
    def draw_winner(self, ctx: Context) -> None:
        is_owner = ctx.get_caller_address() == self.creator
        is_expired = (ctx.block.timestamp - self.creation_timestamp) > TIMEOUT_SECONDS

        if not is_owner and not is_expired:
            raise Unauthorized("Only creator can draw before timeout.")

        if self.state != "OPEN":
            raise LotteryClosed("Not open.")

        participant_count = len(self.participants)
        if participant_count == 0:
            self.state = "CLOSED"
            return

        # Pseudo-random winner selection from contract RNG (deterministic across nodes)
        # Uses rejection sampling internally, avoiding modulo bias.
        winner_index = self.syscall.rng.randbelow(participant_count)
        self.winner = self.participants[winner_index]
        self.state = "CLOSED"

        total_pot = self.pot
        comm_amount = (total_pot * self.commission) // 100
        prize_amount = total_pot - comm_amount

        self.creator_payout += comm_amount
        self.winner_payout = prize_amount

        event_data = (
            f'{{"event": "WinnerDrawn", "winner": "{self.winner.hex()}", "prize": {prize_amount}}}'
        )
        self.syscall.emit_event(event_data.encode("utf-8"))

    @public(allow_withdrawal=True)
    def claim_reward(self, ctx: Context) -> None:
        if self.state != "CLOSED":
            raise LotteryClosed("Lottery not closed.")

        caller = ctx.get_caller_address()
        action = self._get_single_action(ctx)
        if not isinstance(action, NCWithdrawalAction):
            raise Unauthorized("Withdrawal needed.")

        # Calculate total available for this specific caller
        available = 0
        if caller == self.winner:
            available += self.winner_payout
        if caller == self.creator:
            available += self.creator_payout

        if available == 0:
            raise Unauthorized("No rewards available for this address.")

        if action.amount > available:
            raise Unauthorized(f"Amount exceeds available rewards: {available}")

        # Deduct from balances (prioritize winner payout)
        remaining = action.amount

        if caller == self.winner:
            to_deduct = min(remaining, self.winner_payout)
            self.winner_payout -= to_deduct
            remaining -= to_deduct

        if remaining > 0 and caller == self.creator:
            to_deduct = min(remaining, self.creator_payout)
            self.creator_payout -= to_deduct
            remaining -= to_deduct

        event_data = (
            f'{{"event": "RewardClaimed", "claimer": "{caller.hex()}", "amount": {action.amount}}}'
        )
        self.syscall.emit_event(event_data.encode("utf-8"))

    @view
    def get_state(self) -> dict[str, str]:
        return {
            "description": self.description,
            "price": str(self.price),
            "commission": str(self.commission),
            "pot": str(self.pot),
            "state": self.state,
            "creator": self.creator.hex(),
            "participant_count": str(len(self.participants)),
            "winner": self.winner.hex() if self.state == "CLOSED" else "",
        }
