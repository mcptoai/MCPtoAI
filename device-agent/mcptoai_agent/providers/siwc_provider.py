"""ChatGPT sign-in Responses provider; transport uses a device-only token supplier.

The OAuth lifecycle must be installed before this provider can be selected.
"""
from __future__ import annotations
import httpx
from .base import Provider, ToolSpec
from .siwc_responses import parse_events, request_payload

ENDPOINT='https://api.openai.com/v1/responses'


class SIWCProvider(Provider):
    name='chatgpt'

    def __init__(self, model: str, access_token_supplier, *, client=None, origin="unknown", user_initiated=False, web_authorized=False):
        super().__init__('',model)
        self._token_supplier=access_token_supplier
        self._client=client
        self._origin=origin
        self._user_initiated=user_initiated
        self._web_authorized=web_authorized

    async def list_models(self) -> list[dict]:
        import asyncio
        from ..siwc_auth import list_models
        return await asyncio.to_thread(list_models)

    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec]):
        from ..siwc_gate import enforce
        enforce(origin=self._origin, user_initiated=self._user_initiated, web_authorized=self._web_authorized)
        token=await self._token_supplier()
        if not isinstance(token,str) or not token:
            raise RuntimeError('ChatGPT sign-in required')
        payload=request_payload(self.model,system,messages,tools)
        if self._client is None:
            async with httpx.AsyncClient(timeout=90) as client:
                return await self._request(client,token,payload)
        return await self._request(self._client,token,payload)

    @staticmethod
    async def _request(client, token, payload):
        async with client.stream('POST',ENDPOINT,json=payload,headers={
            'Authorization':'Bearer '+token,'Accept':'text/event-stream'}) as response:
            response.raise_for_status()
            lines=[]
            total=0
            async for line in response.aiter_lines():
                total+=len(line)
                if total>8*1024*1024:
                    raise RuntimeError('SIWC response exceeded safety limit')
                lines.append(line)
            return parse_events(lines)
