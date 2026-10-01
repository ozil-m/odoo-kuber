def convert_datetime_to_timezone(datetime_field, from_timezone='UTC', to_timezone='Asia/Riyadh'):
    from pytz import timezone
    from datetime import datetime
    if datetime_field:
        # Convert datetime field to a datetime object
        if isinstance(datetime_field, str):
            datetime_field = datetime.strptime(datetime_field, '%Y-%m-%d %H:%M:%S')

        # Get the timezone object for the from_timezone
        from_tz = timezone(from_timezone)

        # Get the timezone object for the to_timezone
        to_tz = timezone(to_timezone)

        # Convert datetime object from one timezone to another
        converted_dt = datetime_field.replace(tzinfo=from_tz).astimezone(to_tz)

        return converted_dt
    else:
        return False


def translate_selection(record, field_name, force_value=None):
    value = force_value or record[field_name]
    return dict(record._fields[field_name]._description_selection(record.env)).get(value)
