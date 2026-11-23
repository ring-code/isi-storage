# isi_storage/app/utility/price_logic.py
from app.sales.models import CustomerOrder, OrderItem, PublicVariation
from decimal import Decimal
from sqlalchemy.orm import joinedload


def calculate_item_price_and_total(variation_id: int, quantity: int, order_type: str, start_date, end_date) -> dict:
    """
    Calculates the price_per_item and line_total for a single potential order item.
    This is the central source of truth for item pricing.

    Args:
        variation: The PublicVariation object being ordered.
        quantity: The quantity of the item.
        order_type: The type of order ('rental' or 'sale').
        start_date: The order's start date (for rentals).
        end_date: The order's end date (for rentals).

    Returns:
        A dictionary containing {'price_per_item': Decimal, 'line_total': Decimal}.
    """
    variation = PublicVariation.query.get(variation_id)
    if not variation:
        # Return zero values if the variation ID is invalid.
        return {'price_per_item': Decimal('0.00'), 'line_total': Decimal('0.00')}

    public_product = variation.public_product
    price_per_item = Decimal('0.00')
    line_total_net = Decimal('0.00')

    if order_type == 'rental':
        first_day_price = public_product.final_first_day_price or Decimal('0.00')
        next_day_price = public_product.final_next_day_price or Decimal('0.00')
        
        rental_duration_days = 0
        if start_date and end_date:
            rental_duration_days = (end_date - start_date).days + 1

        if rental_duration_days > 0:
            price_per_item += first_day_price
            if rental_duration_days > 1:
                subsequent_days = rental_duration_days - 1
                price_per_item += (next_day_price * subsequent_days)
            
            line_total_net = price_per_item * quantity

    else:  # Sale order
        sale_price = public_product.final_sale_price or Decimal('0.00')
        price_per_item = sale_price
        line_total_net = price_per_item * quantity
    
    return {
        'price_per_item': price_per_item,
        'line_total': line_total_net
    }


def calculate_order_totals(order: CustomerOrder) -> dict:
    """
    Calculates the complete financial totals for a CustomerOrder by iterating
    through its items and using the central pricing helper.
    """
    subtotal_net = Decimal('0.00')
    tax_amount = Decimal('0.00')

    # Eagerly load the relationships needed to prevent N+1 queries.
    items_to_process = OrderItem.query.filter_by(customer_order_id=order.id).options(
        joinedload(OrderItem.public_variation).joinedload(PublicVariation.public_product)
    ).all()

    for item in items_to_process:
        price_data = calculate_item_price_and_total(
            item.public_variation_id,
            item.quantity,
            order.order_type,
            order.start_date,
            order.end_date
        )
        
        # Update the OrderItem's denormalized prices.
        item.price_per_item = price_data['price_per_item']
        item.line_total = price_data['line_total']
        
        # Add this item's contribution to the order's totals.
        subtotal_net += item.line_total
        
        item_tax_rate = item.public_variation.public_product.final_tax_rate or Decimal('0.00')
        tax_amount += (item.line_total * item_tax_rate)

    # Calculate grand total (this part is unchanged).
    grand_total = subtotal_net + tax_amount + (order.shipping_cost or Decimal('0.00')) - (order.discount_amount or Decimal('0.00'))

    return {
        'subtotal_net': subtotal_net,
        'tax_amount': tax_amount,
        'grand_total': grand_total
    }