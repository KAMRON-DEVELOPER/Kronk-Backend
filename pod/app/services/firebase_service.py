import asyncio
from functools import partial

from firebase_admin import auth
from firebase_admin.auth import UserRecord


async def validate_firebase_token(firebase_id_token: str) -> UserRecord:
    """
    Validate the Firebase ID token and return the Firebase user object if valid.
    """
    try:
        # Verify the token asynchronously
        decoded_token: dict = await asyncio.to_thread(partial(auth.verify_id_token, firebase_id_token))
        print(f"🔨 decoded_token in validate_firebase_token: {decoded_token}")

        # Retrieve user information from Firebase
        user = await asyncio.to_thread(partial(auth.get_user, decoded_token["uid"]))
        return user
    except auth.InvalidIdTokenError:
        raise ValueError("🔥 Invalid Firebase ID token.")
    except auth.UserNotFoundError:
        raise ValueError("🔥 User not found in Firebase.")
    except Exception as e:
        raise ValueError(f"🔥 Firebase token validation failed: {e}")
