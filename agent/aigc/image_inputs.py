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


def reference_video_options(options, attachments):
    """Resolve an explicitly ordered list before tool governance freezes arguments."""
    indices = options.get('reference_image_attachment_indices')
    if indices is None:
        return options
    if (not isinstance(indices, list) or not 1 <= len(indices) <= 9
            or any(type(i) is not int or i < 1 for i in indices) or len(set(indices)) != len(indices)):
        raise ValueError("Select 1-9 distinct reference image attachment indices")
    if any(options.get(key) is not None for key in ('reference_image_asset_ids','reference_image_data_urls','reference_image_urls')):
        raise ValueError("Choose exactly one reference image source")
    result = dict(options)
    result['reference_image_data_urls'] = [attachment_image(attachments, i) for i in indices]
    result.pop('reference_image_attachment_indices')
    result.setdefault('mode', 'reference_to_video')
    return result


def spark_image_options(options, attachments):
    result = {key: options[key] for key in ("mode", "image_asset_id", "image_data_url", "denoise", "image_fit", "character_style")
              if options.get(key) is not None}
    if result.get('character_style') and not result.get('mode'):
        result['mode'] = 'character_stylization'
    index = options.get('image_attachment_index')
    if index is not None and any(options.get(key) is not None for key in ("image_asset_id", "image_data_url")):
        raise ValueError("Choose one image source: asset ID, data URL or attachment index")
    has_image = any(item.kind == 'image' and item.data_url.startswith('data:image/') for item in attachments)
    if not result.get('image_asset_id') and not result.get('image_data_url') and (
            index is not None or result.get('mode') in ('image_to_image', 'character_stylization') or (has_image and not result.get('mode'))):
        result['image_data_url'] = attachment_image(attachments, index)
        result.setdefault('mode', 'image_to_image')
    return result


async def public_image_address(host, port):
    """Resolve once and pin the connection to a public address (including redirects)."""
    import asyncio
    import ipaddress
    import socket
    records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = [record[4][0] for record in records]
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Image URL must resolve to a public address")
    return addresses[0]


def _image_bytes_data_url(content):
    from agent.search.service import _sniff_common_image_type
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Input image must contain 1 byte to 16 MiB")
    kind = _sniff_common_image_type(content)
    if kind not in {"png", "jpeg", "webp"}:
        raise ValueError("URL did not return a PNG, JPEG or WebP image")
    # Reject obvious truncation before handing decoding to the image provider.
    if (kind == "png" and (len(content) < 45 or content[-8:] != b'IEND\xaeB`\x82')
            or kind == "jpeg" and not content.rstrip().endswith(b'\xff\xd9')
            or kind == "webp" and (len(content) < 20 or int.from_bytes(content[4:8], 'little') + 8 != len(content))):
        raise ValueError("Image response is incomplete")
    media_type = f"image/{kind}"
    return f'data:{media_type};base64,' + base64.b64encode(content).decode('ascii')


async def load_image_url(url, *, transport=None):
    """Load a known image link, with bounded bytes/time and no ambient credentials."""
    import asyncio
    return await asyncio.wait_for(_load_image_url(url, transport=transport), timeout=25)


async def _load_image_url(url, *, transport=None):
    from pathlib import Path
    from urllib.parse import urljoin, urlsplit
    import httpx
    from agent.search.service import _validate_public_http_url, WEB_USER_AGENT

    if url.startswith('/static/generated/aigc/'):
        root = Path(__file__).resolve().parents[2] / 'web/static/generated/aigc'
        target = (root / url.removeprefix('/static/generated/aigc/')).resolve()
        if target.parent != root.resolve() or target.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise ValueError("Invalid generated image path")
        try:
            with target.open('rb') as source:
                return _image_bytes_data_url(source.read(MAX_IMAGE_BYTES + 1))
        except OSError as exc:
            raise ValueError("Generated image is no longer available") from exc

    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False, transport=transport) as client:
        for redirect in range(4):
            url = _validate_public_http_url(url)
            parsed = urlsplit(url)
            if parsed.username is not None or parsed.password is not None:
                raise ValueError("Image URLs must not contain credentials")
            address = await public_image_address(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
            # Retain the original Host/TLS name but never re-resolve the hostname at connect time.
            target = httpx.URL(url).copy_with(host=address)
            async with client.stream('GET', target, headers={'Host': parsed.netloc, 'Accept':'image/png,image/jpeg,image/webp', 'User-Agent': WEB_USER_AGENT},
                                     extensions={'sni_hostname': parsed.hostname}) as response:
                if response.is_redirect:
                    if redirect == 3 or not response.headers.get('location'):
                        raise ValueError("Too many image redirects or missing location")
                    url = urljoin(url, response.headers['location'])
                    continue
                response.raise_for_status()
                kind = response.headers.get('content-type','').split(';')[0].strip().lower()
                if kind and kind not in MEDIA_TYPES | {'application/octet-stream'}:
                    raise ValueError("URL did not return a supported image")
                length = response.headers.get('content-length','')
                if length.isdigit() and int(length) > MAX_IMAGE_BYTES:
                    raise ValueError("Input image exceeds 16 MiB")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_BYTES:
                        raise ValueError("Input image exceeds 16 MiB")
                return _image_bytes_data_url(bytes(content))
    raise ValueError("Unable to load image")
