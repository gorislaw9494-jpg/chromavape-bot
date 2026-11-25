from aiogram.fsm.state import State, StatesGroup


class AddProduct(StatesGroup):
    name = State()
    price = State()
    description = State()
    photo = State()
    stock = State()
    confirm = State()


class EditProduct(StatesGroup):
    value = State()
