"""Seed historical schemas without asking today's ORM for newer columns."""
from sqlalchemy import MetaData, Table
from app.extensions import db


def insert(model, **values):
    table = Table(model.__tablename__, MetaData(), autoload_with=db.engine)
    for column in model.__table__.columns:
        if column.name not in table.c or column.name in values or column.default is None:
            continue
        default = column.default
        values[column.name] = default.arg(None) if default.is_callable else default.arg
    values = {key: value for key, value in values.items() if key in table.c}
    return db.session.execute(table.insert().values(**values).returning(table.c.id)).scalar_one()
