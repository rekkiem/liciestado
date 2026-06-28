#!/usr/bin/env python3
"""Genera una FERNET_KEY lista para pegar en .env"""
from cryptography.fernet import Fernet
key = Fernet.generate_key().decode()
print(f"\nAgrega esta línea a tu .env:\n\nFERNET_KEY={key}\n")
