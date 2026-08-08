from __future__ import annotations

from aiogram import Bot

from app.core.config import Settings
from app.core.security import SecretBox
from app.integrations.ai.gemini import GeminiClient
from app.integrations.payments.mastercard import MastercardGateway
from app.services.activation_guides import ActivationGuideService
from app.services.announcements import AnnouncementService
from app.services.audit import AuditService
from app.services.authorization import AuthorizationService
from app.services.backups import BackupService
from app.services.branding import BrandingService
from app.services.catalog import CatalogService
from app.services.cache_coherence import CacheCoherenceService
from app.services.direct_support import DirectSupportService
from app.services.deployment_gates import DeploymentGateService
from app.services.email_codes import EmailCodeService
from app.services.enterprise import EnterpriseCoreService
from app.services.enterprise_scale import EnterpriseScaleService
from app.services.evidence import EvidenceService
from app.services.features import FeatureService
from app.services.finance import FinanceService
from app.services.fulfillment import FulfillmentService
from app.services.friend_packages import FriendPackageService
from app.services.health import HealthService
from app.services.issues import BotIssueService
from app.services.key_rotation import KeyRotationService
from app.services.menus import MenuService
from app.services.modules import ModuleRegistryService
from app.services.notifications import NotificationService
from app.services.offer_lifecycle import OfferLifecycleService
from app.services.operations import OperationsService
from app.services.owner_commerce import OwnerCommerceService
from app.services.orders import OrderService
from app.services.order_coupons import OrderCouponService
from app.services.payments import PaymentService
from app.services.pilot import PilotValidationService
from app.services.pricing import PriceService
from app.services.provider_operations import ProviderOperationsService
from app.services.data_protection import DataProtectionService
from app.services.reports import ReportService
from app.services.resources import ResourcePoolService
from app.services.reviews import ReviewService
from app.services.scoped_features import ScopedFeatureService
from app.services.search import SearchService
from app.services.settlements import SettlementService
from app.services.student_subscriptions import StudentSubscriptionService
from app.services.student_commerce import StudentCommerceService
from app.services.status_rewards import StatusRewardService
from app.services.subscriptions import SubscriptionService
from app.services.support import SupportService
from app.services.templates import MessageTemplateService
from app.services.telegram_updates import TelegramUpdateInboxService
from app.services.update_safety import UpdateSafetyService
from app.services.users import UserService
from app.services.wallets import WalletService
from app.services.warranties import WarrantyService
from app.services.workflows import WorkflowService
from app.services.webapp_profile import WebAppProfileService
from app.services.webapp_provider import WebAppProviderService
from app.services.webapp_offer import WebAppOfferService


class Services:
    def __init__(self, bot: Bot, settings: Settings, secrets: SecretBox) -> None:
        self.settings = settings
        self.data_protection = DataProtectionService(settings, secrets)
        self.evidence = EvidenceService(bot, settings, secrets)
        self.authorization = AuthorizationService(settings)
        self.cache_coherence = CacheCoherenceService(settings.cache_generation_poll_seconds)
        self.update_safety = UpdateSafetyService(settings)
        self.features = FeatureService(self.cache_coherence)
        self.scoped_features = ScopedFeatureService()
        self.wallets = WalletService()
        self.resources = ResourcePoolService()
        self.search = SearchService()
        self.operations = OperationsService(settings)
        self.telegram_updates = TelegramUpdateInboxService()
        self.deployment_gates = DeploymentGateService(settings, bot)
        self.pilot = PilotValidationService(settings)
        self.backups = BackupService(settings, secrets)
        self.branding = BrandingService(bot, settings)
        self.key_rotation = KeyRotationService(settings, secrets)
        self.enterprise = EnterpriseCoreService(secrets)
        self.enterprise_scale = EnterpriseScaleService(settings, secrets)
        self.pricing = PriceService()
        self.provider_operations = ProviderOperationsService(secrets)
        self.activation_guides = ActivationGuideService()
        self.announcements = AnnouncementService(bot)
        self.issues = BotIssueService()
        self.modules = ModuleRegistryService()
        self.templates = MessageTemplateService()
        self.workflows = WorkflowService()
        self.health = HealthService(self.modules, settings, bot)
        self.subscriptions = SubscriptionService(
            default_plan_code=settings.default_provider_plan,
            default_grace_days=settings.default_subscription_grace_days,
        )
        self.users = UserService(settings, self.data_protection)
        self.webapp_profile = WebAppProfileService(self.users, self.data_protection)
        self.menus = MenuService(settings, self.features, self.cache_coherence)
        self.catalog = CatalogService()
        self.student_commerce = StudentCommerceService()
        self.status_rewards = StatusRewardService()
        self.student_subscriptions = StudentSubscriptionService()
        self.order_coupons = OrderCouponService(self.wallets)
        self.owner_commerce = OwnerCommerceService(
            enterprise=self.enterprise,
            wallets=self.wallets,
            announcements=self.announcements,
            order_coupons=self.order_coupons,
        )
        self.orders = OrderService(
            settings,
            self.subscriptions,
            self.student_subscriptions,
            self.workflows,
            self.data_protection,
            self.wallets,
        )
        self.notifications = NotificationService(bot, settings)
        self.friend_packages = FriendPackageService(
            self.orders, self.wallets, self.subscriptions, self.notifications
        )
        self.audit = AuditService()
        self.offer_lifecycle = OfferLifecycleService(
            self.announcements, self.templates, self.notifications
        )
        self.webapp_provider = WebAppProviderService(
            bot=bot,
            settings=settings,
            users=self.users,
            subscriptions=self.subscriptions,
            catalog=self.catalog,
            audit=self.audit,
        )
        self.warranties = WarrantyService(
            self.orders, self.provider_operations
        )
        self.webapp_offer = WebAppOfferService(
            settings=settings,
            catalog=self.catalog,
            pricing=self.pricing,
            workflows=self.workflows,
            offer_lifecycle=self.offer_lifecycle,
            provider_operations=self.provider_operations,
            warranties=self.warranties,
            activation_guides=self.activation_guides,
        )
        self.gemini = GeminiClient(settings)
        self.support = SupportService(
            settings, self.gemini, self.data_protection, self.enterprise_scale
        )
        self.payments = PaymentService(
            settings, self.orders, self.wallets, self.friend_packages
        )
        self.email_codes = EmailCodeService(
            settings,
            secrets,
            self.orders,
            self.notifications,
            self.student_subscriptions,
            self.provider_operations,
        )
        self.fulfillment = FulfillmentService(
            settings,
            secrets,
            self.orders,
            self.email_codes,
            self.features,
            self.notifications,
            self.student_subscriptions,
            self.activation_guides,
        )
        self.finance = FinanceService(
            settings,
            self.orders,
            self.users,
            self.notifications,
        )
        self.direct_support = DirectSupportService(
            self.orders,
            self.student_subscriptions,
            self.support,
            self.notifications,
        )
        self.settlements = SettlementService(self.wallets)
        self.reports = ReportService(settings, secrets, self.subscriptions)
        self.reviews = ReviewService()
        self.mastercard = MastercardGateway(settings, secrets)
