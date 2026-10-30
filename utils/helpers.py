
from datetime import date


def parse_positive_number(value, field_name, allow_zero=False):
    """Convert a form value to a non-negative or positive float."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")

    if number < 0 or (number == 0 and not allow_zero):
        if allow_zero:
            raise ValueError(f"{field_name} cannot be negative.")
        raise ValueError(f"{field_name} must be greater than zero.")

    return number


def parse_integer_range(value, field_name, minimum, maximum):
    """Convert a form value to an integer inside an allowed range."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a whole number.")

    if not minimum <= number <= maximum:
        raise ValueError(
            f"{field_name} must be between {minimum} and {maximum}."
        )

    return number


def validate_date_range(start_date, end_date):
    """Validate ISO-format dates and ensure the end is not before the start."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError):
        raise ValueError("Enter valid start and end dates.")

    if end < start:
        raise ValueError("The end date cannot be before the start date.")

    return start, end
