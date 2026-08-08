"""Generate production secrets for Railway without writing them to disk."""

from secrets import token_urlsafe

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(f"ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    print(f"REPORT_SECRET_KEY={token_urlsafe(48)}")
    print(f"API_ADMIN_TOKEN={token_urlsafe(48)}")
    print(f"PAYMENT_WEBHOOK_SECRET={token_urlsafe(48)}")
