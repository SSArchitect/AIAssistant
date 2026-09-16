import base64
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from tests.test_spark_image import png

URL = "https://images.example.com/ling.png"

@pytest.mark.asyncio
async def test_url_loader_checks_real_image_and_redirects():
    from agent.aigc.image_inputs import load_image_url
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.host == '93.184.216.34'
        assert request.headers['host'] == 'images.example.com'
        if request.url.path == '/ling.png':
            return httpx.Response(302, headers={'location':'/actual.png'})
        return httpx.Response(200, content=png(320,240), headers={'content-type':'image/png'})
    with patch('agent.aigc.image_inputs.public_image_address', new=AsyncMock(return_value='93.184.216.34')):
        data = await load_image_url(URL, transport=httpx.MockTransport(handler))
    assert base64.b64decode(data.split(',')[1]) == png(320,240)
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('url', ['http://127.0.0.1/a.png','http://169.254.169.254/a','file:///etc/passwd','/static/generated/../../config/config.yaml','https://user:pass@example.com/a'])
async def test_url_loader_rejects_unsafe_sources(url):
    from agent.aigc.image_inputs import load_image_url
    with pytest.raises(ValueError):
        await load_image_url(url)


@pytest.mark.asyncio
@pytest.mark.parametrize('body,headers', [(b'<html>login</html>',{'content-type':'image/png'}), (b'x',{'content-length':'99999999'}), (png(),{'content-type':'text/html'})])
async def test_url_loader_rejects_invalid_and_oversized_responses(body, headers):
    from agent.aigc.image_inputs import load_image_url
    with patch('agent.aigc.image_inputs.public_image_address', new=AsyncMock(return_value='93.184.216.34')):
        with pytest.raises(ValueError):
            await load_image_url(URL,transport=httpx.MockTransport(lambda r:httpx.Response(200,content=body,headers=headers)))


@pytest.mark.asyncio
async def test_url_loader_blocks_private_dns_and_redirects():
    from agent.aigc.image_inputs import public_image_address, load_image_url
    with patch('socket.getaddrinfo', return_value=[(2,1,6,'',('127.0.0.1',443))]):
        with pytest.raises(ValueError):
            await public_image_address('example.com',443)
    with patch('agent.aigc.image_inputs.public_image_address',new=AsyncMock(return_value='93.184.216.34')):
        with pytest.raises(ValueError):
            await load_image_url(URL,transport=httpx.MockTransport(lambda r:httpx.Response(302,headers={'location':'http://127.0.0.1/a'})))


