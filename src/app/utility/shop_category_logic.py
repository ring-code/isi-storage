# app/utility/shop_category_logic.py

from app.products.models import ProductUnit
from app.sales.models import ShopCategory

def save_unit_shop_categories(unit: ProductUnit, form_data):
    """
    Processes and saves the ShopCategory relationships for a specific ProductUnit.
    It clears existing relationships and adds the new ones.

    Args:
        unit: The ProductUnit object being modified.
        form_data: The `request.form` object from the route.
    """
    # 1. Get the list of all submitted shop category IDs from the form.
    # The input name 'shop_categories' is defined in the template.
    selected_ids = form_data.getlist('shop_categories')
    
    # 2. Convert string IDs to integers.
    try:
        selected_ids = [int(id_str) for id_str in selected_ids]
    except (ValueError, TypeError):
        # Handle potential error if bad data is submitted
        selected_ids = []

    # 3. Fetch the actual ShopCategory objects from the database.
    if selected_ids:
        selected_shop_cats = ShopCategory.query.filter(ShopCategory.id.in_(selected_ids)).all()
        # 4. Assign the list of objects directly to the unit's relationship.
        # SQLAlchemy is smart enough to handle the create/update/delete operations
        # on the association table automatically.
        unit.shop_categories = selected_shop_cats
    else:
        # If no IDs were submitted, clear the relationship.
        unit.shop_categories = []


def get_hierarchical_shop_categories():
    """
    Fetches all ShopCategory objects and returns them as a flat list,
    sorted hierarchically (parents always appear before their children).
    """
    # 1. Fetch all categories from the database
    all_categories = ShopCategory.query.order_by(ShopCategory.name).all()
    
    # 2. Create a dictionary for quick lookups and to build the tree
    category_map = {cat.id: cat for cat in all_categories}
    
    # 3. Add a 'children' attribute to each object and build the tree structure
    for cat in all_categories:
        cat.children_list = [] # Use a custom attribute to avoid conflicts
    
    root_nodes = []
    for cat in all_categories:
        if cat.parent_id and cat.parent_id in category_map:
            category_map[cat.parent_id].children_list.append(cat)
        else:
            root_nodes.append(cat)
            
    # 4. Flatten the tree into a sorted list using a recursive helper
    sorted_list = []
    def flatten_tree(nodes):
        for node in nodes:
            sorted_list.append(node)
            if node.children_list:
                flatten_tree(node.children_list)

    flatten_tree(root_nodes)
    return sorted_list


def get_hierarchical_shop_category_label(category):
    """
    Creates an indented label for a category based on its depth.
    e.g., '↳ Furniture'
    """
    prefix = ''
    level = 0
    parent = category.parent
    while parent:
        level += 1
        parent = parent.parent
    
    if level > 0:
        prefix = '↳' + '—' * (level - 1) + ' '
        
    return prefix + category.name



