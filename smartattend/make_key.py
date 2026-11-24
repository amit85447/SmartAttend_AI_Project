"""Prints a new encryption key for SMARTATTEND_KEY in your .env file. Keep it secret and back it up:
without it, stored face templates cannot be read."""
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
