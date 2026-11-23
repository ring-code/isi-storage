# app/products/models.py

from datetime import datetime, timezone
from app.extensions import db
from app.associations import (
    booking_unit_association, 
    product_shop_category_association, 
    category_rental_grade_association, 
    category_sale_grade_association, 
    category_hidden_specification_association, 
) 


class Product(db.Model):
    __tablename__ = 'product'
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    product_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    serial_number_prefix = db.Column(db.String(100), nullable=True)
    description_txt = db.Column(db.String(255), nullable=True)
    standard_production_cost = db.Column(db.Numeric(10, 2), nullable=True)
    damage_template_id = db.Column(db.Integer, db.ForeignKey('damage_template.id'), nullable=True)
    damage_template = db.relationship("DamageTemplate", back_populates='products')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    product_units = db.relationship("ProductUnit", back_populates='product', lazy='dynamic')
    category_id = db.Column(
        db.Integer, 
        db.ForeignKey('category.category_id', ondelete='RESTRICT'),
        nullable=False
    )
    category = db.relationship("Category", back_populates='products')
    specification_values = db.relationship("SpecificationValue", back_populates='product', cascade="all, delete-orphan")
    attribute_values = db.relationship(
        "ProductAttribute",
        back_populates='product',
        cascade="all, delete-orphan"
    )
    shop_categories = db.relationship(
        "ShopCategory",
        secondary=product_shop_category_association,
        back_populates='products'
    )
    user = db.relationship("User", backref='created_products')
    photos = db.relationship("ProductPhoto", back_populates='product', cascade='all, delete-orphan')
    

class SpecificationDefinition(db.Model):
    __tablename__ = 'specification_definition'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.category_id'), nullable=False)
    category = db.relationship("Category", back_populates='specification_definitions')
    attribute_id = db.Column(db.Integer, db.ForeignKey('attribute.attribute_id'), nullable=True)
    attribute = db.relationship("Attribute", back_populates='specification_definitions')
    is_inheritable = db.Column(db.Boolean, default=False, nullable=False)
    requires_implementation = db.Column(db.Boolean, default=False, nullable=False)
    forbid_override = db.Column(db.Boolean, default=False, nullable=False)
    rule_overrides = db.relationship("SpecificationRuleOverride", back_populates='definition', cascade="all, delete-orphan")
    hidden_in_categories = db.relationship(
        'Category',
        secondary=category_hidden_specification_association,
        back_populates='overridden_specifications'
    )
    data_type_id = db.Column(db.Integer, db.ForeignKey('data_type.id'), nullable=False)
    data_type = db.relationship("DataType", foreign_keys=[data_type_id])
    option_list_id = db.Column(db.Integer, db.ForeignKey('option_list.id'), nullable=True)
    option_list = db.relationship("OptionList")
    __table_args__ = (
        db.UniqueConstraint('name', 'category_id', name='_spec_def_name_category_uc'),
        db.UniqueConstraint('attribute_id', 'category_id', name='_spec_def_attr_category_uc'),
    )

    def to_json(self):
        return {
            'id': self.id,
            'name': self.name,
            'attribute': self.attribute.to_json() if self.attribute else None,
            'data_type': self.data_type.to_json() if self.data_type else None,
            'option_list': self.option_list.to_json() if self.option_list else None
        }


class SpecificationValue(db.Model):
    __tablename__ = 'specification_value'
    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.String(255), nullable=False)
    definition_id = db.Column(db.Integer, db.ForeignKey('specification_definition.id'), nullable=False)
    definition = db.relationship(
        'SpecificationDefinition',
        backref=db.backref('values', cascade="all, delete-orphan")
    )
    category_id = db.Column(db.Integer, db.ForeignKey('category.category_id'), nullable=True)
    category = db.relationship("Category", back_populates='specification_values')
    product_id = db.Column(db.Integer, db.ForeignKey('product.product_id'), nullable=True)
    product = db.relationship("Product", back_populates='specification_values')
    unit_id = db.Column(db.Integer, db.ForeignKey('product_unit.unit_id'), nullable=True)
    unit = db.relationship("ProductUnit", back_populates='specification_values')
    __table_args__ = (
        db.UniqueConstraint('definition_id', 'category_id', name='_spec_val_def_cat_uc'),
        db.UniqueConstraint('definition_id', 'product_id', name='_spec_val_def_prod_uc'),
        db.UniqueConstraint('definition_id', 'unit_id', name='_spec_val_def_unit_uc'),
    )


class SpecificationRuleOverride(db.Model):
    __tablename__ = 'specification_rule_override'
    id = db.Column(db.Integer, primary_key=True)
    
    # Which category is doing the overriding?
    category_id = db.Column(db.Integer, db.ForeignKey('category.category_id'), nullable=False)
    category = db.relationship("Category", back_populates='rule_overrides')

    # Which inherited definition's rules are being overridden?
    definition_id = db.Column(db.Integer, db.ForeignKey('specification_definition.id'), nullable=False)
    definition = db.relationship("SpecificationDefinition", back_populates='rule_overrides')

    # --- The Overridden Rules ---
    # These are nullable because a user might only want to override one rule,
    # not all of them. A NULL value means "just use the parent's rule".
    is_inheritable = db.Column(db.Boolean, nullable=True)
    requires_implementation = db.Column(db.Boolean, nullable=True)
    forbid_override = db.Column(db.Boolean, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('category_id', 'definition_id', name='_category_definition_uc'),
    )


class ProductPhoto(db.Model):
    __tablename__ = 'product_photo'
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    photo_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.product_id'))
    photo_filename = db.Column(db.String(255), nullable=False)
    product = db.relationship("Product", back_populates='photos')


class Category(db.Model):
    __tablename__ = 'category'
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    category_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('category.category_id'), nullable=True)
    children = db.relationship(
        'Category',
        backref=db.backref('parent', remote_side='Category.category_id'),
        cascade="all, delete"
    )
    products = db.relationship("Product", back_populates='category', lazy='dynamic')    
    available_rental_grades = db.relationship(
        'RentalGrade',
        secondary=category_rental_grade_association,
        back_populates='available_in_categories'
    )   
    available_sale_grades = db.relationship(
        'SaleGrade',
        secondary=category_sale_grade_association,
        back_populates='available_in_categories'
    )
    specification_definitions = db.relationship("SpecificationDefinition", back_populates='category', cascade="all, delete")
    specification_values = db.relationship("SpecificationValue", back_populates='category', cascade="all, delete-orphan")
    overridden_specifications = db.relationship(
        'SpecificationDefinition',
        secondary=category_hidden_specification_association,
        back_populates='hidden_in_categories'
    )
    rule_overrides = db.relationship("SpecificationRuleOverride", back_populates='category', cascade="all, delete-orphan")


class ProductUnit(db.Model):
    __tablename__ = 'product_unit'
    __table_args__ = (
        # This constraint ensures a unit can't be both for rent and for sale.
        db.CheckConstraint('(rental_grade_id IS NULL) OR (sale_grade_id IS NULL)', name='_rental_or_sale_check'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    )
    unit_id = db.Column(db.Integer, primary_key=True)
    serial_number = db.Column(db.String(50), unique=True, nullable=False)
    actual_production_cost = db.Column(db.Numeric(10, 2), nullable=True)
    damage_count = db.Column(db.Integer, default=0)
    condition = db.Column(db.String(100), nullable=False, default='in_rental_pool', server_default='in_rental_pool')
    product_id = db.Column(db.Integer, db.ForeignKey('product.product_id'), nullable=False)
    product = db.relationship("Product", back_populates='product_units')
    rental_grade_id = db.Column(db.Integer, db.ForeignKey('rental_grade.id'), nullable=True)
    rental_grade = db.relationship("RentalGrade", back_populates='product_units')   
    sale_grade_id = db.Column(db.Integer, db.ForeignKey('sale_grade.id'), nullable=True)
    sale_grade = db.relationship("SaleGrade", back_populates='product_units')  
    description = db.Column(db.String(255), nullable=True)
    bookings = db.relationship("Booking", secondary=booking_unit_association, back_populates="units")
    space_id = db.Column(db.Integer, db.ForeignKey('space.id'), nullable=True)
    space = db.relationship("Space", backref=db.backref('product_units', lazy='dynamic'))
    asset_tag = db.relationship(
        'AssetTag', 
        backref=db.backref('unit', uselist=False), 
        uselist=False,
        cascade="all, delete-orphan" # Automatically delete the tag if the unit is deleted
    )
    specification_values = db.relationship("SpecificationValue", back_populates='unit', cascade="all, delete-orphan")
    attribute_values = db.relationship("ProductUnitAttribute", back_populates='unit', cascade="all, delete-orphan")


class ProductUnitAttribute(db.Model):
    __tablename__ = 'product_unit_attribute'
    id = db.Column(db.Integer, primary_key=True)

    # What is the value?
    value = db.Column(db.String(255), nullable=False)

    # Which physical unit is this tag on?
    unit_id = db.Column(db.Integer, db.ForeignKey('product_unit.unit_id'), nullable=False)
    unit = db.relationship("ProductUnit", back_populates='attribute_values')

    # Which global Attribute (key) is being used?
    attribute_id = db.Column(db.Integer, db.ForeignKey('attribute.attribute_id'), nullable=False)
    attribute = db.relationship("Attribute") # No back_populates needed on this side for simplicity








