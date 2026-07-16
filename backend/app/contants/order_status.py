from enum import Enum


class OrderStatus(str, Enum):
    """订单状态枚举"""
    PENDING_PAYMENT = "pending_payment"         # 初始状态
    PENDING_ACCEPT = "pending_accept"         # 商家接单
    PREPARING = "preparing"          # 商家正在备餐
    DELIVERING = "delivering"            # 骑手配送中
    COMPLETED = "completed"             # 订单完成
    CANCELING = "canceling"             # 取消中（待商家确认）
    CANCELED = "canceled"              # 订单已取消


# 状态机定义：当前状态 -> 允许的下一状态
ORDER_STATUS_TRANSITIONS = {
    # 正常流程
    OrderStatus.PENDING_PAYMENT: [OrderStatus.PENDING_ACCEPT, OrderStatus.CANCELING],
    OrderStatus.PENDING_ACCEPT: [OrderStatus.PREPARING, OrderStatus.CANCELING],
    OrderStatus.PREPARING: [OrderStatus.DELIVERING, OrderStatus.CANCELING],
    OrderStatus.DELIVERING: [OrderStatus.COMPLETED],
    # 取消流程
    OrderStatus.CANCELING: [OrderStatus.CANCELED],
    # 最终状态
    OrderStatus.COMPLETED: [],
    OrderStatus.CANCELED: [],
}


def can_transition(current: OrderStatus, next_status: OrderStatus) -> bool:
    """检查状态转换是否合法"""
    allowed = ORDER_STATUS_TRANSITIONS.get(current, [])
    return next_status in allowed

