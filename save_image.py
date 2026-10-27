import base64

base64_image = """PASTE_THE_MASKEDIMAGE_STRING_HERE"""

with open("masked_aadhaar.png", "wb") as f:
    f.write(base64.b64decode(base64_image))

print("Masked Aadhaar saved as masked_aadhaar.png")
