from __future__ import annotations

import csv
from io import StringIO

from validate.result import DataPollutionError


def decode_source(raw: bytes) -> tuple[str, str]:
    if not raw:
        raise DataPollutionError("source file is empty")
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise DataPollutionError("source file cannot be decoded as utf-8/cp950/big5")


def read_csv_rows(raw: bytes) -> tuple[list[list[str]], str]:
    text, encoding = decode_source(raw)
    if not text.strip():
        raise DataPollutionError("source file has no content")
    reader = csv.reader(StringIO(text))
    return [row for row in reader], encoding
