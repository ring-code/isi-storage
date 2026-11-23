# /src/app/products/forms.py

from flask_wtf import FlaskForm
from wtforms import MultipleFileField, StringField, SubmitField, TextAreaField, SelectField, IntegerField, HiddenField, BooleanField, DecimalField, SelectMultipleField
from wtforms.validators import DataRequired, ValidationError, Optional, NumberRange

from app.products.models import Product, Category, SpecificationDefinition
from app.sales.models import RentalGrade, SaleGrade
from app.utility.specification_logic import get_concrete_skus
from app.utility.form_helpers import (
    get_all_products,
    get_all_spaces,
    get_all_categories,
    get_all_data_types,
    get_all_option_lists,
    get_all_damage_templates,
    get_all_sale_grades,
    get_all_rental_grades
)
from wtforms_sqlalchemy.fields import QuerySelectField


class ProductForm(FlaskForm):
    """Form for creating and editing Product SKUs."""
    name = StringField('Product SKU Name', validators=[DataRequired()])
    description_txt = TextAreaField('Description', validators=[Optional()])
    
    serial_number_prefix = StringField(
        'Serial Number Prefix',
        validators=[DataRequired()],
        description="A unique counter will be added for each unit."
    )

    standard_production_cost = DecimalField(
        'Standard Production Cost (€)',
        validators=[Optional(), NumberRange(min=0, message="Cost cannot be negative.")],
        places=2, # Ensure two decimal places
        rounding=None # Use default rounding
    )

    category = QuerySelectField(
        'Category',
        query_factory=get_all_categories,
        get_label='name',
        allow_blank=True,
        blank_text='-- Select a Category --',
        validators=[DataRequired(message="You must select a category for this SKU.")]
    )

    damage_template = QuerySelectField(
        'Damage Model',
        query_factory=get_all_damage_templates,
        get_label='name',
        allow_blank=True,
        blank_text='-- No Damage Model (Text-only) --',
        validators=[Optional()]
    )

    shop_categories = SelectMultipleField(
        'Public Shop Categories',
        coerce=int, # This is important! It ensures submitted values are integers.
        description="Select the public-facing categories this SKU should appear in."
    )
    
    photos = MultipleFileField('Photos', validators=[Optional()])

    # --- Final Submit ---
    submit = SubmitField('Create Product SKU')
    id = HiddenField() 

    def validate_name(self, name):
        """
        Ensures the product SKU name is unique across the entire system.
        """
        query = Product.query.filter(Product.name == name.data)
        if self.id.data:
            query = query.filter(Product.product_id != int(self.id.data))
        if query.first():
            raise ValidationError('A Product SKU with this name already exists.')
    
    
class CategoryForm(FlaskForm):
    name = StringField('Category Name', validators=[DataRequired()])
    parent_id = QuerySelectField(
        'Parent Category',
        query_factory=get_all_categories,
        get_label='name',
        allow_blank=True,
        blank_text='-- None (Top-Level Category) --'
    )
    submit = SubmitField('Create Category')
    id = HiddenField()

    def validate_name(self, name):
        existing = Category.query.filter(Category.name == name.data).first()
        if existing and (not self.id.data or int(self.id.data) != existing.category_id):
            raise ValidationError('A category with this name already exists.')


class SpecificationForm(FlaskForm):
    """
    Form for creating and editing synced and unsynced
    specification definitions and their overrides.
    """
    # --- Fields for UNSYNCED specs ---
    name = StringField('Specification Name', validators=[Optional()])
    option_list = QuerySelectField(
        'Use Predefined Option List',
        query_factory=get_all_option_lists,
        get_label='name',
        allow_blank=True,
        blank_text='-- Or, select a simple data type below --',
        validators=[Optional()]
    )
    data_type = QuerySelectField(
        'Data Type',
        query_factory=get_all_data_types,
        get_label='name',
        allow_blank=True,
        blank_text='-- Select a Data Type --',
        validators=[Optional()]
    )

    # --- Field for SYNCED specs ---
    linked_attribute = QuerySelectField(
        'Sync to Global Attribute',
        get_label='name',
        allow_blank=True,
        blank_text='-- Do not sync (create as Unsynced) --',
        validators=[Optional()]
    )

    # --- Inheritance Rules ---
    is_inheritable = BooleanField('Children CAN inherit this specification', default=True)
    requires_implementation = BooleanField('Children HAVE TO inherit this (Enforced)', default=False)
    forbid_override = BooleanField('The value is FINAL (cannot be changed by children)', default=False)

    # --- Hidden fields for context ---
    id = HiddenField() # For editing a spec def
    category_id = HiddenField(validators=[DataRequired()])   
    
    submit = SubmitField('Save Specification')

    def __init__(self, *args, **kwargs):
        self.category = kwargs.pop('category', None)
        self.spec_def = kwargs.pop('spec_def', None)
        self.is_edit_mode = bool(self.spec_def)
        self.is_synced_on_load = self.is_edit_mode and bool(self.spec_def.attribute)
        self.downstream_lock_failed = False
        super(SpecificationForm, self).__init__(*args, **kwargs)

    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False
        
        is_base_edit = self.is_edit_mode and (self.spec_def.category_id == self.category.category_id)

        if is_base_edit and self.category.children:
            # Check if any rule was "changed" (due to being disabled in the form)
            if self.is_inheritable.data != self.spec_def.is_inheritable or \
               self.requires_implementation.data != self.spec_def.requires_implementation or \
               self.forbid_override.data != self.spec_def.forbid_override:
                
                self.downstream_lock_failed = True
                
                # Don't add a form error, just return True. The route will handle it.
                # This allows other validations to proceed.
                pass # We will handle the "real" failure in the route.

        is_creating_new = not self.is_edit_mode
        is_synced_submission = bool(self.linked_attribute.data)

        # 1. VALIDATION FOR "CREATE" MODE
        if is_creating_new:
            if is_synced_submission:
                # No other validation needed; sync attribute provides everything.
                pass
            else: # Creating a new UNSYNCED spec
                # Rule: Must have a name.
                if not self.name.data or not self.name.data.strip():
                    self.name.errors.append("Specification Name is required for unsynced specs.")
                    return False
                
                # Rule: Name must be unique within this category.
                query = SpecificationDefinition.query.filter_by(category_id=int(self.category_id.data), name=self.name.data.strip()).first()
                if query:
                    self.name.errors.append('A spec with this name already exists in this category.')
                    return False

                # Rule: Must have a data source.
                if not self.option_list.data and not self.data_type.data:
                    self.data_type.errors.append("For an unsynced spec, you must select either an Option List or a Data Type.")
                    return False

        # 2. VALIDATION FOR "EDIT" MODE (on an unsynced spec)
        elif not self.is_synced_on_load:
            # Rule: Must have a name.
            if not self.name.data or not self.name.data.strip():
                self.name.errors.append("Specification Name is required.")
                return False
            
            # Rule: Name must be unique (excluding itself).
            query = SpecificationDefinition.query.filter(
                SpecificationDefinition.name == self.name.data.strip(),
                SpecificationDefinition.id != int(self.id.data)
            ).first()
            if query:
                self.name.errors.append('Another specification with this name already exists.')
                return False

        # 3. UNIVERSAL VALIDATION for inheritance logic
        # Rule: You cannot make a spec "Enforced" or "Final" if it's not inheritable.
        if not self.is_inheritable.data and (self.requires_implementation.data or self.forbid_override.data):
            self.is_inheritable.errors.append('Cannot be Enforced or Final if it is not inheritable.')
            return False
            
        # Rule: You cannot make a spec "Final" if it is not also "Enforced".
        if self.forbid_override.data and not self.requires_implementation.data:
            self.requires_implementation.errors.append('Must be Enforced if it is also Final.')
            return False


        return True


class BatchCreateUnitForm(FlaskForm):
    """
    A dedicated form for the batch creation of multiple, identical product units.
    """
    product_id = QuerySelectField(
        'Parent Product SKU',
        query_factory=get_concrete_skus,
        get_label='name',
        allow_blank=True,
        blank_text='-- Select a Concrete SKU --',
        validators=[DataRequired(message="You must select a parent SKU.")]
    )
    
    # 1. The Prefix (read-only in the template)
    serial_number_prefix = StringField('Serial Number Prefix', validators=[Optional()])
    
    # 2. The Optional Suffix
    serial_number_suffix = StringField('Additional Identifier (Optional)', validators=[Optional()])

    # 3. The Starting Number
    serial_start_number = IntegerField(
        'Starting Number', 
        default=1, 
        validators=[DataRequired(), NumberRange(min=1, message="Starting number must be 1 or greater.")]
    )
    
    quantity = IntegerField(
        'Quantity to Create', 
        default=1, 
        validators=[DataRequired(), NumberRange(min=1)],
        description="Units will be created sequentially from the starting number."
    )

    actual_production_cost = DecimalField(
        'Actual Production Cost (per Unit)',
        validators=[Optional(), NumberRange(min=0, message="Cost cannot be negative.")],
        places=2
    )
    
    # --- Commercial Grade and other fields ---
    rental_grade_id = QuerySelectField('Rental Grade', query_factory=get_all_rental_grades, get_label='name', allow_blank=True, validators=[Optional()])
    sale_grade_id = QuerySelectField('Sale Grade', query_factory=get_all_sale_grades, get_label='name', allow_blank=True, validators=[Optional()])
    space = QuerySelectField('Initial Storage Space', query_factory=get_all_spaces, get_label='name', allow_blank=True)
    
    submit = SubmitField('Create Units')

    def validate(self, **kwargs):
        """
        Custom validation to ensure either a rental or sale grade is chosen.
        """
        if not super().validate(**kwargs):
            return False
        
        if self.rental_grade_id.data and self.sale_grade_id.data:
            self.rental_grade_id.errors.append("A unit can only have one grade. Choose either Rental or Sale.")
            return False

        return True


class CreateSingleUnitForm(FlaskForm):
    """
    A dedicated form for creating a single, potentially unique product unit.
    This workflow is used for SKUs with abstract specifications that must
    be fulfilled at the unit level.
    """
    product_id = QuerySelectField(
        'Parent Product SKU',
        # It's important that this factory shows ALL products, not just concrete ones.
        query_factory=get_all_products,
        get_label='name',
        allow_blank=True,
        blank_text='-- Select a SKU to load its details --',
        validators=[DataRequired(message="You must select a parent SKU.")]
    )
    
    # --- Serial Number ---
    serial_number_prefix = StringField('Serial Number Prefix', validators=[Optional()])
    serial_number_suffix = StringField('Additional Identifier (Optional)', validators=[Optional()])
    serial_number_value = StringField('Unique Serial Number/Value', validators=[DataRequired()])

    # --- Production Cost ---
    actual_production_cost = DecimalField(
        'Actual Production Cost',
        validators=[Optional(), NumberRange(min=0, message="Cost cannot be negative.")],
        places=2
    )
    
    # --- Commercial Grade ---
    rental_grade_id = QuerySelectField('Rental Grade', query_factory=get_all_rental_grades, get_label='name', allow_blank=True, validators=[Optional()])
    sale_grade_id = QuerySelectField('Sale Grade', query_factory=get_all_sale_grades, get_label='name', allow_blank=True, validators=[Optional()])

    # --- Other Fields ---
    space = QuerySelectField('Initial Storage Space', query_factory=get_all_spaces, get_label='name', allow_blank=True)
    description = TextAreaField('Unit-Specific Description (Optional)', validators=[Optional()])
    
    submit = SubmitField('Create Unit')

    def validate(self, **kwargs):
        """
        Custom validation to ensure either a rental or sale grade is chosen.
        """
        if not super().validate(**kwargs):
            return False
        
        if self.rental_grade_id.data and self.sale_grade_id.data:
            self.rental_grade_id.errors.append("A unit can only have one grade. Choose either Rental or Sale.")
            return False

        return True


def get_unit_conditions():
    # In the future, this could be read from a database table
    return [
        ('available', 'Available'),
        ('rented_out', 'Rented Out'),
        ('in_maintenance', 'In Maintenance'),
        ('sold', 'Sold'),
        ('decommissioned', 'Decommissioned')
    ]


class EditUnitForm(FlaskForm):
    """
    A comprehensive form for editing all core properties of a single ProductUnit.
    """
    serial_number = StringField('Serial Number', render_kw={'readonly': True})
    
    condition = SelectField(
        'Condition',
        choices=get_unit_conditions,
        validators=[DataRequired()]
    )
    
    rental_grade_id = QuerySelectField(
        'Rental Grade',
        get_label='name',
        get_pk=lambda obj: obj.id,
        allow_blank=True,
        blank_text='-- Not a Rental Unit --',
        validators=[Optional()]
    )
    sale_grade_id = QuerySelectField(
        'Sale Grade',
        get_label='name',
        get_pk=lambda obj: obj.id,
        allow_blank=True,
        blank_text='-- Not a Sale Unit --',
        validators=[Optional()]
    )
    
    space = QuerySelectField(
        'Storage Space',
        query_factory=get_all_spaces,
        get_label='name',
        allow_blank=True,
        blank_text='-- No Assigned Space --'
    )
    actual_production_cost = DecimalField(
        'Actual Production Cost (€)',
        validators=[Optional(), NumberRange(min=0)],
        places=2
    )
    description = TextAreaField('Unit-Specific Description', validators=[Optional()])

    submit = SubmitField('Update Core Details')

    def __init__(self, *args, **kwargs):
        super(EditUnitForm, self).__init__(*args, **kwargs)
        
        # Get the product context passed from the route
        product = kwargs.get('product')
        
        if product:
            # Prepare the lazy-loading query objects
            available_rental_grades_query = RentalGrade.query.filter(RentalGrade.available_in_categories.any(category_id=product.category_id))
            available_sale_grades_query = SaleGrade.query.filter(SaleGrade.available_in_categories.any(category_id=product.category_id))
            
            # Assign a callable (lambda) to the query_factory
            self.rental_grade_id.query_factory = lambda: available_rental_grades_query.all()
            self.sale_grade_id.query_factory = lambda: available_sale_grades_query.all()

    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False
        
        if self.rental_grade_id.data and self.sale_grade_id.data:
            self.rental_grade_id.errors.append("A unit can only have one grade. Choose either Rental or Sale.")
            return False

        return True