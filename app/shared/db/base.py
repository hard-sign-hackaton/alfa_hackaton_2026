from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    """Shared metadata registry; module-owned models register on this base."""
    pass
