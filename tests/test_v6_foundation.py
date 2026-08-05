from app.services.money import iqd_in_words

def test_iqd_words():
    assert iqd_in_words(4000) == "أربعة آلاف دينار"
    assert "خمسمائة" in iqd_in_words(5500)

def test_v6_models_import():
    from app.db.models import Wallet, ProviderSettlement, OfferResourcePool, TemporaryAccessSession
    assert Wallet.__tablename__ == "cp_wallets"
    assert ProviderSettlement.__tablename__ == "cp_provider_settlements"
    assert OfferResourcePool.__tablename__ == "cp_offer_resource_pools"
    assert TemporaryAccessSession.__tablename__ == "cp_temporary_access_sessions"
