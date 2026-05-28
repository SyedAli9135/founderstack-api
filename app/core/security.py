from cryptography.fernet import Fernet
from app.config import settings

def encrypt_secret(plain_text: str) -> str:
    """
    Encrypts a string using the master ENCRYPTION_KEY.
    Returns the encrypted string as a base64 encoded string.
    """
    if not plain_text:
        return ""
    
    f = Fernet(settings.ENCRYPTION_KEY.get_secret_value().encode())
    return f.encrypt(plain_text.encode()).decode()

def decrypt_secret(encrypted_text: str) -> str:
    """
    Decrypts a base64 encoded string using the master ENCRYPTION_KEY.
    Returns the original plain text.
    """
    if not encrypted_text:
        return ""
    
    f = Fernet(settings.ENCRYPTION_KEY.get_secret_value().encode())
    return f.decrypt(encrypted_text.encode()).decode()
