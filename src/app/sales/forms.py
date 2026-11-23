# app/sales/forms.py

from flask_wtf import FlaskForm
from wtforms import Form, StringField, DateField, IntegerField, SelectField, SubmitField, DecimalField, HiddenField, FieldList, FormField, BooleanField
from wtforms.fields import ColorField
from wtforms.validators import DataRequired, Email, Optional, NumberRange, ValidationError
from wtforms_sqlalchemy.fields import QuerySelectField, QuerySelectMultipleField

from .models import ShopCategory, RentalGrade, SaleGrade, Customer
from app.utility.public_product_logic import get_available_rental_grades, get_available_sale_grades
from app.utility.validation_logic import validate_commercial_properties
from app.utility.form_helpers import (
    get_all_public_products,
    get_all_customers,
    get_all_shop_categories,
    get_all_categories
)


class DeleteForm(FlaskForm):
    """A simple form with just a CSRF token and a method override for DELETE requests."""
    _method = HiddenField(default='DELETE')
    submit = SubmitField('Delete')


class CommercialPropertyForm(Form):
    key = StringField('Property Name', validators=[Optional()])
    value = StringField('Property Value', validators=[Optional()])


class RentalGradeForm(FlaskForm):
    """
    Form for creating and editing a RentalGrade.
    """
    name = StringField('Grade Name', validators=[DataRequired()], description="e.g., Premium, Standard, Budget")
    
    # --- The hard-coded fields ---
    first_day_price = DecimalField('First Day Price (€)', validators=[DataRequired(), NumberRange(min=0)], places=2)
    next_day_price = DecimalField('Subsequent Day Price (€)', validators=[DataRequired(), NumberRange(min=0)], places=2)
    tax_rate = DecimalField(
        'Tax Rate (e.g., 0.19 for 19%)',
        validators=[Optional(), NumberRange(min=0, max=1)],
        places=4
    )
    shipping_class_slug = StringField('Shipping Class Slug', validators=[Optional()])

    color = ColorField('Display Color', validators=[Optional()])
    # --- Field for assigning to categories ---
    available_in_categories = QuerySelectMultipleField(
        'Available in Categories',
        query_factory=get_all_categories,
        get_label='name'
    )
    
    # --- FieldList for the flexible properties ---
    properties = FieldList(
        FormField(CommercialPropertyForm), 
        min_entries=0, 
        label="Additional Price Properties",
        validators=[validate_commercial_properties]
    )

    submit = SubmitField('Save Rental Grade')
    id = HiddenField() # For editing

    def validate_name(self, name):
        query = RentalGrade.query.filter(RentalGrade.name == name.data)
        if self.id.data:
            query = query.filter(RentalGrade.id != int(self.id.data))
        if query.first():
            raise ValidationError('A Rental Grade with this name already exists.')


class SaleGradeForm(FlaskForm):
    """
    Form for creating and editing a SaleGrade.
    """
    name = StringField('Grade Name', validators=[DataRequired()], description="e.g., New for Sale, Used - As Is")
    
    # --- The hard-coded fields ---

    sale_price = DecimalField('Sale Price (€)', validators=[DataRequired(), NumberRange(min=0)], places=2)
    tax_rate = DecimalField(
        'Tax Rate (e.g., 0.19 for 19%)',
        validators=[Optional(), NumberRange(min=0, max=1)],
        places=4
    )
    color = ColorField('Display Color', validators=[Optional()])
    shipping_class_slug = StringField('Shipping Class Slug', validators=[Optional()])
    is_convertible_to_rental = BooleanField('Can this be converted to a rental if stock is low?')
    
    # --- Field for assigning to categories ---
    available_in_categories = QuerySelectMultipleField(
        'Available in Categories',
        query_factory=get_all_categories,
        get_label='name'
    )

    # --- FieldList for the flexible properties ---
    properties = FieldList(
        FormField(CommercialPropertyForm), 
        min_entries=0, 
        label="Additional Price Properties",
        validators=[validate_commercial_properties]
    )
    
    submit = SubmitField('Save Sale Grade')
    id = HiddenField() # For editing

    def validate_name(self, name):
        query = SaleGrade.query.filter(SaleGrade.name == name.data)
        if self.id.data:
            query = query.filter(SaleGrade.id != int(self.id.data))
        if query.first():
            raise ValidationError('A Sale Grade with this name already exists.')


class ShopCategoryForm(FlaskForm):
    """Form for creating and editing ShopCategory records."""
    name = StringField('Shop Category Name', validators=[DataRequired()])
    
    parent = QuerySelectField(
        'Parent Shop Category',
        query_factory=get_all_shop_categories,
        get_label='name',
        allow_blank=True,
        blank_text='-- None (Top-Level Category) --'
    )
    
    submit = SubmitField('Save Shop Category')
    id = HiddenField() # For tracking which category is being edited

    def validate_name(self, name):
        """Checks for name uniqueness, excluding the current record being edited."""
        query = ShopCategory.query.filter(ShopCategory.name == name.data)
        if self.id.data:
            query = query.filter(ShopCategory.id != self.id.data)
        if query.first():
            raise ValidationError('A shop category with this name already exists.')


class PublicProductForm(FlaskForm):
    """
    Form for creating and editing a PublicProduct, which represents a
    sellable entity in WooCommerce.
    """
    rental_grade = QuerySelectField(
        'Select Rental Grade',
        query_factory=get_available_rental_grades,
        get_label='name',
        allow_blank=True,
        blank_text='-- Or, select a Sale Grade --',
        validators=[Optional()]
    )

    sale_grade = QuerySelectField(
        'Select Sale Grade',
        query_factory=get_available_sale_grades,
        get_label='name',
        allow_blank=True,
        blank_text='-- Or, select a Rental Grade --',
        validators=[Optional()]
    ) 

    name = StringField(
        'Public Product Name', 
        validators=[DataRequired()], 
        description="e.g., 'Flat Cube - Standard Rental'. This is what the customer sees."
    )

    public_sku = StringField(
        'Public SKU Code',
        validators=[Optional()],
        description="e.g., 'FC-STD-RENT'. Leave blank to auto-generate."
    )
      
    
    # Hidden ID for editing
    id = HiddenField()
    submit = SubmitField('Save Public Product')

    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False
        
        # The grade selection rule should ONLY apply on creation, not on edit.
        # We can determine if we are creating by checking if the 'id' field is empty.
        is_creating = not self.id.data

        if is_creating:
            # Rule 1: Must select exactly one grade
            if self.rental_grade.data and self.sale_grade.data:
                self.rental_grade.errors.append("You can only select one grade (either Rental or Sale), not both.")
                return False
            if not self.rental_grade.data and not self.sale_grade.data:
                self.rental_grade.errors.append("You must select one grade for this public product.")
                return False
            
        return True


class NewOrderForm(FlaskForm):
    """
    Form for creating the parent CustomerOrder.
    """
    start_date = DateField('Rental Start Date', format='%Y-%m-%d', validators=[Optional()])
    end_date = DateField('End Date', format='%Y-%m-%d', validators=[Optional()])
    
    # New customer fields
    customer = QuerySelectField(
        'Existing Customer',
        query_factory=get_all_customers,
        get_label=lambda c: f"{c.first_name} {c.last_name} ({c.email})",
        allow_blank=True,
        blank_text='-- Or, create a new guest customer below --',
        validators=[Optional()]
    )
    # Fields for creating a new guest customer if one isn't selected
    guest_email = StringField('Guest Email', validators=[Optional(), Email()])
    guest_first_name = StringField('Guest First Name', validators=[Optional()])
    guest_last_name = StringField('Guest Last Name', validators=[Optional()])

    order_type = SelectField(
        'Order Type',
        choices=[('rental', 'Rental'), ('sale', 'Direct Sale')],
        validators=[DataRequired()]
    )
    submit = SubmitField('Create Order and Add Items')

    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False
        
        # Rule 1: If it's a rental, dates are required.
        if self.order_type.data == 'rental':
            if not self.start_date.data or not self.end_date.data:
                self.start_date.errors.append("Start and End dates are required for rental orders.")
                return False
            if self.start_date.data > self.end_date.data:
                self.start_date.errors.append("Start date cannot be after the end date.")
                return False

        # Rule 2: Must provide either an existing customer or new guest details.
        if not self.customer.data and not self.guest_email.data:
            self.customer.errors.append("You must select an existing customer or provide a guest email.")
            self.guest_email.errors.append("You must select an existing customer or provide a guest email.")
            return False
        
        # Rule 3: If providing guest details, first and last name are required.
        if self.guest_email.data and (not self.guest_first_name.data or not self.guest_last_name.data):
            self.guest_first_name.errors.append("First and last name are required for new guest customers.")
            return False
            
        return True


class DiscountForm(FlaskForm):
    """
    Form for applying a manual discount to a CustomerOrder.
    """
    discount_amount = DecimalField(
        'Discount Amount (€)',
        places=2,
        validators=[DataRequired(message="Please enter a discount amount.")]
    )
    discount_reason = StringField(
        'Reason for Discount',
        validators=[DataRequired(message="A reason for the discount is required.")],
        description="This will be saved for auditing purposes."
    )
    submit = SubmitField('Apply Discount')


class AddItemToOrderForm(FlaskForm):
    """
    Form for adding a new item (a PublicVariation) to a CustomerOrder.
    """
    # This will be dynamically populated by JS
    public_product = QuerySelectField(
        'Sales Product',
        query_factory=get_all_public_products,
        get_label='name',
        validators=[DataRequired()]
    )
    
    # This will also be dynamically populated by JS based on the above selection
    public_variation = SelectField('Variation (e.g., Color)', coerce=int, validators=[DataRequired()])
    
    quantity = IntegerField('Quantity', default=1, validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField('Add Item')


class AssignUnitsForm(FlaskForm):
    """A simple form with a CSRF token for the fulfillment page."""
    submit = SubmitField('Confirm Fulfillment')


class CustomerForm(FlaskForm):
    """Form for creating or editing core customer details."""
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    phone = StringField('Phone Number', validators=[Optional()])
    
    id = HiddenField()
    submit = SubmitField('Save Customer')

    def validate_email(self, email):
        query = Customer.query.filter(Customer.email == email.data)
        if self.id.data:
            query = query.filter(Customer.id != int(self.id.data))
        if query.first():
            raise ValidationError('This email address is already registered to another customer.')
        

class AddressForm(FlaskForm):
    """Form for managing a customer's address."""
    first_name = StringField('First Name', validators=[DataRequired()])
    last_name = StringField('Last Name', validators=[DataRequired()])
    address_line_1 = StringField('Address Line 1', validators=[DataRequired()])
    address_line_2 = StringField('Address Line 2 (Optional)', validators=[Optional()])
    postcode = StringField('Postcode', validators=[DataRequired()])
    city = StringField('City', validators=[DataRequired()])
    state = StringField('State/Province', validators=[Optional()])
    country = StringField('Country', validators=[DataRequired()])
    
    id = HiddenField()
    submit = SubmitField('Save Address')