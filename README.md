<h1 align="center">
  Daisy Admin for Starlette/FastAPI
</h1>

---


**Documentation**: [https://docs.bhuwanpandey.com.np](https://docs.bhuwanpandey.com.np)

**Source Code**: [https://github.com/BhuwanPandey/fastdaisy-admin](https://github.com/BhuwanPandey/fastdaisy-admin)


---

Fastdaisy-admin is an admin panel with DaisyUI for managing SQLAlchemy models. It offers a dashboard experience similar to `Django Admin` and combining the design of [**django-daisy**](https://hypy13.github.io/django-daisy-docs) with the same functionality of [**Sqladmin**](https://github.com/aminalaee/sqladmin).


## Features

- [**SQLAlchemy**](https://github.com/sqlalchemy/sqlalchemy) sync/async Core Database ORM

- [**Starlette**](https://github.com/Kludex/starlette) sync/async Backend Server

- [**WTForms**](https://github.com/pallets-eco/wtforms) Form Building

- [**SQLModel**](https://github.com/fastapi/sqlmodel) sync/async Database ORM

- [**DaisyUI**](https://github.com/saadeghi/daisyui) Admin UI

- **Django-Admin** Similar Features



## Installation

Install using `pip`:

```bash
pip install fastdaisy-admin
```

Install using [uv](https://docs.astral.sh/uv/):

```bash
uv add fastdaisy-admin
```

## Quickstart


```python
import contextlib
from sqlalchemy import Column, Integer, String, Text, create_engine, ForeignKey
from sqlalchemy.orm import declarative_base,relationship,sessionmaker


Base = declarative_base()
engine = create_engine(
    "sqlite:///example.db",
    connect_args={"check_same_thread": False},
)
Session = sessionmaker(bind=engine)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    books = relationship("Book", back_populates="author", cascade="all, delete-orphan")


class Book(Base):
    __tablename__ = 'books'

    id = Column(Integer, primary_key=True)
    title = Column(String)
    description = Column(Text)
    author_id = Column(Integer, ForeignKey('users.id'))
    author = relationship("User", back_populates="books")


@contextlib.asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine) # create teables 
    yield

secret_key="secret_key"

```

With `FastAPI`:

```python
from fastapi import FastAPI
from fastdaisy_admin import Admin, ModelView


app = FastAPI(lifespan=lifespan)
admin = Admin(
    app, 
    secret_key, 
    engine
)


class UserAdmin(ModelView):
    model=User
    column_list = [User.id, User.name]


admin.add_view(UserAdmin)
```

With `Starlette`:

```python
from fastdaisy_admin import Admin, ModelView
from starlette.applications import Starlette


app = Starlette(lifespan=lifespan)
admin = Admin(
    app, 
    secret_key, 
    engine
)


class BookAdmin(ModelView):
    model=Book
    column_list = ['id', Book.title]


admin.add_view(BookAdmin)
```

Now visiting `/admin` on your browser you can see the `Admin` dashboard.


### To active authentication
```python
from fastdaisy_admin.auth.models import BaseUser

#override BaseUser [optional]
class User(Base, BaseUser):
    __tablename__ = "users"
    books = relationship("Book", back_populates="author", cascade="all, delete-orphan")

class Book(Base):
    __tablename__ = 'books'
    ...

admin = Admin(
    app, 
    secret_key, 
    engine,
    authentication=True,
    auth_model=User
)

```

### create superuser with
```bash

fastdaisy-admin createsuperuser
```


> [!WARNING]
> 
> This project is still under active development.  
> Current test coverage is around **91%**, and work is ongoing to reach **100%**.
