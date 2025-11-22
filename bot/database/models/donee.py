from __future__ import annotations

from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from bot.database.models.base import Base, big_int_pk

class Donee(Base):
    __tablename__ = "donees"

    id: Mapped[big_int_pk]

    donor: Mapped[int] = mapped_column(type_=BigInteger)



