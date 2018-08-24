import datetime

from peewee import *

db = SqliteDatabase('places.db', pragmas={'foreign_keys': 1})


class BaseModel(Model):
    class Meta:
        database = db


class User(BaseModel):
    user_id = IntegerField(unique=True)


class Place(BaseModel):
    user = ForeignKeyField(User, backref='places', on_delete='CASCADE')
    name = CharField(max_length=100)
    photo = BlobField()
    location = CharField()
    upload_date = DateTimeField(default=datetime.datetime.now)


if __name__ == '__main__':
    db.create_tables([User, Place])
