from typing import Optional

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


class OutOfBounds(NCFail):
    pass


class InvalidColorFormat(NCFail):
    pass


class EmptyBatch(NCFail):
   
    pass


class FeeRequired(NCFail):
    
    pass


MAX_BATCH_SIZE = 32
MAX_PIXELS_PAGE_SIZE = 1000


@export
class Pxiel(Blueprint):
    
    owner: Address
    size: int
    fee_htr: int
    paint_count: int
    fees_collected: int
    pixels: dict[str, str]
    pixel_keys: list[str]
    last_painted_by: dict[str, Address]
    last_painted_at: dict[str, Timestamp]

    @public
    def initialize(self, ctx: Context, size: int, fee_htr: int) -> None:
       
        self.owner = ctx.get_caller_address()
        self.size = size
        self.fee_htr = fee_htr
        self.paint_count = 0
        self.fees_collected = 0
        self.pixels = {}
        self.pixel_keys = []
        self.last_painted_by = {}
        self.last_painted_at = {}

    def _make_key(self, x: int, y: int) -> str:
       
        return f"{x},{y}"

    def _validate_pixel(self, x: int, y: int, color: str) -> None:
     
        if not (0 <= x < self.size and 0 <= y < self.size):
            raise OutOfBounds("Coordinates (x, y) are outside canvas bounds.")
        
        if not (len(color) == 7 and color.startswith('#')):
            raise InvalidColorFormat("Color format must be '#RRGGBB'.")
        
        hex_part = color[1:]
        if any(ch not in "0123456789abcdefABCDEF" for ch in hex_part):
            raise InvalidColorFormat("Use only hexadecimal digits in '#RRGGBB'.")

    def _emit_paint_event(self, x: int, y: int, color: str, fee: int) -> None:
        
        event_data = f'{{"event":"Paint","x":{x},"y":{y},"color":"{color}","fee":{fee}}}'
        self.syscall.emit_event(event_data.encode('utf-8'))

    def _apply_paint(self, caller_address: Address, current_timestamp: Timestamp, x: int, y: int, color: str, fee: int) -> None:
       
        self._validate_pixel(x, y, color)
        key = self._make_key(x, y)
        if key not in self.pixels:
            self.pixel_keys.append(key)
        self.pixels[key] = color
        self.last_painted_by[key] = caller_address
        self.last_painted_at[key] = current_timestamp
        self._emit_paint_event(x, y, color, fee)

    @public(allow_deposit=True)
    def paint(self, ctx: Context, x: int, y: int, color: str) -> None:
   
        action = ctx.get_single_action(HATHOR_TOKEN_UID)
        assert len(ctx.actions) == 1, 'expected only one token'
        if not isinstance(action, NCDepositAction):
            raise FeeRequired("An HTR deposit is required to paint.")

        if action.amount < self.fee_htr:
            raise FeeRequired(f"Minimum fee of {self.fee_htr} HTR cents is required.")

        caller_address = ctx.get_caller_address()
        current_timestamp = ctx.block.timestamp
        self._apply_paint(caller_address, current_timestamp, x, y, color, action.amount)
        self.paint_count += 1
        self.fees_collected += action.amount

    @public(allow_deposit=True)
    def paint_batch(self, ctx: Context, xs: list[int], ys: list[int], colors: list[str]) -> None:
      
        if not (len(xs) == len(ys) == len(colors)):
            raise EmptyBatch("Lists of coordinates and colors must have the same size.")
        
        total = len(xs)
        if total == 0:
            raise EmptyBatch("Empty batch is not allowed.")
        if total > MAX_BATCH_SIZE:
            raise EmptyBatch(f"Maximum batch size is {MAX_BATCH_SIZE} pixels.")

        required_fee = self.fee_htr * total
        action = ctx.get_single_action(HATHOR_TOKEN_UID)
        if not isinstance(action, NCDepositAction):
            raise FeeRequired("An HTR deposit is required to paint.")
        if action.amount < required_fee:
            raise FeeRequired(f"Minimum fee of {required_fee} HTR cents is required.")

        caller_address = ctx.get_caller_address()
        current_timestamp = ctx.block.timestamp

        for i in range(total):
            self._apply_paint(caller_address, current_timestamp, xs[i], ys[i], colors[i], self.fee_htr)

        self.paint_count += total
        self.fees_collected += action.amount

    @public(allow_withdrawal=True)
    def withdraw_fees(self, ctx: Context) -> None:
     
        if ctx.get_caller_address() != self.owner:
            raise NCFail("Only the owner can withdraw fees.")

        action = ctx.get_single_action(HATHOR_TOKEN_UID)
        if not isinstance(action, NCWithdrawalAction):
            raise NCFail("Withdrawal action expected.")

        if action.amount > self.fees_collected:
            raise NCFail("Withdrawal amount exceeds collected fees.")

        self.fees_collected -= action.amount

    @view
    def get_pixel_info(self, x: int, y: int) -> Optional[tuple[str, str, Timestamp]]:
       
        key = self._make_key(x, y)
        if key in self.pixels:
            return (
                self.pixels[key],
                str(self.last_painted_by[key]),
                self.last_painted_at[key],
            )
        return None

    @view
    def get_stats(self) -> tuple[int, int]:
        
        return (self.paint_count, self.fees_collected)

    @view
    def get_owner(self) -> str:
    
        return str(self.owner)

    @view
    def get_canvas_size(self) -> int:
    
        return self.size
      

    @view
    def get_paint_fee(self) -> int:
    
        return self.fee_htr 

    @view
    def get_pixels_count(self) -> int:
    
        return len(self.pixel_keys)

    @view
    def get_pixels_page(self, offset: int, limit: int) -> list[list[str]]:
        
        offset = int(offset)
        limit = int(limit)

        if offset < 0:
          raise NCFail("Invalid offset.")
        if limit <= 0 or limit > MAX_PIXELS_PAGE_SIZE:
          raise NCFail(f"Limit must be between 1 and {MAX_PIXELS_PAGE_SIZE}.")

        total = len(self.pixel_keys)
        if offset >= total:
           return []

        end = offset + limit
        if end > total:
            end = total

        out: list[list[str]] = []
        for i in range(offset, end):
            key = self.pixel_keys[i]         
            out.append([key, self.pixels[key]])

        return out