from unittest.mock import AsyncMock
import pytest
from app.services.llm import OpenRouterClient, OpenRouterError

@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["not json", "[]", '{"suggestion":null}', '{"suggestion":42}', '{"suggestion":"' + 'x'*401 + '"}', '{"suggestion":""}'])
async def test_bad_or_empty_hint_does_not_block_goal_flow(result):
    client = OpenRouterClient()
    client._chat = AsyncMock(return_value=result)
    assert await client.suggest_photo_report("goal") == ""

@pytest.mark.asyncio
async def test_provider_error_is_optional():
    client = OpenRouterClient()
    client._chat = AsyncMock(side_effect=OpenRouterError("unavailable"))
    assert await client.suggest_photo_report("goal") == ""

@pytest.mark.asyncio
async def test_context_and_prior_offer_reach_model():
    client = OpenRouterClient()
    client._chat = AsyncMock(return_value='{"suggestion":""}')
    await client.suggest_photo_report("Make a drawing", "Not yet", [{"role":"assistant","content":"Send a photo if you want"}])
    payload = client._chat.call_args.args[0][1]["content"]
    assert "Make a drawing" in payload and "Not yet" in payload and "Send a photo if you want" in payload

@pytest.mark.asyncio
@pytest.mark.parametrize('result,reason', [
    ('not json', 'invalid_json'), ('[]', 'invalid_schema'),
    ('{"suggestion":"' + 'x'*401 + '"}', 'too_long'),
    ('{"suggestion":""}', 'not_applicable'),
    ('{"suggestion":"Можешь прислать фото рисунка"}', 'generated'),
])
async def test_diagnostic_reason_without_content(result, reason, caplog):
    import logging
    client = OpenRouterClient()
    client._chat = AsyncMock(return_value=result)
    with caplog.at_level(logging.INFO):
        await client.suggest_photo_report('PRIVATE_GOAL', 'PRIVATE_MESSAGE')
    assert 'reason=' + reason in caplog.text
    assert 'PRIVATE_' not in caplog.text
    assert 'рисунка' not in caplog.text

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {}, {'choices': [None]}, {'choices': 'oops'},
    {'choices': [{'message': None}]}, {'choices': [{'message': {'content': ' '}}]}])
async def test_malformed_http200_does_not_escape_optional_hint(monkeypatch, body, caplog):
    import logging
    from types import SimpleNamespace
    import app.services.llm as module
    response = SimpleNamespace(status_code=200, json=lambda: body)
    transport = AsyncMock()
    transport.__aenter__.return_value.post.return_value = response
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: transport)
    with caplog.at_level(logging.INFO):
        assert await OpenRouterClient().suggest_photo_report('private') == ''
    assert 'photo_hint reason=' in caplog.text

@pytest.mark.parametrize('text,declined', [
    ('Не хочу присылать фотографии', True), ('Без фото, пожалуйста', True),
    ('Фото не нужны', True), ('Больше не предлагай снимки', True),
    ('Не хочу грустить, хочу нарисовать картину', False),
    ('План без обязательного фото', False), ('Можно прислать фото?', False),
])
def test_explicit_refusal_is_not_confused_with_drawing_or_optional_photo(text, declined):
    from app.bot.photo_hints import declines_photos
    assert declines_photos(text) == declined
