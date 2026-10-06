from food_order.bot.keyboards import build_choice_keyboard, remove_choice_keyboard


def test_choice_keyboard_labels() -> None:
    markup = build_choice_keyboard(["Шаурма классическая", "Кола"])
    buttons = [row[0] for row in markup.keyboard]
    assert [button.text for button in buttons] == ["Шаурма классическая", "Кола"]
    assert markup.resize_keyboard is True
    assert markup.one_time_keyboard is True
    assert all(not getattr(button, "callback_data", None) for button in buttons)


def test_remove_choice_keyboard() -> None:
    assert remove_choice_keyboard().remove_keyboard is True
