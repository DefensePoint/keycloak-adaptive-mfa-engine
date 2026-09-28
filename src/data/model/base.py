from datetime import datetime
from sqlalchemy.ext.declarative import declarative_base


def serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()

    return value


class BaseModel:
    def to_dict(self):
        return {
            column.name: serialize(getattr(self, column.name))
            for column in self.__table__.columns
        }


Base = declarative_base(cls=BaseModel)
