"""The FareQuote contract every adapter must emit — see docs/03-architecture.md
"Adapter isolation": nothing downstream of PARSE knows which source a quote
came from except as a metadata field on this object.

Product specification (docs/02-methodology.md §1): one adult, one-way, economy,
non-stop, lowest available total fare, directional route, specific departure
date, specific carrier, recorded collection timestamp.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import pandera.pandas as pa
from pandera.typing import Series
from pydantic import BaseModel, Field, model_validator

ObservationStatus = Literal["observed", "no_service", "collection_failed", "imputed"]
AdvancePurchaseDays = Literal[1, 7, 15, 30]


class FareQuote(BaseModel):
    """One row: one carrier, one route, one departure date, one advance-purchase
    window, one collection timestamp. Emitted by PARSE, consumed by NORMALISE.
    """

    source: str
    carrier: str
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    departure_date: date
    collection_ts: datetime
    advance_purchase_days: AdvancePurchaseDays
    fare_class: str | None = None
    is_nonstop: bool = True

    base_fare: Decimal | None = None
    carrier_charges: Decimal | None = None
    udf: Decimal | None = None
    asf: Decimal | None = None
    rcs_levy: Decimal | None = None
    gst: Decimal | None = None
    convenience_fee: Decimal | None = None
    total_fare: Decimal | None = None

    observation_status: ObservationStatus
    raw_payload_hash: str | None = None

    @model_validator(mode="after")
    def _consistency(self) -> "FareQuote":
        if self.observation_status == "observed":
            if self.total_fare is None:
                raise ValueError("observed quotes must carry a total_fare")
            if self.raw_payload_hash is None:
                raise ValueError("observed quotes must carry raw_payload_hash (audit trail)")
        if self.total_fare is not None and self.total_fare < 0:
            raise ValueError("total_fare cannot be negative")
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        return self


# --- Pandera schema for the same contract, applied to batches (DataFrames)
#     at the PARSE -> NORMALISE and NORMALISE -> CLEAN boundaries. ---

class FareQuoteBatchSchema(pa.DataFrameModel):
    source: Series[str]
    carrier: Series[str]
    origin: Series[str] = pa.Field(str_length={"min_value": 3, "max_value": 3})
    destination: Series[str] = pa.Field(str_length={"min_value": 3, "max_value": 3})
    departure_date: Series[pa.typing.pandas.DateTime]
    collection_ts: Series[pa.typing.pandas.DateTime]
    advance_purchase_days: Series[int] = pa.Field(isin=[1, 7, 15, 30])
    total_fare: Series[float] = pa.Field(ge=0, nullable=True)
    observation_status: Series[str] = pa.Field(
        isin=["observed", "no_service", "collection_failed", "imputed"]
    )
    raw_payload_hash: Series[str] = pa.Field(nullable=True)

    class Config:
        coerce = True
