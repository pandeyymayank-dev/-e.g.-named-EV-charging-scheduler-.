"""
models.py

SQLAlchemy models for EV Charging Scheduler.
Tables:
  - stations(id, name, capacity_kw)
  - requests(id, station_id, label, arrival, deadline, hours_needed, power_kw)
"""
from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class Station(Base):
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, default="Main Station", nullable=False)
    capacity_kw = Column(Float, default=20.0, nullable=False)

    requests = relationship(
        "Request",
        back_populates="station",
        cascade="all, delete-orphan",
    )


class Request(Base):
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id", ondelete="CASCADE"), nullable=False)
    label = Column(String, nullable=False)
    arrival = Column(Float, nullable=False)
    deadline = Column(Float, nullable=False)
    hours_needed = Column(Float, nullable=False)
    power_kw = Column(Float, nullable=False)

    station = relationship("Station", back_populates="requests")
