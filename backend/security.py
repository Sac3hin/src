
# backend/security.py
import hashlib

def hash_password(password: str, salt: str) -> str:
    """
    Demo hashing using SHA-256 + salt. Replace with bcrypt/Argon2 for production.
    """
    material = f"{salt}:{password}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()
