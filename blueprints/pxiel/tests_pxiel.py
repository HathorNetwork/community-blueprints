
from hathor.reactor.reactor import initialize_global_reactor
initialize_global_reactor()
from hathor.nanocontracts import HATHOR_TOKEN_UID
from hathor.nanocontracts.exception import NCFail
from hathor.nanocontracts.types import Address, NCDepositAction, NCWithdrawalAction, TokenUid
from hathor_tests.nanocontracts.blueprints.unittest import BlueprintTestCase

from pxiel import (
    EmptyBatch,
    FeeRequired,
    InvalidColorFormat,
    OutOfBounds,
    Pxiel,
)




class TestPxiel(BlueprintTestCase):
 
    def setUp(self) -> None:
        super().setUp()
        self.pxiel_id = self._register_blueprint_class(Pxiel)
        genesis = self.manager.tx_storage.get_all_genesis()
        self.tx = [t for t in genesis if t.is_transaction][0]

    def _create_pxiel_contract(self, size: int = 10, fee_htr: int = 5) -> None:
        """Helper to create and initialize a Pxiel contract."""
        caller = self.gen_random_address()
        ctx = self.create_context(caller_id=caller)
        self.runner.create_contract(self.pxiel_id, self.pxiel_id, ctx, size, fee_htr)
        self._owner = caller

    def test_initialize_sets_state(self) -> None:
        """Test that initialize correctly sets up the contract state."""
        self._create_pxiel_contract(size=10, fee_htr=5)

        contract = self.get_readonly_contract(self.pxiel_id)
        self.assertEqual(contract.size, 10)
        self.assertEqual(contract.fee_htr, 5)
        self.assertEqual(contract.paint_count, 0)
        self.assertEqual(contract.fees_collected, 0)

    def test_paint_success(self) -> None:
        """Test painting a pixel with proper deposit."""
        self._create_pxiel_contract(size=8, fee_htr=3)

        caller = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=3)],
            vertex=self.tx,
            caller_id=caller,
            timestamp=99,
        )
        self.runner.call_public_method(self.pxiel_id, 'paint', ctx, 2, 3, '#abcdef')

        contract = self.get_readonly_contract(self.pxiel_id)
        self.assertEqual(contract.pixels['2,3'], '#abcdef')
        self.assertEqual(contract.paint_count, 1)
        self.assertEqual(contract.fees_collected, 3)

    def test_paint_out_of_bounds(self) -> None:
        """Test that painting outside canvas bounds raises OutOfBounds."""
        self._create_pxiel_contract(size=4, fee_htr=2)

        caller = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=2)],
            vertex=self.tx,
            caller_id=caller,
        )

        with self.assertRaises(OutOfBounds):
            self.runner.call_public_method(self.pxiel_id, 'paint', ctx, 9, 0, '#ffffff')

    def test_paint_invalid_color(self) -> None:
        """Test that invalid color format raises InvalidColorFormat."""
        self._create_pxiel_contract(size=4, fee_htr=2)

        caller = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=2)],
            vertex=self.tx,
            caller_id=caller,
        )

        with self.assertRaises(InvalidColorFormat):
            self.runner.call_public_method(self.pxiel_id, 'paint', ctx, 1, 1, 'red')

    def test_paint_requires_fee(self) -> None:
        """Test that painting without deposit raises FeeRequired."""
        self._create_pxiel_contract(size=4, fee_htr=2)

        caller = self.gen_random_address()
        ctx = self.create_context(
            vertex=self.tx,
            caller_id=caller,
        )

        with self.assertRaises(NCFail):
            self.runner.call_public_method(self.pxiel_id, 'paint', ctx, 1, 1, '#ffffff')

    def test_paint_batch_success(self) -> None:
        """Test painting multiple pixels in a batch."""
        self._create_pxiel_contract(size=10, fee_htr=2)

        caller = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=6)],
            vertex=self.tx,
            caller_id=caller,
            timestamp=55,
        )
        self.runner.call_public_method(
            self.pxiel_id, 'paint_batch', ctx,
            [0, 1, 2], [0, 1, 2], ['#000000', '#111111', '#222222']
        )

        contract = self.get_readonly_contract(self.pxiel_id)
        self.assertEqual(contract.paint_count, 3)
        self.assertEqual(contract.fees_collected, 6)
        self.assertEqual(contract.pixels['0,0'], '#000000')
        self.assertEqual(contract.pixels['1,1'], '#111111')
        self.assertEqual(contract.pixels['2,2'], '#222222')

    def test_paint_batch_empty_raises(self) -> None:
        """Test that empty batch raises EmptyBatch."""
        self._create_pxiel_contract(size=10, fee_htr=1)

        caller = self.gen_random_address()
        ctx = self.create_context(
            vertex=self.tx,
            caller_id=caller,
        )

        with self.assertRaises(EmptyBatch):
            self.runner.call_public_method(
                self.pxiel_id, 'paint_batch', ctx,
                [], [], []
            )

    def test_withdraw_fees_success(self) -> None:
        """Test that owner can withdraw collected fees."""
        self._create_pxiel_contract(size=5, fee_htr=10)

        # First, paint to collect some fees
        painter = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        paint_ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=10)],
            vertex=self.tx,
            caller_id=painter,
        )
        self.runner.call_public_method(self.pxiel_id, 'paint', paint_ctx, 1, 1, '#ff0000')

        # Now owner withdraws
        withdraw_ctx = self.create_context(
            actions=[NCWithdrawalAction(token_uid=token_uid, amount=10)],
            vertex=self.tx,
            caller_id=self._owner,
        )
        self.runner.call_public_method(self.pxiel_id, 'withdraw_fees', withdraw_ctx)

        contract = self.get_readonly_contract(self.pxiel_id)
        self.assertEqual(contract.fees_collected, 0)

    def test_get_pixels_page(self) -> None:
        """Test retrieving a page of pixels."""
        self._create_pxiel_contract(size=10, fee_htr=1)

        painter = self.gen_random_address()
        token_uid = TokenUid(HATHOR_TOKEN_UID)
        ctx = self.create_context(
            actions=[NCDepositAction(token_uid=token_uid, amount=3)],
            vertex=self.tx,
            caller_id=painter,
        )
        self.runner.call_public_method(
            self.pxiel_id, 'paint_batch', ctx,
            [0, 1, 2], [0, 1, 2], ['#000000', '#111111', '#222222']
        )

        # Call view method
        count = self.runner.call_view_method(self.pxiel_id, 'get_pixels_count')
        self.assertEqual(count, 3)

        page = self.runner.call_view_method(self.pxiel_id, 'get_pixels_page', 0, 2)
        self.assertEqual(len(page), 2)
        self.assertEqual(page[0], ['0,0', '#000000'])
        self.assertEqual(page[1], ['1,1', '#111111'])
