from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove


def build_choice_keyboard(choices: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label)] for label in choices],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def remove_choice_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
