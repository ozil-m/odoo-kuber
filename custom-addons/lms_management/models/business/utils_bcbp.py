
from dataclasses import dataclass
from datetime import date, timedelta

@dataclass
class BCBPData:
    format_code: str = ""
    number_of_legs: int = 1
    passenger_name: str = ""
    passenger_name_raw: str = ""  # LAST/FIRST[MIDDLE] as-is from barcode
    pnr: str = ""
    from_airport: str = ""
    to_airport: str = ""
    operating_carrier: str = ""
    flight_number: str = ""
    flight_date_julian: str = ""
    compartment_code: str = ""
    seat_number: str = ""
    check_in_sequence: str = ""
    passenger_status: str = ""
    ticket_number: str = ""
    fqtv: str = ""

def convert_julian_to_date(julian_str: str):
    """ Convert Julian date string (001-366) to a date object in the current year."""
    try:
        day = int(julian_str or "0")
        if not (1 <= day <= 366):
            return None
        year = date.today().year
        return date(year, 1, 1) + timedelta(days=day - 1)
    except Exception:
        return None

def parse_bcbp(bcbp: str) -> BCBPData:
    """ Parse IATA BCBP (Bar Coded Boarding Pass) string into structured data."""
    s = bcbp or ""
    if len(s) < 60:
        name_raw = (s[2:22] or "").strip()
        return BCBPData(passenger_name=name_raw.replace("/", " "), passenger_name_raw=name_raw, pnr=(s[22:29] or "").strip())
    try:
        format_code = s[0]
        number_of_legs = int(s[1] or "1")
        name_raw = (s[2:22] or "").strip()
        name_clean = name_raw.replace("/", " ")
        pnr = (s[22:29] or "").strip()
        from_airport = (s[30:33] or "").strip().upper()
        to_airport = (s[33:36] or "").strip().upper()
        operating_carrier = (s[36:39] or "").strip().upper()
        flight_number = (s[39:44] or "").strip()
        date_julian = (s[44:47] or "").strip()
        compartment = (s[47] or "").strip().upper()
        seat = (s[48:52] or "").strip().upper()
        seq = (s[52:56] or "").strip()
        status = (s[57] or "").strip()
        ticket = (s[90:103] or "").strip()
        fqtv = (s[111:127] or "").strip()

        return BCBPData(
            format_code=format_code,
            number_of_legs=number_of_legs,
            passenger_name=name_clean,
            passenger_name_raw=name_raw,
            pnr=pnr,
            from_airport=from_airport,
            to_airport=to_airport,
            operating_carrier=operating_carrier,
            flight_number=flight_number,
            flight_date_julian=date_julian,
            compartment_code=compartment,
            seat_number=seat,
            check_in_sequence=seq,
            passenger_status=status,
            ticket_number=ticket,
            fqtv=fqtv,
        )
    except Exception:
        name_raw = (s[2:22] or "").strip()
        return BCBPData(passenger_name=name_raw.replace("/", " "), passenger_name_raw=name_raw, pnr=(s[22:29] or "").strip())
