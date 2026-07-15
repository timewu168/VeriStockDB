from hashlib import sha256


def disposition_notice_id(
    market: str,
    stock_id: str,
    announcement_date: str,
    start_date: str,
    end_date: str,
) -> str:
    identity = "|".join((market, stock_id, announcement_date, start_date, end_date))
    return f"disp_{sha256(identity.encode('utf-8')).hexdigest()[:24]}"
