from app.crypto import decrypt, derived_key, encrypt, last4


def test_round_trip_and_ciphertext_hides_value():
    secret = "abcd1234secretvalue9xyz"
    token = encrypt(secret)
    assert secret not in token
    assert decrypt(token) == secret
    assert last4(secret) == "9xyz"


def test_derived_keys_differ_by_label():
    assert derived_key("a") != derived_key("b")
