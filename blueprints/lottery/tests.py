from hathor.reactor import get_global_reactor, initialize_global_reactor

try:
    get_global_reactor()
except Exception:
    initialize_global_reactor(use_asyncio_reactor=True)

from hathor.nanocontracts import HATHOR_TOKEN_UID
from hathor.nanocontracts.types import Address, NCDepositAction, NCWithdrawalAction, TokenUid
from hathor_tests.nanocontracts.blueprints.unittest import BlueprintTestCase

from blueprints.lottery.lottery import (
    CREATION_FEE,
    TIMEOUT_SECONDS,
    Lottery,
    InsufficientFunds,
    InvalidPrice,
    LotteryClosed,
    Unauthorized,
    EMPTY_ADDRESS,
)


class TestLottery(BlueprintTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.blueprint_id = self.gen_random_blueprint_id()
        self.contract_id = self.gen_random_contract_id()
        self._register_blueprint_class(Lottery, self.blueprint_id)

        genesis = self.manager.tx_storage.get_all_genesis()
        self.tx = [t for t in genesis if t.is_transaction][0]
        self.creator = self.gen_random_address()

    def _create_lottery(
        self,
        description: str = "Test Lottery",
        ticket_price: int = 100,
        commission_percent: int = 10,
        creation_fee: int = CREATION_FEE,
        timestamp: int = 100,
    ) -> None:
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        actions = [NCDepositAction(token_uid=token_uid, amount=creation_fee)]
        ctx = self.create_context(
            actions=actions,
            vertex=self.tx,
            caller_id=self.creator,
            timestamp=timestamp,
        )
        self.runner.create_contract(
            self.contract_id,
            self.blueprint_id,
            ctx,
            description,
            ticket_price,
            commission_percent,
        )
        self.created_at = timestamp

    def _buy_ticket(self, buyer: Address, amount: int, timestamp: int) -> None:
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=amount)],
            vertex=self.tx,
            caller_id=buyer,
            timestamp=timestamp,
        )
        self.runner.call_public_method(self.contract_id, "buy_ticket", ctx)

    def test_initialize_requires_creation_fee(self) -> None:
        ctx = self.create_context(
            actions=[],
            vertex=self.tx,
            caller_id=self.creator,
            timestamp=1,
        )
        with self.assertRaises(InsufficientFunds):
            self.runner.create_contract(
                self.contract_id,
                self.blueprint_id,
                ctx,
                "Lottery",
                100,
                10,
            )

    def test_initialize_validates_params(self) -> None:
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        actions = [NCDepositAction(token_uid=token_uid, amount=CREATION_FEE)]

        ctx = self.create_context(actions=actions, vertex=self.tx, caller_id=self.creator, timestamp=1)
        with self.assertRaises(InvalidPrice):
            self.runner.create_contract(
                self.gen_random_contract_id(),
                self.blueprint_id,
                ctx,
                "Lottery",
                0,
                10,
            )

        ctx = self.create_context(actions=actions, vertex=self.tx, caller_id=self.creator, timestamp=2)
        with self.assertRaises(InvalidPrice):
            self.runner.create_contract(
                self.gen_random_contract_id(),
                self.blueprint_id,
                ctx,
                "Lottery",
                1,
                101,
            )

    def test_initialize_sets_state(self) -> None:
        self._create_lottery(description="Weekly", ticket_price=250, commission_percent=15, timestamp=123)

        contract = self.get_readonly_contract(self.contract_id)
        self.assertEqual(contract.description, "Weekly")
        self.assertEqual(contract.price, 250)
        self.assertEqual(contract.commission, 15)
        self.assertEqual(contract.pot, 0)
        self.assertEqual(contract.state, "OPEN")
        self.assertEqual(contract.creator, self.creator)
        self.assertEqual(contract.creation_timestamp, 123)
        self.assertEqual(contract.participants, [])
        self.assertEqual(contract.winner, EMPTY_ADDRESS)
        self.assertEqual(contract.creator_payout, CREATION_FEE)
        self.assertEqual(contract.winner_payout, 0)

    def test_buy_ticket_requires_payment(self) -> None:
        self._create_lottery(ticket_price=200)
        buyer = self.gen_random_address()

        ctx = self.create_context(vertex=self.tx, caller_id=buyer, timestamp=10)
        with self.assertRaises(InsufficientFunds):
            self.runner.call_public_method(self.contract_id, "buy_ticket", ctx)

        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=100)],
            vertex=self.tx,
            caller_id=buyer,
            timestamp=11,
        )
        with self.assertRaises(InsufficientFunds):
            self.runner.call_public_method(self.contract_id, "buy_ticket", ctx)

    def test_buy_ticket_updates_pot_and_participants(self) -> None:
        self._create_lottery(ticket_price=150)
        buyer = self.gen_random_address()
        self._buy_ticket(buyer=buyer, amount=150, timestamp=20)

        contract = self.get_readonly_contract(self.contract_id)
        self.assertEqual(contract.pot, 150)
        self.assertEqual(contract.participants, [buyer])

    def test_draw_winner_requires_authority_before_timeout(self) -> None:
        self._create_lottery()
        other = self.gen_random_address()
        ctx = self.create_context(vertex=self.tx, caller_id=other, timestamp=self.created_at + 1)

        with self.assertRaises(Unauthorized):
            self.runner.call_public_method(self.contract_id, "draw_winner", ctx)

    def test_draw_winner_after_timeout(self) -> None:
        self._create_lottery(ticket_price=300, commission_percent=20, timestamp=1000)
        buyer_one = self.gen_random_address()
        buyer_two = self.gen_random_address()
        self._buy_ticket(buyer=buyer_one, amount=300, timestamp=1010)
        self._buy_ticket(buyer=buyer_two, amount=300, timestamp=1020)

        ctx = self.create_context(
            vertex=self.tx,
            caller_id=self.gen_random_address(),
            timestamp=self.created_at + TIMEOUT_SECONDS + 1,
        )
        self.runner.call_public_method(self.contract_id, "draw_winner", ctx)

        contract = self.get_readonly_contract(self.contract_id)
        self.assertEqual(contract.state, "CLOSED")
        self.assertIn(contract.winner, [buyer_one, buyer_two])

        total_pot = 600
        comm_amount = (total_pot * 20) // 100
        prize_amount = total_pot - comm_amount
        self.assertEqual(contract.creator_payout, CREATION_FEE + comm_amount)
        self.assertEqual(contract.winner_payout, prize_amount)

    def test_claim_reward_flow(self) -> None:
        self._create_lottery(ticket_price=400, commission_percent=25, timestamp=200)
        buyer = self.gen_random_address()
        self._buy_ticket(buyer=buyer, amount=400, timestamp=201)

        draw_ctx = self.create_context(vertex=self.tx, caller_id=self.creator, timestamp=202)
        self.runner.call_public_method(self.contract_id, "draw_winner", draw_ctx)

        contract = self.get_readonly_contract(self.contract_id)
        winner = contract.winner
        winner_amount = contract.winner_payout
        creator_amount = contract.creator_payout

        token_uid = TokenUid(HATHOR_TOKEN_UID)
        winner_ctx = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=winner_amount)],
            vertex=self.tx,
            caller_id=winner,
            timestamp=203,
        )
        self.runner.call_public_method(self.contract_id, "claim_reward", winner_ctx)

        contract = self.get_readonly_contract(self.contract_id)
        self.assertEqual(contract.winner_payout, 0)

        creator_ctx = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=creator_amount)],
            vertex=self.tx,
            caller_id=self.creator,
            timestamp=204,
        )
        self.runner.call_public_method(self.contract_id, "claim_reward", creator_ctx)

        contract = self.get_readonly_contract(self.contract_id)
        self.assertEqual(contract.creator_payout, 0)

    def test_claim_reward_rejects_unauthorized(self) -> None:
        self._create_lottery(ticket_price=100, commission_percent=10, timestamp=300)
        buyer = self.gen_random_address()
        self._buy_ticket(buyer=buyer, amount=100, timestamp=301)

        draw_ctx = self.create_context(vertex=self.tx, caller_id=self.creator, timestamp=302)
        self.runner.call_public_method(self.contract_id, "draw_winner", draw_ctx)

        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=1)],
            vertex=self.tx,
            caller_id=self.gen_random_address(),
            timestamp=303,
        )
        with self.assertRaises(Unauthorized):
            self.runner.call_public_method(self.contract_id, "claim_reward", ctx)

    def test_buy_ticket_after_close_fails(self) -> None:
        self._create_lottery()
        draw_ctx = self.create_context(vertex=self.tx, caller_id=self.creator, timestamp=10)
        self.runner.call_public_method(self.contract_id, "draw_winner", draw_ctx)

        buyer = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=100)],
            vertex=self.tx,
            caller_id=buyer,
            timestamp=11,
        )
        with self.assertRaises(LotteryClosed):
            self.runner.call_public_method(self.contract_id, "buy_ticket", ctx)
