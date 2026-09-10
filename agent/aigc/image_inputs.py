"""Resolve image attachments without asking the LLM to copy image bytes."""
import base64
import binascii

MAX_IMAGE_BYTES = 16 * 1024**2
MAX_DATA_URL_LENGTH = ((MAX_IMAGE_BYTES + 2) // 3) * 4 + 64
MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp"}


def decode_image_data_url(value):
    if not isinstance(value, str) or len(value) > MAX_DATA_URL_LENGTH:
        raise ValueError("Input image exceeds 16 MiB")
    header, separator, encoded = value.partition(',')
    media_type = header.removeprefix('data:').removesuffix(';base64')
    if not separator or header != f'data:{media_type};base64' or media_type not in MEDIA_TYPES:
        raise ValueError("Use a PNG, JPEG or WebP base64 data URL")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid image base64") from None
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Input image must contain 1 byte to 16 MiB")
    return content, media_type


def attachment_image(attachments, index=None):
    if index is not None and (type(index) is not int or index < 1):
        raise ValueError("image_attachment_index must be a positive integer")
    candidates = [(i, item.data_url) for i, item in enumerate(attachments, 1)
                  if item.kind == 'image' and item.data_url.startswith('data:image/')]
    if index is None:
        if len(candidates) != 1:
            raise ValueError("Select image_attachment_index when there is not exactly one image attachment")
        return candidates[0][1]
    for position, value in candidates:
        if position == index:
            return value
    raise ValueError("image_attachment_index does not identify an image in this message")


def spark_image_options(options, attachments):
    result = {key: options[key] for key in ("mode", "image_asset_id", "image_data_url", "denoise", "image_fit")
              if options.get(key) is not None}
    index = options.get('image_attachment_index')
    if index is not None and any(options.get(key) is not None for key in ("image_asset_id", "image_data_url")):
        raise ValueError("Choose one image source: asset ID, data URL or attachment index")
    has_image = any(item.kind == 'image' and item.data_url.startswith('data:image/') for item in attachments)
    if not result.get('image_asset_id') and not result.get('image_data_url') and (
            index is not None or result.get('mode') == 'image_to_image' or (has_image and not result.get('mode'))):
        result['image_data_url'] = attachment_image(attachments, index)
        result.setdefault('mode', 'image_to_image')
    return result
