from ecdsa import SigningKey, VerifyingKey, NIST256p
import base64


def generate_keys():
    sk = SigningKey.generate(curve=NIST256p)
    vk = sk.verifying_key

    return sk.to_string().hex(), vk.to_string().hex()


def sign_message(private_key_hex, message):
    sk = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=NIST256p)
    signature = sk.sign(message.encode())

    return base64.b64encode(signature).decode()


def verify_signature(public_key_hex, message, signature):
    try:
        vk = VerifyingKey.from_string(bytes.fromhex(public_key_hex), curve=NIST256p)
        return vk.verify(base64.b64decode(signature), message.encode())
    except Exception:
        return False