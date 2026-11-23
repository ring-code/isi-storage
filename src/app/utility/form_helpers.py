# src/app/utility/form_helpers.py

# This file contains simple query_factory helpers for use in WTForms.
# It should only import models and should NOT import any form classes.

from app.definitions.models import DataType, OptionList, Attribute
from app.products.models import Product, Category
from app.sales.models import ShopCategory, PublicProduct, Customer, RentalGrade, SaleGrade
from app.inventory.models import Space, DamageTemplate
from .specification_logic import get_concrete_skus

def get_all_products():
    return Product.query.order_by(Product.name)

def get_concrete_skus_for_forms():
    return get_concrete_skus()

def get_all_categories():
    return Category.query.order_by(Category.name)

def get_all_shop_categories():
    return ShopCategory.query.order_by(ShopCategory.name)

def get_all_spaces():
    return Space.query.order_by(Space.name)

def get_all_attributes():
    return Attribute.query.order_by(Attribute.name)

def get_all_data_types():
    return DataType.query.order_by(DataType.name)

def get_data_types_for_list():
    return DataType.query.filter(DataType.display_type.notin_(['boolean', 'range', 'textarea'])).order_by(DataType.name)

def get_all_option_lists():
    return OptionList.query.order_by(OptionList.name)

def get_all_damage_templates():
    return DamageTemplate.query.order_by(DamageTemplate.name)

def get_all_rental_grades():
    return RentalGrade.query.order_by(RentalGrade.name)

def get_all_sale_grades():
    return SaleGrade.query.order_by(SaleGrade.name)

def get_all_public_products():
    return PublicProduct.query.order_by(PublicProduct.name)

def get_all_customers():
    return Customer.query.order_by(Customer.last_name, Customer.first_name)