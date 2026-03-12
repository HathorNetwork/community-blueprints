"""
Blueprint tests for Polls contract.
"""

from hathor.reactor import get_global_reactor, initialize_global_reactor

try:
    get_global_reactor()
except Exception:
    initialize_global_reactor(use_asyncio_reactor=True)

from hathor.nanocontracts import HATHOR_TOKEN_UID
from hathor.nanocontracts.types import NCDepositAction, NCWithdrawalAction, TokenUid
from hathor_tests.nanocontracts.blueprints.unittest import BlueprintTestCase

from blueprints.poll.poll import (
    AlreadyVoted,
    FeeRequired,
    InvalidConfig,
    PollClosed,
    PollNotStarted,
    Polls,
    Unauthorized,
    WithdrawalNotAvailable,
    WEIGHTING_LINEAR,
)


class TestPolls(BlueprintTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.polls_id = self._register_blueprint_class(Polls)
        genesis = self.manager.tx_storage.get_all_genesis()
        self.tx = [t for t in genesis if t.is_transaction][0]

    def _create_contract(self, creation_fee_htr: int = 0):
        caller = self.gen_random_address()
        ctx = self.create_context(caller_id=caller)
        self.runner.create_contract(self.polls_id, self.polls_id, ctx, creation_fee_htr)
        return caller

    def _create_poll(self, weighting: str, cap: int = 0) -> int:
        creator = self.gen_random_address()
        ctx = self.create_context(vertex=self.tx, caller_id=creator, timestamp=100)
        return self.runner.call_public_method(
            self.polls_id,
            "create_poll",
            ctx,
            "Test Poll",
            "Desc",
            ["Yes", "No"],
            HATHOR_TOKEN_UID,
            90,
            200,
            weighting,
            cap,
        )

    def test_create_poll_increments_count(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        count = self.runner.call_view_method(self.polls_id, "get_poll_count")
        self.assertEqual(count, 1)

    def test_get_poll_returns_stringified_dict(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        poll = self.runner.call_view_method(self.polls_id, "get_poll", 0)

        self.assertEqual(
            poll,
            {
                "id": "0",
                "title": "Test Poll",
                "description": "Desc",
                "option_count": "2",
                "token_uid": HATHOR_TOKEN_UID.hex(),
                "start_at": "90",
                "end_at": "200",
                "creator": poll["creator"],
                "weighting": WEIGHTING_LINEAR,
                "weight_cap": "0",
            },
        )

    def test_vote_linear_weight(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        voter = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=120)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=120,
        )
        self.runner.call_public_method(self.polls_id, "cast_vote", ctx, 0, 1)

        results = self.runner.call_view_method(self.polls_id, "get_poll_results", 0)
        row = [result for result in results if result[0] == 1][0]
        self.assertEqual(row[1], 120)
        self.assertEqual(row[2], 1)

    def test_get_vote_returns_stringified_dict(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        voter = self.gen_random_address()
        empty_vote = self.runner.call_view_method(self.polls_id, "get_vote", 0, voter.hex())
        self.assertEqual(empty_vote, {"voted": "false"})

        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=120)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=120,
        )
        self.runner.call_public_method(self.polls_id, "cast_vote", ctx, 0, 1)

        vote = self.runner.call_view_method(self.polls_id, "get_vote", 0, voter.hex())
        self.assertEqual(
            vote,
            {
                "voted": "true",
                "option": "1",
                "weight": "120",
                "deposit": "120",
                "locked_until": "200",
            },
        )

    def test_vote_accepts_split_deposit_actions(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        voter = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[
                NCDepositAction(token_uid=token_uid, amount=40),
                NCDepositAction(token_uid=token_uid, amount=60),
            ],
            vertex=self.tx,
            caller_id=voter,
            timestamp=120,
        )
        self.runner.call_public_method(self.polls_id, "cast_vote", ctx, 0, 0)

        results = self.runner.call_view_method(self.polls_id, "get_poll_results", 0)
        self.assertEqual(results, [[0, 100, 1], [1, 0, 0]])

    def test_create_poll_rejects_non_linear_weighting(self) -> None:
        self._create_contract()
        with self.assertRaises(InvalidConfig):
            self._create_poll("quadratic")

    def test_create_poll_rejects_weight_cap(self) -> None:
        self._create_contract()
        with self.assertRaises(InvalidConfig):
            self._create_poll(WEIGHTING_LINEAR, cap=10)

    def test_create_poll_accepts_split_creation_fee_actions(self) -> None:
        self._create_contract(creation_fee_htr=10)
        creator = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[
                NCDepositAction(token_uid=token_uid, amount=4),
                NCDepositAction(token_uid=token_uid, amount=6),
            ],
            vertex=self.tx,
            caller_id=creator,
            timestamp=100,
        )

        self.runner.call_public_method(
            self.polls_id,
            "create_poll",
            ctx,
            "Test Poll",
            "Desc",
            ["Yes", "No"],
            HATHOR_TOKEN_UID,
            90,
            200,
            WEIGHTING_LINEAR,
            0,
        )

        balance = self.runner.call_view_method(self.polls_id, "get_creation_fee_balance")
        self.assertEqual(balance, 10)

    def test_create_poll_rejects_creation_fee_overpayment(self) -> None:
        self._create_contract(creation_fee_htr=10)
        creator = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=11)],
            vertex=self.tx,
            caller_id=creator,
            timestamp=100,
        )

        with self.assertRaises(FeeRequired):
            self.runner.call_public_method(
                self.polls_id,
                "create_poll",
                ctx,
                "Test Poll",
                "Desc",
                ["Yes", "No"],
                HATHOR_TOKEN_UID,
                90,
                200,
                WEIGHTING_LINEAR,
                0,
            )

    def test_results_are_scoped_per_poll(self) -> None:
        self._create_contract()
        first_poll_id = self._create_poll(WEIGHTING_LINEAR)
        second_poll_id = self._create_poll(WEIGHTING_LINEAR)

        token_uid = TokenUid(HATHOR_TOKEN_UID)

        first_voter = self.gen_random_address()
        first_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=25)],
            vertex=self.tx,
            caller_id=first_voter,
            timestamp=120,
        )
        self.runner.call_public_method(self.polls_id, "cast_vote", first_ctx, first_poll_id, 0)

        second_voter = self.gen_random_address()
        second_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=90)],
            vertex=self.tx,
            caller_id=second_voter,
            timestamp=120,
        )
        self.runner.call_public_method(self.polls_id, "cast_vote", second_ctx, second_poll_id, 1)

        first_results = self.runner.call_view_method(self.polls_id, "get_poll_results", first_poll_id)
        second_results = self.runner.call_view_method(self.polls_id, "get_poll_results", second_poll_id)

        self.assertEqual(first_results, [[0, 25, 1], [1, 0, 0]])
        self.assertEqual(second_results, [[0, 0, 0], [1, 90, 1]])

    def test_double_vote_rejected(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        voter = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=10)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=120,
        )
        self.runner.call_public_method(self.polls_id, "cast_vote", ctx, 0, 0)

        with self.assertRaises(AlreadyVoted):
            self.runner.call_public_method(self.polls_id, "cast_vote", ctx, 0, 1)

    def test_vote_outside_window(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        voter = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)

        early_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=10)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=50,
        )
        with self.assertRaises(PollNotStarted):
            self.runner.call_public_method(self.polls_id, "cast_vote", early_ctx, 0, 0)

        late_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=10)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=201,
        )
        with self.assertRaises(PollClosed):
            self.runner.call_public_method(self.polls_id, "cast_vote", late_ctx, 0, 0)

    def test_withdraw_after_end(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        voter = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        vote_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=40)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=120,
        )
        self.runner.call_public_method(self.polls_id, "cast_vote", vote_ctx, 0, 1)

        withdraw_ctx = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=20)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=201,
        )
        self.runner.call_public_method(self.polls_id, "withdraw_vote", withdraw_ctx, 0)

        vote_info = self.runner.call_view_method(self.polls_id, "get_vote", 0, voter.hex())
        self.assertEqual(vote_info["deposit"], "20")
        self.assertEqual(vote_info["locked_until"], "200")

    def test_withdraw_accepts_split_actions(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        voter = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        vote_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=40)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=120,
        )
        self.runner.call_public_method(self.polls_id, "cast_vote", vote_ctx, 0, 1)

        withdraw_ctx = self.create_context(
            actions=[
                NCWithdrawalAction(token_uid=token_uid, amount=5),
                NCWithdrawalAction(token_uid=token_uid, amount=10),
            ],
            vertex=self.tx,
            caller_id=voter,
            timestamp=201,
        )
        self.runner.call_public_method(self.polls_id, "withdraw_vote", withdraw_ctx, 0)

        vote_info = self.runner.call_view_method(self.polls_id, "get_vote", 0, voter.hex())
        self.assertEqual(vote_info["deposit"], "25")

    def test_withdraw_before_end_rejected(self) -> None:
        self._create_contract()
        self._create_poll(WEIGHTING_LINEAR)

        voter = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        vote_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=40)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=120,
        )
        self.runner.call_public_method(self.polls_id, "cast_vote", vote_ctx, 0, 1)

        early_withdraw_ctx = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=10)],
            vertex=self.tx,
            caller_id=voter,
            timestamp=150,
        )
        with self.assertRaises(WithdrawalNotAvailable):
            self.runner.call_public_method(self.polls_id, "withdraw_vote", early_withdraw_ctx, 0)

    def test_owner_can_withdraw_creation_fees(self) -> None:
        owner = self._create_contract(creation_fee_htr=10)
        creator = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        create_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=10)],
            vertex=self.tx,
            caller_id=creator,
            timestamp=100,
        )
        self.runner.call_public_method(
            self.polls_id,
            "create_poll",
            create_ctx,
            "Test Poll",
            "Desc",
            ["Yes", "No"],
            HATHOR_TOKEN_UID,
            90,
            200,
            WEIGHTING_LINEAR,
            0,
        )

        withdraw_ctx = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=6)],
            vertex=self.tx,
            caller_id=owner,
            timestamp=150,
        )
        self.runner.call_public_method(self.polls_id, "withdraw_creation_fees", withdraw_ctx)

        balance = self.runner.call_view_method(self.polls_id, "get_creation_fee_balance")
        self.assertEqual(balance, 4)

    def test_non_owner_cannot_withdraw_creation_fees(self) -> None:
        self._create_contract(creation_fee_htr=10)
        creator = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        create_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=10)],
            vertex=self.tx,
            caller_id=creator,
            timestamp=100,
        )
        self.runner.call_public_method(
            self.polls_id,
            "create_poll",
            create_ctx,
            "Test Poll",
            "Desc",
            ["Yes", "No"],
            HATHOR_TOKEN_UID,
            90,
            200,
            WEIGHTING_LINEAR,
            0,
        )

        attacker = self.gen_random_address()
        withdraw_ctx = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=1)],
            vertex=self.tx,
            caller_id=attacker,
            timestamp=150,
        )
        with self.assertRaises(Unauthorized):
            self.runner.call_public_method(self.polls_id, "withdraw_creation_fees", withdraw_ctx)
