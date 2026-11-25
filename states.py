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


class Checkout(StatesGroup):
    phone = State()
    name = State()
    delivery = State()
    address = State()
    comment = State()
    confirm = State()


class ChatWithManager(StatesGroup):
    active = State()


class ReplyToBuyer(StatesGroup):
    message = State()
