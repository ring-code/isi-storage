# /src/app/definitions/models.py

from app.extensions import db
from sqlalchemy.dialects.postgresql import JSONB


class DataType(db.Model):
    __tablename__ = 'data_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    display_type = db.Column(db.String(50), nullable=False, default='text')
    validation_rules = db.Column(JSONB, nullable=True)
    attributes = db.relationship("Attribute", back_populates='data_type', foreign_keys='Attribute.data_type_id')
    option_lists = db.relationship("OptionList", back_populates='item_data_type', lazy='dynamic')
    def to_json(self):
        """Serializes the object to a JSON-compatible dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'display_type': self.display_type,
            'validation_rules': self.validation_rules or {}          
        }


class OptionList(db.Model):
    __tablename__ = 'option_list'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    # What kind of items are in this list?
    item_data_type_id = db.Column(db.Integer, db.ForeignKey('data_type.id'), nullable=False)
    item_data_type = db.relationship("DataType", back_populates='option_lists')
    display_hint = db.Column(db.String(50), nullable=True, default=None)
    selection_rules = db.Column(JSONB, nullable=True)
    
    # Can a user select more than one item from this list?
    allow_multiple_selections = db.Column(db.Boolean, default=False, nullable=False)

    # Relationship to the actual items
    items = db.relationship("OptionListItem", back_populates='option_list', cascade="all, delete-orphan")
    attributes = db.relationship("Attribute", back_populates='option_list')
    specification_definitions = db.relationship("SpecificationDefinition", back_populates='option_list')

    def to_json(self):
        return {
            'id': self.id,
            'name': self.name,
            'allow_multiple_selections': self.allow_multiple_selections,
            'display_hint': self.display_hint,
            'item_data_type': self.item_data_type.to_json() if self.item_data_type else None,
            'items': [{'id': item.id, 'value': item.value} for item in self.items]
        }


class OptionListItem(db.Model):
    __tablename__ = 'option_list_item'
    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.String(255), nullable=False)
    display_order = db.Column(db.Integer, default=0)
    
    option_list_id = db.Column(db.Integer, db.ForeignKey('option_list.id'), nullable=False)
    option_list = db.relationship("OptionList", back_populates='items')


class Attribute(db.Model):
    __tablename__ = 'attribute'
    attribute_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    sync_behavior = db.Column(
        db.String(50), 
        nullable=False, 
        default='do_not_sync', 
        server_default='do_not_sync'
    )
    data_type_id = db.Column(db.Integer, db.ForeignKey('data_type.id'), nullable=False)
    data_type = db.relationship("DataType", back_populates='attributes', foreign_keys=[data_type_id])
    product_attributes = db.relationship("ProductAttribute", back_populates='attribute', cascade="all, delete-orphan")
    specification_definitions = db.relationship("SpecificationDefinition", back_populates='attribute')
    option_list_id = db.Column(db.Integer, db.ForeignKey('option_list.id'), nullable=True)
    option_list = db.relationship("OptionList", back_populates='attributes')

    def to_json(self):
        return {
            'id': self.attribute_id,
            'name': self.name,
            'data_type': self.data_type.to_json() if self.data_type else None,
            'option_list': self.option_list.to_json() if self.option_list else None
        }


class ProductAttribute(db.Model):
    __tablename__ = 'product_attribute'
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    product_attribute_id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.product_id'))
    attribute_id = db.Column(db.Integer, db.ForeignKey('attribute.attribute_id'))
    value = db.Column(db.String(255), nullable=False)
    product = db.relationship("Product", back_populates='attribute_values')
    attribute = db.relationship(
        'Attribute', 
        back_populates='product_attributes'
    )