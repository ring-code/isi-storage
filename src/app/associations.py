# src/app/associations.py

from app.extensions import db


booking_unit_association = db.Table(
    'booking_unit_association',
    db.Column('booking_id', db.Integer, db.ForeignKey('booking.id'), primary_key=True),
    db.Column('unit_id', db.Integer, db.ForeignKey('product_unit.unit_id'), primary_key=True)
)


product_shop_category_association = db.Table(
    'product_shop_category_association',
    db.Column('product_id', db.Integer, db.ForeignKey('product.product_id'), primary_key=True),
    db.Column('shop_category_id', db.Integer, db.ForeignKey('shop_category.id'), primary_key=True)
)


category_rental_grade_association = db.Table(
    'category_rental_grade_association',
    db.Column('category_id', db.Integer, db.ForeignKey('category.category_id'), primary_key=True),
    db.Column('rental_grade_id', db.Integer, db.ForeignKey('rental_grade.id'), primary_key=True)
)


category_sale_grade_association = db.Table(
    'category_sale_grade_association',
    db.Column('category_id', db.Integer, db.ForeignKey('category.category_id'), primary_key=True),
    db.Column('sale_grade_id', db.Integer, db.ForeignKey('sale_grade.id'), primary_key=True)
)


category_hidden_specification_association = db.Table(
    'category_hidden_specification_association',
    db.Column('category_id', db.Integer, db.ForeignKey('category.category_id'), primary_key=True),
    db.Column('specification_definition_id', db.Integer, db.ForeignKey('specification_definition.id'), primary_key=True)
)


public_product_shop_category_association = db.Table(
    'public_product_shop_category_association',
    db.Column('public_product_id', db.Integer, db.ForeignKey('public_product.id'), primary_key=True),
    db.Column('shop_category_id', db.Integer, db.ForeignKey('shop_category.id'), primary_key=True)
)
