from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    full_name = State()
    phone = State()
    governorate = State()
    university = State()
    college = State()
    department = State()
    stage = State()


class ProfileEditStates(StatesGroup):
    field = State()
    value = State()


class PurchaseStates(StatesGroup):
    activation_field = State()
    confirmation = State()


class OrderCouponStates(StatesGroup):
    code = State()


class PaymentProofStates(StatesGroup):
    proof_file = State()
    sender_phone = State()
    amount = State()
    reference = State()


class PaymentReviewStates(StatesGroup):
    reject_reason = State()


class ReviewStates(StatesGroup):
    comment = State()


class MissingServiceStates(StatesGroup):
    name = State()
    details = State()


class MissingServiceReplyStates(StatesGroup):
    text = State()


class SupportStates(StatesGroup):
    custom_question = State()
    direct_message = State()
    ticket_message = State()


class WithdrawalStates(StatesGroup):
    amount = State()
    method = State()
    destination = State()


class AdminProviderStates(StatesGroup):
    name_ar = State()
    name_en = State()
    slug = State()
    description = State()
    contact = State()
    commission = State()


class AdminProviderLogoStates(StatesGroup):
    provider_id = State()
    logo = State()
    confirm = State()


class AdminCategoryStates(StatesGroup):
    name = State()
    emoji = State()


class AdminOfferStates(StatesGroup):
    provider_id = State()
    service_id = State()
    category_id = State()
    title = State()
    description = State()
    price = State()
    service_fee = State()
    delivery_type = State()
    activation_fields = State()
    daily_limit = State()
    validity_type = State()
    validity_value = State()
    start_trigger = State()
    warranty_hours = State()


class AdminCatalogSectionStates(StatesGroup):
    provider_id = State()
    name = State()
    emoji = State()


class AdminCatalogServiceStates(StatesGroup):
    provider_id = State()
    section_id = State()
    name = State()
    emoji = State()


class AdminOfferImageStates(StatesGroup):
    offer_id = State()
    image = State()


class AdminPaymentMethodStates(StatesGroup):
    provider_id = State()
    name = State()
    method_type = State()
    recipient = State()
    instructions = State()
    proof_guide = State()


class AdminEmailStates(StatesGroup):
    provider_id = State()
    offer_id = State()
    label = State()
    host = State()
    port = State()
    username = State()
    secret = State()
    sender_filter = State()
    subject_regex = State()
    code_regex = State()
    daily_limit = State()
    valid_until = State()


class AdminInventoryStates(StatesGroup):
    offer_id = State()
    item_kind = State()
    label = State()
    payload = State()
    expires_at = State()


class AdminMenuTextStates(StatesGroup):
    key = State()
    text = State()


class AdminMediaStates(StatesGroup):
    name = State()
    file = State()


class AdminBroadcastStates(StatesGroup):
    message = State()
    confirm = State()


class AdminAssignStaffStates(StatesGroup):
    provider_id = State()
    telegram_id = State()


class AdminSettingStates(StatesGroup):
    key = State()
    value = State()


class AdminWithdrawalStates(StatesGroup):
    proof = State()


class AdminOrderCouponStates(StatesGroup):
    code = State()
    value = State()
    max_uses = State()


class AdminPlatformCollectionStates(StatesGroup):
    amount = State()


class ProviderSettlementProofStates(StatesGroup):
    proof = State()


class ProviderManualDeliveryStates(StatesGroup):
    payload = State()


class AdminSubscriptionTrialStates(StatesGroup):
    provider_id = State()
    days = State()


class AdminSubscriptionExtendStates(StatesGroup):
    provider_id = State()
    days = State()


class AdminSubscriptionLimitStates(StatesGroup):
    provider_id = State()
    limit_key = State()
    value = State()
    days = State()


class AdminCommissionOverrideStates(StatesGroup):
    provider_id = State()
    percent = State()
    days = State()


class ProviderCouponStates(StatesGroup):
    code = State()


class ProviderStudentCouponStates(StatesGroup):
    target = State()
    value = State()
    code = State()


class AdminCouponStates(StatesGroup):
    code = State()
    kind = State()
    value = State()
    plan_code = State()
    feature_key = State()
    feature_days = State()
    valid_days = State()
    max_uses = State()


class AdminFeatureTemporaryStates(StatesGroup):
    provider_id = State()
    feature_key = State()
    enabled = State()
    days = State()


class AdminSubscriptionPriceStates(StatesGroup):
    provider_id = State()
    value = State()


class AdminPlanStates(StatesGroup):
    code = State()
    name_ar = State()
    price = State()
    price_confirm = State()
    billing_days = State()
    grace_days = State()


class AdminPlanEditStates(StatesGroup):
    plan_id = State()
    field = State()
    value = State()
    price_confirm = State()


class AdminPlanLimitStates(StatesGroup):
    plan_id = State()
    limit_key = State()
    value = State()


class AdminMenuPositionStates(StatesGroup):
    value = State()


class AdminMessageTemplateStates(StatesGroup):
    body = State()


class AdminStartMessageStates(StatesGroup):
    body = State()
    confirm = State()


class ProviderBrandingStates(StatesGroup):
    logo = State()
    confirm = State()


class ProviderCatalogSectionStates(StatesGroup):
    name = State()
    emoji = State()


class ProviderCatalogServiceStates(StatesGroup):
    name = State()
    emoji = State()


class ProviderCatalogEditStates(StatesGroup):
    section_name = State()
    service_name = State()
    offer_title = State()
    offer_price = State()
    offer_price_confirm = State()


class ProviderOfferStates(StatesGroup):
    title = State()
    description = State()
    price = State()
    service_fee = State()
    promotion_type = State()
    promotion_price = State()
    promotion_end = State()
    delivery_type = State()
    validity_type = State()
    validity_value = State()
    start_trigger = State()
    daily_limit = State()
    terms = State()


class ProviderCredentialUpdateStates(StatesGroup):
    payload = State()
    email = State()
    password = State()
    instructions = State()
    expires_at = State()


class ProviderInventoryStates(StatesGroup):
    label = State()
    email = State()
    password = State()
    instructions = State()
    payload = State()
    expires_at = State()


class ProviderPaymentMethodStates(StatesGroup):
    name = State()  # legacy compatibility; V11.2 derives the canonical name automatically.
    method_type = State()
    balance_mode = State()
    recipient = State()
    instructions = State()
    proof_guide = State()


class ProviderTicketReplyStates(StatesGroup):
    text = State()


class ProviderGuideStates(StatesGroup):
    activation_mode = State()
    intro = State()
    step_kind = State()
    step_content = State()
    more_steps = State()
    review = State()


class BotIssueStates(StatesGroup):
    category = State()
    description = State()
    attachment = State()


class AdminAnnouncementStates(StatesGroup):
    title = State()
    body = State()
    target_scope = State()
    target_value = State()
    duration_hours = State()
    pin = State()
    button = State()
    confirm = State()


class AdminSystemPriceStates(StatesGroup):
    price_key = State()
    value = State()
    confirm = State()


class AdminCustomButtonStates(StatesGroup):
    key = State()
    text = State()
    content_type = State()
    content = State()
    roles = State()
    surface = State()
    parent = State()
    confirm = State()


class ProviderReportV5States(StatesGroup):
    report_type = State()
    period = State()
    custom_start = State()
    custom_end = State()
    tier = State()


class OfferPriceConfirmStates(StatesGroup):
    provider_offer = State()
    admin_offer = State()


class ProviderEmailStates(StatesGroup):
    offer = State()
    provider_kind = State()
    username = State()
    secret = State()
    confirm = State()


class DirectSupportStates(StatesGroup):
    details = State()


class DisputeStates(StatesGroup):
    """Legacy alias retained only for old callbacks during migration."""
    details = State()


class ProviderDisputeStates(StatesGroup):
    extension_days = State()
    partial_refund_amount = State()
    refund_reference = State()
    resolution_note = State()


class ProviderFulfillmentStates(StatesGroup):
    account_type = State()
    capacity = State()
    temporary_mode = State()
    temporary_minutes = State()
    student_email = State()
    student_code = State()


class ProviderWorkingHoursStates(StatesGroup):
    opens_at = State()
    closes_at = State()


class ProviderInboxActionStates(StatesGroup):
    note = State()


class StudentActivationStates(StatesGroup):
    email = State()
    code = State()


class TemporaryLogoutStates(StatesGroup):
    proof = State()
    note = State()


class FriendPackageStates(StatesGroup):
    custom_members = State()


class WarrantyClaimStates(StatesGroup):
    screenshot = State()
    note = State()


class AdminBillingPolicyStates(StatesGroup):
    fee = State()
    due_hours = State()


class AdminCampaignRejectStates(StatesGroup):
    reason = State()


class AdminCouponCampaignStates(StatesGroup):
    provider = State()
    audience = State()
    code = State()
    kind = State()
    value = State()
    max_uses = State()


class AdminHybridBundleStates(StatesGroup):
    title = State()
    description = State()
    price = State()
    bot_fee = State()
    components = State()


class ProviderInvoiceProofStates(StatesGroup):
    amount = State()
    proof = State()


class ProviderAdCampaignStates(StatesGroup):
    campaign_type = State()
    title = State()
    body = State()
    offer_id = State()
    audience = State()
    duration_hours = State()
    proof = State()


class ProviderRewardCampaignStates(StatesGroup):
    title = State()
    channel_chat_id = State()
    channel_url = State()
    reward_iqd = State()
    requested_count = State()
    budget_iqd = State()
    proof = State()


class HybridPurchaseProofStates(StatesGroup):
    amount = State()
    proof = State()


class ProviderCouponCampaignStates(StatesGroup):
    audience = State()
    code = State()
    kind = State()
    value = State()
