from __future__ import annotations

from ib_insync import Order

from src.common.models import Side


def _opposite(side: Side) -> str:
    return "SELL" if side == Side.BUY else "BUY"


def create_market_order(order_id: int, side: Side, qty: int) -> Order:
    return Order(
        orderId=order_id,
        action=side.value,
        orderType="MKT",
        totalQuantity=qty,
        tif="DAY",
        transmit=True,
    )


def create_bracket_orders(
    parent_order_id: int,
    side: Side,
    qty: int,
    take_profit_price: float,
    stop_loss_price: float,
) -> list[Order]:
    exit_action = _opposite(side)
    parent = Order(
        orderId=parent_order_id,
        action=side.value,
        orderType="MKT",
        totalQuantity=qty,
        tif="DAY",
        transmit=False,
    )
    take_profit = Order(
        orderId=parent_order_id + 1,
        action=exit_action,
        orderType="LMT",
        totalQuantity=qty,
        lmtPrice=round(take_profit_price, 2),
        parentId=parent_order_id,
        tif="GTC",
        transmit=False,
    )
    stop_loss = Order(
        orderId=parent_order_id + 2,
        action=exit_action,
        orderType="STP",
        totalQuantity=qty,
        auxPrice=round(stop_loss_price, 2),
        parentId=parent_order_id,
        tif="GTC",
        transmit=True,
    )
    return [parent, take_profit, stop_loss]
