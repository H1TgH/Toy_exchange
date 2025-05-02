from secrets import token_urlsafe


def generate_api_key() -> str:
    return token_urlsafe(32)