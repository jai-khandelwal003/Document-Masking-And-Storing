from PIL import Image, ImageEnhance

def increase_resolution(image) -> Image:
    # Increase the resolution of the image
    # enhancer = ImageEnhance.Contrast(image)
    # image = enhancer.enhance(2)
    return image

def increase_size_and_resolution(image, size) -> Image:
    # Increase the size of the image
    width, height = image.size

    if width < 500 or height < 500:
        new_width = width * 2
        new_height = height * 2
        image = image.resize((new_width, new_height),Image.Resampling.LANCZOS)
        return increase_resolution(image)
    if size < 1000000:
        new_width = width * 2
        new_height = height * 2
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        return increase_resolution(image)

    if (height<1000 or width < 1000) and (width-height > 400 or height-width > 400) :
        new_width = width * 4
        new_height = height * 4
        image = image.resize((new_width, new_height),Image.Resampling.LANCZOS)
        return increase_resolution(image)
    return image
