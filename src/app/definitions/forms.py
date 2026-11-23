# src/app/definitions/forms.py

import json
from flask_wtf import FlaskForm
from wtforms import Form, StringField, SubmitField, TextAreaField, SelectField, HiddenField, BooleanField, FieldList, FormField
from wtforms.validators import DataRequired, Optional, ValidationError
from wtforms_sqlalchemy.fields import QuerySelectField
from .models import DataType, OptionList, Attribute
from app.utility.form_helpers import get_data_types_for_list, get_all_option_lists, get_all_data_types
from app.utility.validation_logic import validate_value_by_datatype

class JsonObjectValidator:
    """
    Custom WTForms validator that checks two things:
    1. The field's text is syntactically valid JSON.
    2. The valid JSON is specifically an OBJECT (starts with {).
    """
    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        # The validator only runs if the field has data and is not empty.
        if field.data and field.data.strip():
            try:
                # Try to parse the string into a Python object
                parsed_data = json.loads(field.data)
            except json.JSONDecodeError:
                # If parsing fails, it's not valid JSON syntax.
                # Use a custom message or a default one.
                message = self.message or 'The text entered is not in a valid JSON format.'
                raise ValidationError(message)

            # If parsing succeeds, check if the resulting Python object is a dictionary.
            # A JSON object "{...}" becomes a Python dict.
            if not isinstance(parsed_data, dict):
                message = self.message or 'Validation rules must be a valid JSON object (e.g., {"key": "value"}).'
                raise ValidationError(message)


class DataTypeOptionForm(Form):
    value = StringField('Option Value', validators=[DataRequired()])


class DataTypeForm(FlaskForm):
    """
    Form for creating and editing a DataType.
    """
    name = StringField('Data Type Name', validators=[DataRequired()], description="e.g., Color, Positive Integer, Feature")
    
    display_type = SelectField(
        'Display Type', 
        choices=[
            ('text', 'Text (Single Line)'),
            ('textarea', 'Text Area (Multi-Line)'),
            ('boolean', 'Checkbox (True/False)'),
            ('integer', 'Integer Number'),
            ('float', 'Decimal Number'),
            ('color', 'Color Picker'),
            ('date', 'Date Picker'),
            ('datetime-local', 'Date & Time Picker'),
            ('email', 'Email'),
            ('url', 'URL'),
            ('tel', 'Telephone'),
            ('range', 'Range Slider'),
            ('month', 'Month Picker'),
            ('week', 'Week Picker'),
            ('time', 'Time Picker')
        ],
        validators=[DataRequired()]
    )

    validation_rules = TextAreaField(
        'Validation Rules (JSON format)', 
        validators=[Optional(), JsonObjectValidator()]
    )
    
    submit = SubmitField('Save Data Type')
    id = HiddenField()

    def validate_name(self, name):
        query = DataType.query.filter(DataType.name == name.data)
        if self.id.data:
            query = query.filter(DataType.id != self.id.data)
        if query.first():
            raise ValidationError('A Data Type with this name already exists.')




class OptionListItemForm(Form):
    id = HiddenField() # To track existing items vs. new ones
    value = StringField('Value')


class CreateOptionListForm(FlaskForm):
    name = StringField('List Name', validators=[DataRequired()])
    item_data_type = QuerySelectField('Data Type of Items', query_factory=get_data_types_for_list, get_label='name', validators=[DataRequired()])
    allow_multiple_selections = BooleanField('Allow multiple items to be selected?')
    
    display_hint = SelectField(
        'Display As',
        choices=[
            ('', '-- Select a Display Style --'),
            ('dropdown', 'Dropdown Menu'),
            ('radio', 'Radio Buttons')
        ],
        validators=[Optional()]
    )

    selection_rules = TextAreaField('Selection Rules (JSON)', validators=[Optional(), JsonObjectValidator()])
    items = FieldList(FormField(OptionListItemForm), min_entries=1)
    submit = SubmitField('Create Option List')

    def validate_name(self, name):
        if OptionList.query.filter_by(name=name.data).first():
            raise ValidationError('An Option List with this name already exists.')

    def validate(self, **kwargs):
        # First, run all the standard field-level validators.
        if not super().validate(**kwargs):
            return False

        # --- Rule 1: Single-choice lists MUST have a display hint. ---
        if not self.allow_multiple_selections.data and not self.display_hint.data:
            self.display_hint.errors.append("You must select a Display Style (Dropdown or Radio Buttons) for a single-choice list.")
            return False
        
        # --- Rule 2: Check the list items themselves. ---
        item_data_type = self.item_data_type.data
        
        has_at_least_one_value = False
        all_values_are_valid = True

        # Loop through all submitted items to find any potential errors.
        for item_form in self.items:
            value_str = item_form.value.data
            # Check only for items where the user actually typed something.
            if value_str and value_str.strip():
                has_at_least_one_value = True
                is_valid, error_message = validate_value_by_datatype(value_str, item_data_type)
                if not is_valid:
                    # An item has a value, but it's invalid.
                    item_form.value.errors.append(error_message)
                    all_values_are_valid = False # Mark the form as invalid but continue checking other items.
        
        if not has_at_least_one_value:
            # The user didn't provide ANY values.
            self.items[0].value.errors.append("You must provide at least one item value.")
            return False
        
        return all_values_are_valid


class EditOptionListForm(FlaskForm):
    """
    Form ONLY for editing an existing OptionList.
    """
    name = StringField('List Name', validators=[DataRequired()])
    display_hint = SelectField(
        'Display As',
        choices=[
            ('dropdown', 'Dropdown Menu'),
            ('radio', 'Radio Buttons')
        ],
        validators=[Optional()]
    )
    items = FieldList(FormField(OptionListItemForm), min_entries=0, label="List Items")
    submit = SubmitField('Update Option List')
    id = HiddenField()

    def __init__(self, *args, **kwargs):
        self.option_list = kwargs.pop('option_list', None)
        super(EditOptionListForm, self).__init__(*args, **kwargs)

    def validate_name(self, name):
        query = OptionList.query.filter(OptionList.name == name.data)
        if self.id.data:
            query = query.filter(OptionList.id != int(self.id.data))
        if query.first():
            raise ValidationError('An Option List with this name already exists.')
        
    def validate(self, **kwargs):
        if not super().validate(**kwargs):
            return False

        if not self.option_list:
            return False

        is_multi = self.option_list.allow_multiple_selections
        hint = self.display_hint.data
        if hint in ['dropdown', 'radio'] and is_multi:
            self.display_hint.errors.append("Dropdowns and Radio Buttons are for single-choice lists only.")
            return False
        
        return True
    

class AttributeForm(FlaskForm):
    name = StringField('Attribute Name', validators=[DataRequired()])
    sync_behavior = SelectField(
        'WooCommerce Sync Behavior',
        choices=[
            ('do_not_sync', 'Do Not Sync'),
            ('sync_as_global', 'Sync as Global Attribute (for info/filtering)'),
            ('sync_as_variation', 'Sync as Variation Attribute (e.g., Color/Size)')
        ],
        validators=[DataRequired()]
    )
    option_list = QuerySelectField('Use Predefined Option List', query_factory=get_all_option_lists, get_label='name', allow_blank=True, blank_text='-- Or, select a simple data type --', validators=[Optional()])
    data_type = QuerySelectField('Data Type', query_factory=get_all_data_types, get_label='name', allow_blank=True, blank_text='-- Select a Data Type --', validators=[Optional()])
    
    id = HiddenField()
    submit = SubmitField('Save Attribute')

    def __init__(self, *args, **kwargs):
        self.attribute_id = kwargs.get('obj').attribute_id if kwargs.get('obj') else None
        super(AttributeForm, self).__init__(*args, **kwargs)

    def validate_name(self, name):
        query = Attribute.query.filter(Attribute.name == name.data)
        if self.attribute_id:
            query = query.filter(Attribute.attribute_id != self.attribute_id)
        if query.first():
            raise ValidationError('An attribute with this name already exists.')

    def validate(self, **kwargs):
        if not super().validate(**kwargs): return False
        if not self.attribute_id: # Only on create
            if not self.option_list.data and not self.data_type.data:
                self.data_type.errors.append("You must select either an Option List or a Data Type.")
                return False
            if self.option_list.data and self.data_type.data:
                self.option_list.errors.append("You can select an Option List OR a Data Type, but not both.")
                return False

        return True