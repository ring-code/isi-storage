# /app/sales/models.py

from app.extensions import db
from app.associations import (
    booking_unit_association, 
    product_shop_category_association, 
    category_rental_grade_association, 
    category_sale_grade_association
)
from datetime import datetime, timezone


class RentalGrade(db.Model):
    __tablename__ = 'rental_grade'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    # --- Hard-coded rental price fields ---
    # Nullable=True allows a grade to be "abstract"
    first_day_price = db.Column(db.Numeric(10, 2), nullable=True)
    next_day_price = db.Column(db.Numeric(10, 2), nullable=True)
    tax_rate = db.Column(db.Numeric(5, 4), nullable=True) 
    
    color = db.Column(db.String(7), nullable=True)
    
    shipping_class_slug = db.Column(db.String(100), nullable=True)

    # Relationship to ProductUnits using this grade
    product_units = db.relationship("ProductUnit", back_populates='rental_grade')
    
    # Relationship to flexible key-value properties
    properties = db.relationship("RentalCommercialProperty", back_populates='rental_grade', cascade="all, delete-orphan")

    # Internal Categories this applies to
    available_in_categories = db.relationship(
        'Category',
        secondary=category_rental_grade_association,
        back_populates='available_rental_grades'
    )


class SaleGrade(db.Model):
    __tablename__ = 'sale_grade'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    # --- Hard-coded sale price fields ---
    sale_price = db.Column(db.Numeric(10, 2), nullable=True)
    tax_rate = db.Column(db.Numeric(5, 4), nullable=True)

    color = db.Column(db.String(7), nullable=True)

    shipping_class_slug = db.Column(db.String(100), nullable=True)
    
    # --- Hard-coded business rule flag ---
    is_convertible_to_rental = db.Column(db.Boolean, default=False, nullable=False)

    # Relationship to ProductUnits using this grade
    product_units = db.relationship("ProductUnit", back_populates='sale_grade')

    # Relationship to flexible key-value properties
    properties = db.relationship("SaleCommercialProperty", back_populates='sale_grade', cascade="all, delete-orphan")

    # Internal Categories this applies to
    available_in_categories = db.relationship(
        'Category',
        secondary=category_sale_grade_association,
        back_populates='available_sale_grades'
    )


class CommercialProperty(db.Model):
    __tablename__ = 'commercial_property'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False)
    value = db.Column(db.String(255), nullable=False)
    
    # This tells us if the value is a 'price' or a 'slug' for UI/validation
    property_type = db.Column(db.String(50), nullable=False, default='price')
    
    # Polymorphic relationship setup
    grade_type = db.Column(db.String(50)) # 'rental' or 'sale'
    grade_id = db.Column(db.Integer)
    __mapper_args__ = { 'polymorphic_on': grade_type }


class RentalCommercialProperty(CommercialProperty):
    __tablename__ = 'rental_commercial_property'
    id = db.Column(db.Integer, db.ForeignKey('commercial_property.id'), primary_key=True)
    rental_grade_id = db.Column(db.Integer, db.ForeignKey('rental_grade.id', ondelete="CASCADE"))
    rental_grade = db.relationship("RentalGrade", back_populates='properties')
    __mapper_args__ = {'polymorphic_identity': 'rental_grade'}


class SaleCommercialProperty(CommercialProperty):
    __tablename__ = 'sale_commercial_property'
    id = db.Column(db.Integer, db.ForeignKey('commercial_property.id'), primary_key=True)
    sale_grade_id = db.Column(db.Integer, db.ForeignKey('sale_grade.id', ondelete="CASCADE"))
    sale_grade = db.relationship("SaleGrade", back_populates='properties')
    __mapper_args__ = {'polymorphic_identity': 'sale_grade'}


class ShopCategory(db.Model):
    __tablename__ = 'shop_category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    
    # Self-referencing relationship for parent-child hierarchy
    parent_id = db.Column(db.Integer, db.ForeignKey('shop_category.id'), nullable=True)
    children = db.relationship(
        'ShopCategory',
        backref=db.backref('parent', remote_side='ShopCategory.id')
    )
    
    # Many-to-many relationship with products
    products = db.relationship(
        'Product',
        secondary=product_shop_category_association,
        back_populates='shop_categories'
    )


class PublicProduct(db.Model):
    __tablename__ = 'public_product'
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(255), nullable=False, unique=True)
    public_sku = db.Column(db.String(100), nullable=True, unique=True, index=True)
    
    # --- Link to Commercial Terms (The Grade) ---
    grade_type = db.Column(db.String(50), nullable=False)
    grade_id = db.Column(db.Integer, nullable=False)
    
    # --- Denormalized Price Data ---
    final_sale_price = db.Column(db.Numeric(10, 2), nullable=True)
    final_first_day_price = db.Column(db.Numeric(10, 2), nullable=True)
    final_next_day_price = db.Column(db.Numeric(10, 2), nullable=True)
    final_tax_rate = db.Column(db.Numeric(5, 4), nullable=False, default=0)
    
    # --- Relationships ---
    variations = db.relationship("PublicVariation", back_populates='public_product', cascade="all, delete-orphan")
    
    # --- UniqueConstraint to prevent duplicates ---
    __table_args__ = (
        db.UniqueConstraint('grade_type', 'grade_id', name='_public_product_grade_uc'),
    )

    @property
    def grade_object(self):
        if self.grade_type == 'rental_grade':
            return RentalGrade.query.get(self.grade_id)
        elif self.grade_type == 'sale_grade':
            return SaleGrade.query.get(self.grade_id)
        return None

    def __repr__(self):
        return f'<PublicProduct for Grade {self.grade_type}:{self.grade_id}>'
    
    
class PublicVariation(db.Model):
    __tablename__ = 'public_variation'
    id = db.Column(db.Integer, primary_key=True)
    # hash for woocommerce order polling
    isi_variation_id = db.Column(db.BigInteger, unique=True, nullable=True, index=True)
    
    # --- Link back to the parent PublicProduct ---
    public_product_id = db.Column(db.Integer, db.ForeignKey('public_product.id'), nullable=False)
    public_product = db.relationship("PublicProduct", back_populates='variations')
    
    # --- Link to the Internal "Blueprint" ---
    manufacturing_product_id = db.Column(db.Integer, db.ForeignKey('product.product_id'), nullable=False)
    manufacturing_product = db.relationship("Product") 
    
    __table_args__ = (
        db.UniqueConstraint('public_product_id', 'manufacturing_product_id', name='_public_variation_uc'),
    )

    def __repr__(self):
        return f'<PublicVariation for Product ID {self.manufacturing_product_id}>'


class Customer(db.Model):
    __tablename__ = 'customer'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    
    # These fields can be populated from the billing address
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(50), nullable=True)
    
    # Relationships
    orders = db.relationship("CustomerOrder", back_populates='customer')
    addresses = db.relationship("Address", back_populates='customer', cascade="all, delete-orphan")

    def __repr__(self):
        return f'<Customer {self.first_name} {self.last_name}>'


class Address(db.Model):
    __tablename__ = 'address'
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    
    # Address fields from the screenshot
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    address_line_1 = db.Column(db.String(255), nullable=False)
    address_line_2 = db.Column(db.String(255), nullable=True) # For "Add flat, suite, etc."
    postcode = db.Column(db.String(20), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), nullable=False)
    
    # Relationships
    customer = db.relationship("Customer", back_populates='addresses')

    def __repr__(self):
        return f'<Address {self.address_line_1}, {self.city}>'
    

class CustomerOrder(db.Model):
    __tablename__ = 'customer_order'
    id = db.Column(db.Integer, primary_key=True)
    wc_order_id = db.Column(db.Integer, unique=True, nullable=True, index=True)
    
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True) # Nullable for guest checkouts
    
    # Foreign keys to the Address table
    shipping_address_id = db.Column(db.Integer, db.ForeignKey('address.id'), nullable=True)
    billing_address_id = db.Column(db.Integer, db.ForeignKey('address.id'), nullable=True)

    # --- FINANCIAL COLUMNS ---
    subtotal_net = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    shipping_cost = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    tax_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    # For manual price adjustments/overwrites
    discount_amount = db.Column(db.Numeric(10, 2), nullable=True)
    discount_reason = db.Column(db.String(255), nullable=True)

    grand_total = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    
    # Fields from payment/shipping options
    shipping_method_title = db.Column(db.String(255), nullable=True)
    payment_method_title = db.Column(db.String(255), nullable=True)
    customer_note = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(50), nullable=False, default='Draft')
    order_type = db.Column(db.String(50), nullable=False) # 'rental' or 'sale'
    start_date = db.Column(db.Date, nullable=True) # Nullable for sale orders
    end_date = db.Column(db.Date, nullable=True)   # Nullable for sale orders
    
    customer = db.relationship("Customer", back_populates='orders')
    
    # Define relationships to the Address model
    shipping_address = db.relationship("Address", foreign_keys=[shipping_address_id])
    billing_address = db.relationship("Address", foreign_keys=[billing_address_id])

    order_items = db.relationship("OrderItem", back_populates='customer_order', cascade="all, delete-orphan")


class OrderItem(db.Model):
    __tablename__ = 'order_item'
    id = db.Column(db.Integer, primary_key=True)
    customer_order_id = db.Column(db.Integer, db.ForeignKey('customer_order.id'), nullable=False)
   
    # Link to the PublicVariation
    public_variation_id = db.Column(db.Integer, db.ForeignKey('public_variation.id'), nullable=False)
    
    quantity = db.Column(db.Integer, nullable=False)
    
    # Store the price AT THE TIME OF THE ORDER for historical accuracy
    price_per_item = db.Column(db.Numeric(10, 2), nullable=False)
    line_total = db.Column(db.Numeric(10, 2), nullable=False)
    
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=True)
    
    # Relationships
    customer_order = db.relationship("CustomerOrder", back_populates='order_items')
    booking = db.relationship("Booking", back_populates="order_items")  
    public_variation = db.relationship("PublicVariation", backref="order_items")
    

class Booking(db.Model):
    __tablename__ = 'booking'
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    units = db.relationship("ProductUnit", secondary=booking_unit_association, back_populates="bookings")
    order_items = db.relationship("OrderItem", back_populates="booking")


