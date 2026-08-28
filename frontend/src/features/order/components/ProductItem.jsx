import { formatMoney } from '../shopFormatting.js';

export function ProductItem({ product, quantity, disabled, onChange }) {
  const soldOut = product.stock <= 0;

  return (
    <article className="product-item">
      <div>
        <strong>{product.food_name}</strong>
        <small>{soldOut ? '已售罄' : `库存 ${product.stock}`}</small>
      </div>
      <span>{formatMoney(product.price)}</span>
      <div className="quantity" aria-label={`${product.food_name}数量`}>
        <button
          type="button"
          aria-label={`减少${product.food_name}`}
          disabled={disabled || quantity === 0}
          onClick={() => onChange(product, -1)}
        >
          −
        </button>
        <b>{quantity}</b>
        <button
          type="button"
          aria-label={`增加${product.food_name}`}
          disabled={disabled || soldOut || quantity >= product.stock}
          onClick={() => onChange(product, 1)}
        >
          ＋
        </button>
      </div>
    </article>
  );
}
