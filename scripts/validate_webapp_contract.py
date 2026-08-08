from __future__ import annotations

"""Offline contract gate for CampusPass Telegram Web Apps.

The gate is intentionally stdlib-only so Render can catch security, validation,
back-navigation, and business-flow regressions before importing aiogram/FastAPI.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"WEBAPP CONTRACT VALIDATION FAILED: {message}")


def text(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        fail(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def require(source: str, marker: str, *, where: str) -> None:
    if marker not in source:
        fail(f"{where} is missing {marker!r}")


def reject(source: str, marker: str, *, where: str) -> None:
    if marker in source:
        fail(f"{where} contains forbidden {marker!r}")


def validate_templates() -> None:
    templates = {
        "profile": text("app/api/templates/student_profile.html"),
        "provider": text("app/api/templates/admin_provider.html"),
        "offer": text("app/api/templates/provider_offer.html"),
    }
    for name, source in templates.items():
        reject(source, ".sendData(", where=f"{name} template")
        require(source, "X-Telegram-Init-Data", where=f"{name} template")
        require(source, "fetch(", where=f"{name} template")
        require(source, "tg.BackButton", where=f"{name} template")
        require(source, "next.disabled", where=f"{name} template")
        require(source, 'spellcheck="true"', where=f"{name} template")
    require(templates["profile"], "/api/webapp/student/profile", where="profile template")

    provider = templates["provider"]
    require(provider, "/api/webapp/admin/provider", where="provider template")
    require(provider, "localStorage", where="provider draft persistence")
    require(provider, "staff_identifiers", where="provider staff workflow")
    require(provider, "service_fee_iqd", where="provider service fee")
    require(provider, "logoFile", where="optional provider logo")
    require(provider, "goBack", where="provider one-step back")

    offer = templates["offer"]
    require(offer, "/api/webapp/provider/offers", where="offer template")
    require(offer, "localStorage", where="offer durable browser draft")
    require(offer, "history", where="branch-aware back navigation")
    require(offer, "goBack", where="offer one-step back")
    require(offer, "/copy-suggestion", where="offer AI copywriter")
    require(offer, "fulfillment_kind", where="offer fulfillment intent")
    require(offer, "account_type", where="offer account model")
    require(offer, "warranty_enabled", where="offer warranty")
    require(offer, "guide_text", where="offer activation guide")
    require(offer, "هل تقصد", where="Iraqi smart-price confirmation")



def _pydantic_model_fields(module_source: str, class_name: str) -> tuple[set[str], set[str]]:
    """Return (all_fields, syntactically_required_fields) for a BaseModel class.

    This is intentionally AST-only so the build gate can detect API/verifier drift
    before importing FastAPI/aiogram. A Field(...) declaration without an explicit
    default is treated as required.
    """
    tree = ast.parse(module_source)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        all_fields: set[str] = set()
        required: set[str] = set()
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            name = item.target.id
            all_fields.add(name)
            value = item.value
            if value is None:
                required.add(name)
                continue
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "Field":
                has_default_keyword = any(k.arg in {"default", "default_factory"} for k in value.keywords)
                has_positional_default = bool(value.args)
                if not has_default_keyword and not has_positional_default:
                    required.add(name)
        return all_fields, required
    fail(f"FastAPI server is missing model {class_name!r}")
    raise AssertionError


def _call_keyword_names(module_source: str, call_name: str) -> set[str]:
    tree = ast.parse(module_source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == call_name:
            return {kw.arg for kw in node.keywords if kw.arg is not None}
    fail(f"render verifier is missing {call_name}(...) contract sample")
    raise AssertionError


def validate_runtime_contract_samples() -> None:
    """Keep Render runtime samples synchronized with the live Pydantic models.

    This catches exactly the class of regression where the API model gains/renames a
    required field but render_build_verify.py still constructs the old request shape.
    """
    server = text("app/api/server.py")
    verifier = text("scripts/render_build_verify.py")
    all_fields, required = _pydantic_model_fields(server, "OfferCreateRequest")
    supplied = _call_keyword_names(verifier, "OfferCreateRequest")

    # warranty_enabled is semantically required by the model_validator even though
    # its transport type is Optional so the UI can represent "not answered yet".
    semantic_required = {"warranty_enabled"}
    missing = sorted((required | semantic_required) - supplied)
    unknown = sorted(supplied - all_fields)
    if missing:
        fail(f"render OfferCreateRequest sample is missing required fields: {', '.join(missing)}")
    if unknown:
        fail(f"render OfferCreateRequest sample contains stale/unknown fields: {', '.join(unknown)}")


def validate_server_contract() -> None:
    source = text("app/api/server.py")
    for route in (
        '/webapp/student/profile',
        '/api/webapp/student/profile',
        '/webapp/admin/provider',
        '/api/webapp/admin/provider',
        '/api/webapp/admin/provider/{provider_id}/logo',
        '/webapp/provider/offer',
        '/api/webapp/provider/offer/bootstrap',
        '/api/webapp/provider/offers',
        '/api/webapp/provider/catalog/sections/{section_id}/status',
        '/api/webapp/provider/catalog/services/{service_id}/status',
    ):
        require(source, route, where="FastAPI server")
    require(source, "verify_telegram_init_data", where="FastAPI server")
    require(source, 'request.headers.get("X-Telegram-Init-Data"', where="FastAPI server")
    require(source, "ProviderCreateRequest(BaseModel)", where="FastAPI server")
    require(source, "OfferCreateRequest(BaseModel)", where="FastAPI server")
    require(source, "@field_validator", where="FastAPI server")
    require(source, "@model_validator", where="FastAPI server")
    require(source, "context.bot.send_message", where="FastAPI server")


def validate_business_services() -> None:
    validation = text("app/services/webapp_validation.py")
    for marker in (
        "validate_person_full_name",
        "normalize_iraqi_phone",
        "validate_optional_arabic_platform_name",
        "validate_optional_english_name",
        "normalize_staff_identifiers",
        "parse_iqd_amount",
        "suggested_iqd_amount",
        "validate_catalog_label",
    ):
        require(validation, marker, where="shared WebApp validation")

    provider = text("app/services/webapp_provider.py")
    for marker in (
        "ProviderStaff(",
        'role="OWNER"',
        "ensure_subscription",
        "create_default_provider_catalog",
        "mark_platform_authorization_dirty",
        'status=ProviderStatus.ACTIVE.value',
        "default_service_fee_iqd",
        "staff_identifiers",
    ):
        require(provider, marker, where="provider WebApp service")

    offer = text("app/services/webapp_offer.py")
    for marker in (
        "OfferCatalogPlacement(",
        "OfferValidityPolicy(",
        "validate_offer_price",
        "configure_fulfillment",
        "warranties.configure",
        "activation_guides.upsert",
        "FULFILLMENT_MAP",
        "OUT_OF_STOCK",
    ):
        require(offer, marker, where="offer WebApp service")


def validate_bot_entry_buttons() -> None:
    admin = text("app/bot/handlers/admin/catalog.py")
    offers = text("app/bot/handlers/provider_catalog.py")
    require(admin, "/webapp/admin/provider", where="admin provider button")
    require(admin, "WebAppInfo", where="admin provider button")
    require(offers, "/webapp/provider/offer?provider_id=", where="provider offer button")
    require(offers, 'F.data == "provider:offer_add"', where="offer legacy fallback")
    require(offers, 'text="➕ إضافة عرض"', where="offer WebApp button")
    reject(offers, "رفع شعار المنصة خطوة إلزامية قبل إنشاء أول عرض", where="optional-logo contract")
    reject(text("app/api/server.py"), "يجب رفع شعار المنصة من لوحة المنصة قبل إنشاء أول عرض", where="optional-logo API contract")
    reject(text("app/bot/handlers/admin/catalog.py"), "لا يمكن تفعيل المنصة قبل رفع شعارها", where="optional-logo admin contract")


def validate_python_syntax() -> None:
    for rel in (
        "app/api/server.py",
        "app/services/webapp_validation.py",
        "app/services/webapp_profile.py",
        "app/services/webapp_provider.py",
        "app/services/webapp_offer.py",
        "app/services/branding.py",
        "app/services/container.py",
        "app/bot/handlers/admin/catalog.py",
        "app/bot/handlers/provider_catalog.py",
    ):
        source = text(rel)
        try:
            ast.parse(source, filename=rel)
        except SyntaxError as exc:
            fail(f"syntax error in {rel}:{exc.lineno}: {exc.msg}")


def main() -> None:
    validate_python_syntax()
    validate_templates()
    validate_server_contract()
    validate_runtime_contract_samples()
    validate_business_services()
    validate_bot_entry_buttons()
    print("WebApp architecture contract validation passed")


if __name__ == "__main__":
    main()
