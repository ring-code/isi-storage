# app/utility/sync_logic.py

from app.products.models import Product, ProductUnit
from app.sales.models import CustomerOrder, OrderItem, PublicProduct, PublicVariation, ShopCategory
from app.utility.specification_logic import get_definitions_for_categories, get_all_values_for_product
from sqlalchemy.orm import joinedload
import re

# --- MAIN ORCHESTRATOR ---

def build_woocommerce_payload() -> list:
    """
    Builds the complete, structured payload of all PublicProducts and their
    dynamically generated variations for syncing to WooCommerce.
    """
    payload = []
    
    # Pre-fetch all necessary data in bulk to avoid N+1 query issues.
    inventory_data = _get_all_inventory_data()
    
    # Eagerly load the variations and their related data.
    public_products = PublicProduct.query.options(
        joinedload(PublicProduct.variations).joinedload(PublicVariation.manufacturing_product).joinedload(Product.shop_categories).joinedload(ShopCategory.parent)
    ).all()
    
    for pp in public_products:
        product_data = _build_single_product_data(pp, inventory_data)
        if product_data and product_data.get("variations"):
            payload.append(product_data)
    
    return payload


# --- PRIVATE HELPER FUNCTIONS ---

def _get_all_inventory_data() -> dict:
    """
    Performs efficient, bulk queries to pre-calculate all physical and virtual
    inventory data required for the sync.
    """
    # 1. Get all physical units with their essential relationships pre-loaded.
    all_units = ProductUnit.query.options(joinedload(ProductUnit.bookings)).all()
    
    # 2. Get all unfulfilled order items with their relationships pre-loaded.
    unfulfilled_items = OrderItem.query.join(CustomerOrder).options(
        joinedload(OrderItem.customer_order),
        joinedload(OrderItem.public_variation)
    ).filter(
        CustomerOrder.status == 'Pending Fulfillment'
    ).all()
    
    return {
        'all_units': all_units,
        'unfulfilled_items': unfulfilled_items
    }


def _build_single_product_data(pp: PublicProduct, inventory_data: dict) -> dict:
    """
    Assembles the data for a single WooCommerce 'Variable Product' by dynamically
    grouping units into variations.
    """
    # 1. Build the payload for each variation from the existing PublicVariation records.
    variations_payload = [
        _build_variation_data(variation, inventory_data) 
        for variation in pp.variations
    ]
    
    if not variations_payload:
        return {}

    # 2. Build the parent attribute structure from the generated variations.
    parent_attributes_payload = _get_parent_attribute_structure(variations_payload)
    
    # 3. Collect all Shop Categories from the underlying internal SKUs of the variations.
    all_shop_categories = set()
    for var in pp.variations:
        for shop_cat in var.manufacturing_product.shop_categories:
            all_shop_categories.add(shop_cat)
    hierarchical_categories = _build_hierarchical_categories(list(all_shop_categories))
    
    # 4. Get the shipping class from the Grade object.
    grade_obj = pp.grade_object
    shipping_class = grade_obj.shipping_class_slug if grade_obj else None

    return {
        "isi_public_product_id": pp.id, "name": pp.name, "public_sku": pp.public_sku,
        "type": "variable", "status": "publish",
        "shipping_class": shipping_class,
        "shop_categories": hierarchical_categories,
        "attributes": parent_attributes_payload,
        "variations": variations_payload
    }


def _build_variation_data(variation: PublicVariation, inventory_data: dict) -> dict:
    """
    Assembles the data for a single variation, reading the stable hash from the DB
    and calculating its specific inventory.
    """
    pp = variation.public_product
    mfg_product = variation.manufacturing_product

    # 1. Get all definitions that apply to this product's internal category.
    all_definitions = get_definitions_for_categories([mfg_product.category_id])
    
    # 2. Get the final, resolved values for all specifications on this product.
    final_specs = get_all_values_for_product(mfg_product)
    
    # 3. Build the attributes dictionary directly. No helper needed.
    attributes = {}
    for definition in all_definitions:
        # Only consider specs that are linked to a syncable attribute.
        if definition.attribute and definition.attribute.sync_behavior != 'do_not_sync':
            value = final_specs.get(definition.name)
            
            # Only include attributes that have a final, non-empty value.
            if value is not None and str(value).strip() != '':
                attributes[definition.attribute.name] = str(value)


    # Read the stable hash from the database for identity.
    isi_variation_id = variation.isi_variation_id

    # Generate the SKU from the raw attributes we just calculated.
    raw_suffix = "-".join(str(v).upper().replace(' ', '-') for k, v in sorted(attributes.items()))
    sku_suffix = re.sub(r'[^A-Z0-9-]+', '', raw_suffix)
    final_sku = f"{pp.public_sku}-{sku_suffix}" if sku_suffix else pp.public_sku

    # Calculate inventory for this specific variation.
    inventory = _get_inventory_for_variation(variation, inventory_data)

    return {
        "isi_variation_id": str(isi_variation_id),
        "sku": final_sku,
        "attributes": attributes,
        "price": {"sale": pp.final_sale_price, "first_day": pp.final_first_day_price, "next_day": pp.final_next_day_price},
        "tax_rate": pp.final_tax_rate,
        "is_rentable": pp.grade_type == 'rental_grade',
        "is_sellable": pp.grade_type == 'sale_grade',
        "inventory": inventory
    }


def _get_inventory_for_variation(variation: PublicVariation, inventory_data: dict) -> dict:
    """
    Calculates inventory data (physical and virtual) for a specific PublicVariation.
    """
    # Filter the global list of units to find ones matching this variation's blueprint and grade.
    units_for_variation = [
        unit for unit in inventory_data['all_units']
        if unit.product_id == variation.manufacturing_product_id and \
           ((variation.public_product.grade_type == 'rental_grade' and unit.rental_grade_id == variation.public_product.grade_id) or \
            (variation.public_product.grade_type == 'sale_grade' and unit.sale_grade_id == variation.public_product.grade_id))
    ]
    
    total_stock = len([u for u in units_for_variation if u.condition == 'available'])
    
    # Calendar Data (from pre-fetched bookings)
    availability_calendar = []
    if variation.public_product.grade_type == 'rental_grade':
        for unit in units_for_variation:
            bookings_list = [
                {'start': booking.start_date.isoformat(), 'end': booking.end_date.isoformat()}
                for booking in unit.bookings
            ]
            availability_calendar.append({'unit_id': unit.unit_id, 'bookings': bookings_list})

    # Unfulfilled Orders Data (matched by PublicVariation ID)
    unfulfilled_orders = []
    matching_items = [
        item for item in inventory_data['unfulfilled_items']
        if item.public_variation_id == variation.id
    ]
    
    for item in matching_items:
        unfulfilled_orders.append({
            'quantity': item.quantity,
            'start': item.customer_order.start_date.isoformat() if item.customer_order.start_date else None,
            'end': item.customer_order.end_date.isoformat() if item.customer_order.end_date else None
        })

    return {
        'total_stock': total_stock,
        'availability_calendar': availability_calendar,
        'unfulfilled_orders': unfulfilled_orders
    }


def _get_parent_attribute_structure(variations_payload: list) -> list:
    """
    Analyzes a list of generated variation payloads to determine the parent
    attribute structure.
    """
    attributes_map = {}
    for var_data in variations_payload:
        for name, value in var_data['attributes'].items():
            if name not in attributes_map:
                attributes_map[name] = {'name': name, 'is_variation': True, 'options': set()}
            attributes_map[name]['options'].add(value)

    return [{**data, 'options': list(data['options'])} for data in attributes_map.values()]


def _build_hierarchical_categories(shop_categories: list) -> list:
    """
    Takes a list of ShopCategory objects and returns a list of dictionaries
    containing name and parent name, suitable for hierarchical syncing.
    """
    processed_ids, category_payload, queue = set(), [], list(shop_categories)
    
    while queue:
        category = queue.pop(0)
        if category and category.id not in processed_ids:
            category_payload.append({
                'name': category.name, 'parent': category.parent.name if category.parent else None
            })
            processed_ids.add(category.id)
            if category.parent:
                queue.append(category.parent)
                
    return [dict(t) for t in {tuple(d.items()) for d in category_payload}]