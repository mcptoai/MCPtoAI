from __future__ import annotations
PRESETS={
 'openai': {'name':'OpenAI','base_url':None,'key':True},
 'nvidia': {'name':'NVIDIA NIM','base_url':'https://integrate.api.nvidia.com/v1','key':True},
 'replicate': {'name':'Replicate','base_url':'https://api.replicate.com/v1','key':True,'chat':False,'credential_name':'REPLICATE_API_TOKEN'},
 'anthropic': {'name':'Anthropic','native':'anthropic','key':True},
 'evren': {'name':'EVREN','native':'evren','key':True},
 'deepseek': {'name':'DeepSeek','base_url':'https://api.deepseek.com','key':True},
 'xai': {'name':'xAI / Grok','base_url':'https://api.x.ai/v1','key':True},
 'groq': {'name':'Groq','base_url':'https://api.groq.com/openai/v1','key':True},
 'mistral': {'name':'Mistral AI','base_url':'https://api.mistral.ai/v1','key':True},
 'openrouter': {'name':'OpenRouter','base_url':'https://openrouter.ai/api/v1','key':True},
 'together': {'name':'Together AI','base_url':'https://api.together.xyz/v1','key':True},
 'fireworks': {'name':'Fireworks AI','base_url':'https://api.fireworks.ai/inference/v1','key':True},
 'cerebras': {'name':'Cerebras','base_url':'https://api.cerebras.ai/v1','key':True},
 'moonshot': {'name':'Moonshot / Kimi','base_url':'https://api.moonshot.ai/v1','key':True},
 'ollama': {'name':'Ollama','base_url':'http://127.0.0.1:11434/v1','key':False,'local':True},
 'lmstudio': {'name':'LM Studio','base_url':'http://127.0.0.1:1234/v1','key':False,'local':True},
 'local': {'name':'Custom Local','base_url':None,'key':False,'local':True},
 'custom': {'name':'Custom OpenAI-compatible','base_url':None,'key':True},
}
def preset(provider:str): return PRESETS.get(provider)

def registry(custom:dict|None=None):
    out={k:dict(v) for k,v in PRESETS.items()}
    for pid,v in (custom or {}).items():
        if not pid.startswith('custom-') or not isinstance(v,dict): continue
        out[pid]={'name':str(v.get('name') or 'Custom Provider')[:80],'base_url':str(v.get('base_url') or ''),'key':bool(v.get('key',True)),'custom':True}
    return out
