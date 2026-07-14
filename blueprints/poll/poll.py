from hathor import (
    Address,
    Blueprint,
    Context,
    HATHOR_TOKEN_UID,
    NCDepositAction,
    NCFail,
    NCWithdrawalAction,
    TokenUid,
    Timestamp,
    export,
    json_dumps,
    public,
    view,
)


class PollNotFound(NCFail):
    pass


class PollNotStarted(NCFail):
    pass


class PollClosed(NCFail):
    pass


class InvalidOption(NCFail):
    pass


class AlreadyVoted(NCFail):
    pass


class InvalidConfig(NCFail):
    pass


class FeeRequired(NCFail):
    pass


class WithdrawalNotAvailable(NCFail):
    pass


class Unauthorized(NCFail):
    pass


WEIGHTING_LINEAR = "linear"

MAX_OPTIONS = 8
MAX_TITLE_LEN = 80
MAX_DESC_LEN = 300


@export
class Polls(Blueprint):
    owner: Address
    creation_fee_htr: int
    creation_fee_balance_htr: int
    poll_count: int

    poll_title: dict[str, str]
    poll_description: dict[str, str]
    poll_option_text: dict[str, str]
    poll_option_count: dict[str, int]
    poll_token: dict[str, TokenUid]
    poll_start: dict[str, Timestamp]
    poll_end: dict[str, Timestamp]
    poll_creator: dict[str, Address]
    poll_weighting: dict[str, str]
    poll_weight_cap: dict[str, int]
    poll_result_weight: dict[str, int]
    poll_result_votes: dict[str, int]

    # Runtime-safe vote storage:
    # - per-option aggregates for O(1) result reads
    # - indexed vote lists for withdrawals and per-(poll, voter) lookup
    vote_poll_ids: list[int]
    vote_voters: list[Address]
    vote_options: list[int]
    vote_weights: list[int]
    vote_deposits: list[int]
    vote_locked_until: list[Timestamp]
    vote_withdrawn: list[int]
    vote_index_by_key: dict[str, int]

    @public
    def initialize(self, ctx: Context, creation_fee_htr: int) -> None:
        if creation_fee_htr < 0:
            raise InvalidConfig("Creation fee cannot be negative.")

        self.owner = ctx.get_caller_address()
        self.creation_fee_htr = creation_fee_htr
        self.creation_fee_balance_htr = 0
        self.poll_count = 0

        self.poll_title = {}
        self.poll_description = {}
        self.poll_option_text = {}
        self.poll_option_count = {}
        self.poll_token = {}
        self.poll_start = {}
        self.poll_end = {}
        self.poll_creator = {}
        self.poll_weighting = {}
        self.poll_weight_cap = {}
        self.poll_result_weight = {}
        self.poll_result_votes = {}

        self.vote_poll_ids = []
        self.vote_voters = []
        self.vote_options = []
        self.vote_weights = []
        self.vote_deposits = []
        self.vote_locked_until = []
        self.vote_withdrawn = []
        self.vote_index_by_key = {}

    def _poll_key(self, poll_id: int) -> str:
        return str(poll_id)

    def _option_key(self, poll_id: int, option_index: int) -> str:
        return f"{poll_id}:{option_index}"

    def _vote_key(self, poll_id: int, voter: Address) -> str:
        return f"{poll_id}:{voter.hex()}"

    def _find_vote_index(self, poll_id: int, voter: Address) -> int:
        key = self._vote_key(poll_id, voter)
        if key in self.vote_index_by_key:
            return self.vote_index_by_key[key]
        return -1

    def _calc_weight(self, amount: int) -> int:
        if amount <= 0:
            return 0
        return amount

    def _validate_poll(
        self,
        title: str,
        description: str,
        options: list[str],
        token_uid: TokenUid,
        start_at: int,
        end_at: int,
        weighting: str,
        weight_cap: int,
    ) -> None:
        if not title or len(title) > MAX_TITLE_LEN:
            raise InvalidConfig("Invalid title length.")
        if len(description) > MAX_DESC_LEN:
            raise InvalidConfig("Invalid description length.")
        if not options or len(options) < 2:
            raise InvalidConfig("At least two options are required.")
        if len(options) > MAX_OPTIONS:
            raise InvalidConfig("Too many options.")
        for option in options:
            if not option:
                raise InvalidConfig("Option text cannot be empty.")
        if not token_uid:
            raise InvalidConfig("Token uid is required.")
        if end_at <= start_at:
            raise InvalidConfig("End time must be after start time.")
        if weighting != WEIGHTING_LINEAR:
            raise InvalidConfig("Only linear weighting is supported.")
        if weight_cap != 0:
            raise InvalidConfig("Weight cap is not supported.")

    def _sum_actions(self, ctx: Context, token_uid: TokenUid, action_type):
        actions = ctx.actions.get(token_uid)
        if actions is None:
            return 0

        total = 0
        for action in actions:
            if not isinstance(action, action_type):
                return -1
            total += action.amount
        return total

    @public(allow_deposit=True)
    def create_poll(
        self,
        ctx: Context,
        title: str,
        description: str,
        options: list[str],
        token_uid: TokenUid,
        start_at: Timestamp,
        end_at: Timestamp,
        weighting: str,
        weight_cap: int,
    ) -> int:
        self._validate_poll(title, description, options, token_uid, start_at, end_at, weighting, weight_cap)

        fee_amount = self._sum_actions(ctx, HATHOR_TOKEN_UID, NCDepositAction)
        if fee_amount < 0:
            raise FeeRequired("Creation fee must use HTR deposit actions only.")
        if self.creation_fee_htr == 0:
            if fee_amount != 0:
                raise FeeRequired("No creation fee is expected.")
        elif fee_amount != self.creation_fee_htr:
            raise FeeRequired(f"Exact creation fee of {self.creation_fee_htr} is required.")

        poll_id = self.poll_count
        key = self._poll_key(poll_id)

        self.poll_title[key] = title
        self.poll_description[key] = description
        self.poll_option_count[key] = len(options)
        self.poll_token[key] = token_uid
        self.poll_start[key] = start_at
        self.poll_end[key] = end_at
        self.poll_creator[key] = ctx.get_caller_address()
        self.poll_weighting[key] = WEIGHTING_LINEAR
        self.poll_weight_cap[key] = 0
        self.creation_fee_balance_htr += fee_amount

        for i, option in enumerate(options):
            opt_key = self._option_key(poll_id, i)
            self.poll_option_text[opt_key] = option
            self.poll_result_weight[opt_key] = 0
            self.poll_result_votes[opt_key] = 0

        self.poll_count += 1

        event_data = json_dumps(
            {
                "event": "PollCreated",
                "id": poll_id,
                "token": token_uid.hex(),
                "start": start_at,
                "end": end_at,
                "weighting": weighting,
            }
        )
        self.syscall.emit_event(event_data.encode("utf-8"))

        return poll_id

    @public(allow_deposit=True)
    def cast_vote(self, ctx: Context, poll_id: int, option_index: int) -> None:
        key = self._poll_key(poll_id)
        if key not in self.poll_title:
            raise PollNotFound("Poll not found.")

        now = ctx.block.timestamp
        start_at = self.poll_start[key]
        end_at = self.poll_end[key]
        if now < start_at:
            raise PollNotStarted("Poll has not started.")
        if now > end_at:
            raise PollClosed("Poll is closed.")

        option_count = self.poll_option_count.get(key, 0)
        if option_index < 0 or option_index >= option_count:
            raise InvalidOption("Invalid option index.")

        caller = ctx.get_caller_address()
        vote_key = self._vote_key(poll_id, caller)
        if vote_key in self.vote_index_by_key:
            raise AlreadyVoted("Address already voted.")

        token_uid = self.poll_token[key]
        amount = self._sum_actions(ctx, token_uid, NCDepositAction)
        if amount <= 0:
            raise FeeRequired("Token deposit required to vote.")

        weight = self._calc_weight(amount)
        if weight <= 0:
            raise FeeRequired("Invalid voting weight.")

        vote_index = len(self.vote_poll_ids)
        self.vote_poll_ids.append(poll_id)
        self.vote_voters.append(caller)
        self.vote_options.append(option_index)
        self.vote_weights.append(weight)
        self.vote_deposits.append(amount)
        self.vote_locked_until.append(end_at)
        self.vote_withdrawn.append(0)
        self.vote_index_by_key[vote_key] = vote_index
        option_key = self._option_key(poll_id, option_index)
        self.poll_result_weight[option_key] = self.poll_result_weight.get(option_key, 0) + weight
        self.poll_result_votes[option_key] = self.poll_result_votes.get(option_key, 0) + 1

        event_data = json_dumps(
            {
                "event": "VoteCast",
                "id": poll_id,
                "option": option_index,
                "weight": weight,
                "amount": amount,
            }
        )
        self.syscall.emit_event(event_data.encode("utf-8"))

    @public(allow_withdrawal=True)
    def withdraw_vote(self, ctx: Context, poll_id: int) -> None:
        key = self._poll_key(poll_id)
        if key not in self.poll_title:
            raise PollNotFound("Poll not found.")

        now = ctx.block.timestamp
        if now <= self.poll_end[key]:
            raise WithdrawalNotAvailable("Poll is still active.")

        caller = ctx.get_caller_address()
        vote_index = self._find_vote_index(poll_id, caller)
        if vote_index < 0:
            raise WithdrawalNotAvailable("No deposit to withdraw.")

        locked_until = self.vote_locked_until[vote_index]
        if now <= locked_until:
            raise WithdrawalNotAvailable("Vote weight is locked until the poll ends.")

        token_uid = self.poll_token[key]
        amount = self._sum_actions(ctx, token_uid, NCWithdrawalAction)
        if amount <= 0:
            raise WithdrawalNotAvailable("Withdrawal action required.")

        available = self.vote_deposits[vote_index] - self.vote_withdrawn[vote_index]
        if amount <= 0 or amount > available:
            raise WithdrawalNotAvailable("Invalid withdrawal amount.")

        self.vote_withdrawn[vote_index] = self.vote_withdrawn[vote_index] + amount

        event_data = json_dumps(
            {
                "event": "VoteWithdrawn",
                "id": poll_id,
                "amount": amount,
            }
        )
        self.syscall.emit_event(event_data.encode("utf-8"))

    @public(allow_withdrawal=True)
    def withdraw_creation_fees(self, ctx: Context) -> None:
        if ctx.get_caller_address() != self.owner:
            raise Unauthorized("Only the contract owner can withdraw creation fees.")

        amount = self._sum_actions(ctx, HATHOR_TOKEN_UID, NCWithdrawalAction)
        if amount <= 0:
            raise WithdrawalNotAvailable("Withdrawal action required.")
        if amount > self.creation_fee_balance_htr:
            raise WithdrawalNotAvailable("Withdrawal amount exceeds collected creation fees.")

        self.creation_fee_balance_htr -= amount

        event_data = json_dumps(
            {
                "event": "CreationFeeWithdrawn",
                "amount": amount,
            }
        )
        self.syscall.emit_event(event_data.encode("utf-8"))

    @view
    def get_poll_count(self) -> int:
        return self.poll_count

    @view
    def get_owner(self) -> str:
        return self.owner.hex()

    @view
    def get_creation_fee_balance(self) -> int:
        return self.creation_fee_balance_htr

    @view
    def get_poll(self, poll_id: int) -> dict[str, str]:
        key = self._poll_key(poll_id)
        if key not in self.poll_title:
            raise PollNotFound("Poll not found.")

        return {
            "id": str(poll_id),
            "title": self.poll_title[key],
            "description": self.poll_description[key],
            "option_count": str(self.poll_option_count.get(key, 0)),
            "token_uid": self.poll_token[key].hex(),
            "start_at": str(self.poll_start[key]),
            "end_at": str(self.poll_end[key]),
            "creator": self.poll_creator[key].hex(),
            "weighting": self.poll_weighting[key],
            "weight_cap": str(self.poll_weight_cap[key]),
        }

    @view
    def get_poll_option(self, poll_id: int, option_index: int) -> str:
        key = self._poll_key(poll_id)
        if key not in self.poll_title:
            raise PollNotFound("Poll not found.")
        count = self.poll_option_count.get(key, 0)
        if option_index < 0 or option_index >= count:
            raise InvalidOption("Invalid option index.")
        opt_key = self._option_key(poll_id, option_index)
        return self.poll_option_text.get(opt_key, "")

    @view
    def get_poll_results(self, poll_id: int) -> list[list[int]]:
        key = self._poll_key(poll_id)
        if key not in self.poll_title:
            raise PollNotFound("Poll not found.")

        count = self.poll_option_count.get(key, 0)
        results: list[list[int]] = []
        for i in range(count):
            option_key = self._option_key(poll_id, i)
            results.append([
                i,
                self.poll_result_weight.get(option_key, 0),
                self.poll_result_votes.get(option_key, 0),
            ])
        return results

    @view
    def get_vote(self, poll_id: int, voter_hex: str) -> dict[str, str]:
        key = self._poll_key(poll_id)
        if key not in self.poll_title:
            raise PollNotFound("Poll not found.")

        vote_key = f"{poll_id}:{voter_hex}"
        if vote_key not in self.vote_index_by_key:
            return {"voted": "false"}

        vote_index = self.vote_index_by_key[vote_key]
        return {
            "voted": "true",
            "option": str(self.vote_options[vote_index]),
            "weight": str(self.vote_weights[vote_index]),
            "deposit": str(self.vote_deposits[vote_index] - self.vote_withdrawn[vote_index]),
            "locked_until": str(self.vote_locked_until[vote_index]),
        }
