import asyncio
import base64
import io
from types import SimpleNamespace
from PIL import Image
from mcptoai_agent.context_budget import assemble, estimate_tokens, resolve_budget, complete_with_context_retry
from mcptoai_agent.context_layers import ContextLayers, select_layered
from mcptoai_agent.image_token_budget import visual_tokens
from mcptoai_agent.context_errors import friendly_context_error


def make_image(w, h, typ='PNG', noisy=False):
    im = Image.new('RGB', (w, h), 'white')
    if noisy:
        from PIL import ImageDraw
        draw=ImageDraw.Draw(im)
        for y in range(0, h, 17):draw.line((0,y,w,y),fill=(y%255,100,50))
    out=io.BytesIO();im.save(out,format=typ)
    return {'data_url': f'data:image/{"jpeg" if typ=="JPEG" else "png"};base64,'+base64.b64encode(out.getvalue()).decode()}


def test_three_megabyte_png_screen_without_context_overflow():
    # Incompressible pixels simulate a multi-MB screenshot; only pixel dimensions count.
    import random
    random.seed(42)
    im=Image.frombytes('RGB',(1100,1100),random.randbytes(1100*1100*3))
    buf=io.BytesIO();im.save(buf,format='PNG');assert len(buf.getvalue())>3_000_000
    image={'data_url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()}
    h=[{'role':'user','content':'Inspect the screenshot','images':[image]}]
    for provider in ('openai','anthropic'):
        budget=resolve_budget(SimpleNamespace(name=provider,context_window_tokens=32768))
        prompt,kept,truncated=assemble('system',h,budget)
        assert not truncated and kept==h and len(prompt)>0
        assert estimate_tokens(h[0],provider)<12000


def test_ten_megapixel_photo_no_context_overflow():
    image=make_image(4000,2500,'JPEG')
    h=[{'role':'user','content':'Describe the photo','images':[image]}]
    for provider in ('openai','anthropic'):
        budget=resolve_budget(SimpleNamespace(name=provider,context_window_tokens=32768))
        assert not assemble('system',h,budget)[2]
        assert estimate_tokens(h[0],provider)<12000
        assert visual_tokens(image,provider)>100


def test_large_encoded_base64_not_charged_as_utf8_text():
    image=make_image(2048,1200)
    huge={'data_url':image['data_url']+'A'*7_000_000}
    a=estimate_tokens({'role':'user','content':'x','images':[huge]},'anthropic')
    assert a<9000
    assert estimate_tokens({'role':'user','content':'x','images':[image]},'anthropic')<9000
    assert visual_tokens(huge,'anthropic')<8192


def test_layered_context_and_provider_receive_complete_unmodified_image():
    image=make_image(1600,1200)
    message={'role':'user','content':'Inspect this','images':[image]}
    provider=SimpleNamespace(name='openai',context_window_tokens=32768)
    budget=resolve_budget(provider)
    _,kept,truncated=select_layered('system',[message],budget,ContextLayers())
    assert kept[0]['images'][0]['data_url']==image['data_url'] and not truncated
    class Fake:
        name='openai'
        context_window_tokens=32768
        async def complete(self,system,messages,tools):
            assert messages[-1]['images'][0]['data_url']==image['data_url']
            return 'ok'
    assert asyncio.run(complete_with_context_retry(Fake(),'system',[message],[],layers=ContextLayers()))[0]=='ok'


def test_unknown_provider_has_fixed_visual_cost_and_text_still_is_text():
    image=make_image(1700,1100)
    message={'role':'user','content':'x'*100000,'images':[image]}
    assert visual_tokens(image,'unverified')==8192
    assert estimate_tokens(message,'unverified')>50000


def test_seven_web_languages_translate_context_code():
    for language in ('en','tr','de','fr','es','zh','ar'):
        result=friendly_context_error(language)
        assert result and result!=friendly_context_error('en') or language=='en'
