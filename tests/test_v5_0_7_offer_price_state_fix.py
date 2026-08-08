import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.bot.handlers import provider_catalog
from app.bot.states import ProviderOfferStates


def run(coro):
    return asyncio.run(coro)


def test_every_active_callback_manager_call_declares_expected_state():
    """Prevent future runtime TypeError regressions in provider wizard callbacks."""
    source_path = Path(provider_catalog.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    missing = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "_active_callback_manager":
            continue
        keyword_names = {keyword.arg for keyword in node.keywords}
        if "expected_state" not in keyword_names:
            missing.append(node.lineno)
    assert missing == [], f"missing expected_state at lines: {missing}"


async def _price_accept_scenario(monkeypatch):
    captured = {}

    class FakeMessage:
        def __init__(self):
            self.answers = []
            self.keyboard_cleared = False

        async def answer(self, text, **kwargs):
            self.answers.append((text, kwargs))

        async def edit_reply_markup(self, **kwargs):
            self.keyboard_cleared = kwargs.get("reply_markup") is None

    class FakeCallback:
        def __init__(self):
            self.data = "provider:offer_price_accept:10000"
            self.message = FakeMessage()
            self.from_user = SimpleNamespace(id=123)
            self.answered = False

        async def answer(self, *args, **kwargs):
            self.answered = True

    async def fake_manager(callback, state, session, services, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(provider_id=1), {}

    async def fake_confirm(message, state, session, services, amount):
        captured["amount"] = amount

    monkeypatch.setattr(provider_catalog, "_active_callback_manager", fake_manager)
    monkeypatch.setattr(provider_catalog, "_confirm_provider_price", fake_confirm)

    callback = FakeCallback()
    await provider_catalog.offer_price_accept(
        callback,
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    assert callback.answered is True
    assert callback.message.keyboard_cleared is True
    assert captured["permission"] == "can_manage_offers"
    assert captured["expected_state"] == ProviderOfferStates.price.state
    assert captured["amount"] == 10000


def test_offer_price_accept_passes_state_and_continues(monkeypatch):
    run(_price_accept_scenario(monkeypatch))


async def _inventory_label_scenario(monkeypatch):
    captured = {}

    class FakeState:
        async def update_data(self, **kwargs):
            captured.setdefault("updated", {}).update(kwargs)

        async def set_state(self, value):
            captured["state"] = value

    class FakeMessage:
        def __init__(self):
            self.text = "حساب تجريبي"
            self.answers = []

        async def answer(self, text, **kwargs):
            self.answers.append((text, kwargs))

    async def fake_manager(message, state, session, services, **kwargs):
        return SimpleNamespace(provider_id=1), {
            "item_kind": "account",
            "inventory_simple_account": True,
        }

    monkeypatch.setattr(provider_catalog, "_active_manager", fake_manager)
    state = FakeState()
    message = FakeMessage()
    await provider_catalog.inventory_label(
        message,
        state,
        SimpleNamespace(),
        SimpleNamespace(),
    )

    assert captured["updated"]["item_label"] == "حساب تجريبي"
    assert captured["state"] == provider_catalog.ProviderInventoryStates.email
    assert "اكتب إيميل الحساب" in message.answers[-1][0]


def test_simple_inventory_flow_moves_from_label_to_email(monkeypatch):
    run(_inventory_label_scenario(monkeypatch))
