# MongoDB 店铺与商品数据契约

第二阶段不会自动生成目录数据。订单页只读取 `smart_customer_service` 数据库中的 `shops` 和 `products` 集合；应用启动时会创建唯一索引。

## shops

`shop_id` 必须唯一。营业时间的 `day_of_week` 使用 `0` 表示星期一、`6` 表示星期日；跨午夜可令 `close_time` 小于 `open_time`。

```javascript
db.shops.insertOne({
  shop_id: "shop-001",
  shop_name: "SmartServe 示例餐厅",
  is_active: true,
  is_accepting_orders: true,
  timezone: "Asia/Shanghai",
  business_hours: [
    { day_of_week: 0, open_time: "00:00:00", close_time: "23:59:59" },
    { day_of_week: 1, open_time: "00:00:00", close_time: "23:59:59" },
    { day_of_week: 2, open_time: "00:00:00", close_time: "23:59:59" },
    { day_of_week: 3, open_time: "00:00:00", close_time: "23:59:59" },
    { day_of_week: 4, open_time: "00:00:00", close_time: "23:59:59" },
    { day_of_week: 5, open_time: "00:00:00", close_time: "23:59:59" },
    { day_of_week: 6, open_time: "00:00:00", close_time: "23:59:59" }
  ],
  minimum_order_amount: 20.0,
  delivery_fee: 3.0,
  address: {
    province: "北京市",
    city: "北京市",
    district: "朝阳区",
    detail_address: "建国路88号"
  },
  longitude: 116.475,
  latitude: 39.908,
  adcode: "110105",
  formatted_address: "北京市朝阳区建国路88号",
  delivery_radius_meters: 5000,
  location_updated_at: new Date()
})
```

经纬度必须同时存在；用于演示下单时，收货地址必须在 `delivery_radius_meters` 范围内。

## products

`shop_id + food_id` 必须唯一，并且 `shop_id` 必须对应一个有效店铺。

```javascript
db.products.insertMany([
  {
    food_id: "food-001",
    shop_id: "shop-001",
    food_name: "招牌牛肉饭",
    price: 28.0,
    stock: 100,
    reserved_stock: 0,
    is_listed: true,
    is_available: true
  },
  {
    food_id: "food-002",
    shop_id: "shop-001",
    food_name: "冰柠檬茶",
    price: 8.0,
    stock: 100,
    reserved_stock: 0,
    is_listed: true,
    is_available: true
  }
])
```

客户端只提交 `food_id` 与数量；商品名、单价、库存、店铺状态和配送费用始终以后端读取的数据为准。
