# app/utility/validation_logic.py
import re
from wtforms.validators import ValidationError

def validate_value_by_datatype(value_str: str, data_type_obj) -> tuple[bool, str | None]:
    """
    Validates a string value against the rules defined in a DataType object.

    Args:
        value_str (str): The input value from the form.
        data_type_obj: The SQLAlchemy DataType object containing the rules.

    Returns:
        tuple[bool, str | None]: A tuple containing:
            - bool: True if the value is valid, False otherwise.
            - str | None: An error message if invalid, otherwise None.
    """
    if not data_type_obj:
        return False, "Validation failed: No data type provided."
        
    if not value_str or not value_str.strip():
        return True, None # An empty value is considered valid by this helper

    rules = data_type_obj.validation_rules or {}
    display_type = data_type_obj.display_type

    # --- Rule Application Logic ---

    # A. Numeric Types
    if display_type in ['integer', 'float', 'range']:
        try:
            num_value = float(value_str)
            if 'min' in rules and num_value < rules['min']:
                return False, f"Value must be {rules['min']} or greater."
            if 'max' in rules and num_value > rules['max']:
                return False, f"Value must be {rules['max']} or less."
        except (ValueError, TypeError):
            return False, "Must be a valid number."

    # B. Text-based Types
    elif display_type in ['text', 'textarea', 'email', 'url', 'tel']:
        if 'min_length' in rules and len(value_str) < rules['min_length']:
            return False, f"Must be at least {rules['min_length']} characters long."
        if 'max_length' in rules and len(value_str) > rules['max_length']:
            return False, f"Must not exceed {rules['max_length']} characters."
        if 'regex' in rules and rules['regex']:
            try:
                if not re.match(rules['regex'], value_str):
                    return False, "Value does not match the required format."
            except re.error:
                return False, "Invalid validation pattern configured."

    # C. Date and Time Types
    elif display_type in ['date', 'datetime-local', 'month', 'week', 'time']:
        # This is a basic string comparison, which works for ISO formats (YYYY-MM-DD)
        # For more complex validation, you would convert to datetime objects.
        try:
            if 'min' in rules and value_str < rules['min']:
                return False, f"Date/Time must be on or after {rules['min']}."
            if 'max' in rules and value_str > rules['max']:
                return False, f"Date/Time must be on or before {rules['max']}."
        except TypeError:
             return False, "Invalid date/time format for comparison."
    
    # D. Color Type
    elif display_type == 'color':
        # A simple regex to check for a valid hex color format (#RRGGBB)
        if not re.match(r'^#[0-9a-fA-F]{6}$', value_str):
            return False, "Value must be a valid hex color code (e.g., #RRGGBB)."

    # If no rules specific to the display_type failed, the value is valid.
    return True, None


def validate_commercial_properties(form, field):
    """
    A custom WTForms validator for a FieldList of CommercialPropertyForm.
    - Ignores completely empty rows.
    - Enforces that a key is always present if a row is used.
    - Enforces that all values, if provided, are non-negative numbers.
    """
    for entry in field.entries:
        key = entry.form.key.data
        value = entry.form.value.data

        # Ignore completely empty rows
        if (not key or not key.strip()) and (not value or not value.strip()):
            continue

        # If a row is used, the key is mandatory
        if not key or not key.strip():
            entry.form.key.errors.append("Property Name is required.")
            # We raise this to make the parent form's validation fail
            raise ValidationError("An additional property is missing a name.")

        # If a value is provided, it must be a valid, non-negative number
        if value and value.strip():
            try:
                price_value = float(value)
                if price_value < 0:
                    entry.form.value.errors.append("Price cannot be negative.")
                    raise ValidationError("An additional price is negative.")
            except (ValueError, TypeError):
                entry.form.value.errors.append("Must be a valid number.")
                raise ValidationError("An additional price is not a valid number.")