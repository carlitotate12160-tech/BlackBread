import base64
import os

os.environ.setdefault(
    "BLACKBREAD_ARTIFACT_KEY",
    base64.urlsafe_b64encode(bytes(range(32))).decode("ascii"),
)
