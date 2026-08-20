from enum import Enum


class OrderStatus(str, Enum):
    PENDING_PAYMENT = "pending_payment"
    PENDING_ACCEPT = "pending_accept"
    PREPARING = "preparing"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    CANCELING = "canceling"
    CANCELED = "canceled"


ORDER_STATUS_TRANSITIONS = {
    OrderStatus.PENDING_PAYMENT: [OrderStatus.PENDING_ACCEPT, OrderStatus.CANCELING],
    OrderStatus.PENDING_ACCEPT: [OrderStatus.PREPARING, OrderStatus.CANCELING],
    OrderStatus.PREPARING: [OrderStatus.DELIVERING, OrderStatus.CANCELING],
    OrderStatus.DELIVERING: [OrderStatus.COMPLETED],
    OrderStatus.CANCELING: [OrderStatus.CANCELED],
    OrderStatus.COMPLETED: [],
    OrderStatus.CANCELED: [],
}


def can_transition(current: OrderStatus, next_status: OrderStatus) -> bool:
    return next_status in ORDER_STATUS_TRANSITIONS.get(current, [])
