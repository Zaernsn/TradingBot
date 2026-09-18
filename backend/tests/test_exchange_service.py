from app.services.exchange_service import encrypt_value, decrypt_value, mask_key


def test_encrypt_decrypt_roundtrip():
    plain = "my-secret-key"
    encrypted = encrypt_value(plain)
    assert encrypted != plain
    assert decrypt_value(encrypted) == plain


def test_mask_key():
    assert mask_key("ABCDEFGHIJ") == "****GHIJ"
    assert mask_key("AB") == "****"
