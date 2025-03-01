import re

import cv2
from fastapi import UploadFile

email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
violent_words = ["sex", "sexy", "sexual", "nude", "porn", "pornography", "nudes", "nudity"]
violent_words_regex = r"(" + "|".join(re.escape(word) for word in violent_words) + r")"
allowed_image_extension = {"png", "jpg", "jpeg"}
allowed_video_extension = {"mp4", "mov"}


def validate_username(username: str) -> None:
    validate_length(field=username, min_len=3, max_len=20, field_name="Username")
    if re.search(violent_words_regex, username, re.IGNORECASE):
        raise ValueError("Username contains restricted or inappropriate content.")


def validate_email(email: str) -> None:
    validate_length(field=email, min_len=5, max_len=255, field_name="Email")
    if not re.match(email_regex, email):
        raise ValueError("Invalid email format.")


def validate_password(password_string: str) -> None:
    validate_length(field=password_string, min_len=8, max_len=255, field_name="Password")
    if not re.search(pattern=r"\d", string=password_string):
        raise ValueError("Password must contain at least one digit.")
    if not re.search(pattern=r"[a-zA-Z]", string=password_string):
        raise ValueError("Password must contain at least one letter.")


def validate_length(field: str, min_len: int, max_len: int, field_name: str):
    if not (min_len <= len(field) <= max_len):
        raise ValueError(f"{field_name} must be between {min_len} and {max_len} characters.")


def get_file_extension(file: UploadFile) -> str:
    if file.filename and "." in file.filename:
        return file.filename.rsplit(sep=".", maxsplit=1)[-1].lower()
    return ""


async def get_video_duration(file_path: str) -> float:
    try:
        video = cv2.VideoCapture(file_path)
        if not video.isOpened():
            raise ValueError(f"Could not open video file: {file_path}")

        fps = video.get(cv2.CAP_PROP_FPS)
        total_frame_count = video.get(cv2.CAP_PROP_FRAME_COUNT)

        if fps <= 0 or total_frame_count <= 0:
            raise ValueError(f"Invalid video properties: fps={fps}, frame_count={total_frame_count}")

        duration = total_frame_count / fps
        return duration
    except Exception as e:
        raise ValueError(f"Could not get video duration: {e}")
