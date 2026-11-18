"""User-facing context-budget errors, independent of provider and client UI."""

class ContextBudgetError(RuntimeError):
    pass

_MESSAGES = {
    'en': 'This request exceeds the selected model’s context capacity. Shorten the message or choose a model with a larger context window.',
    'tr': 'Bu istek seçili modelin bağlam kapasitesini aşıyor. Mesajı kısaltın veya daha geniş bağlamlı bir model seçin.',
    'de': 'Diese Anfrage überschreitet das Kontextlimit des gewählten Modells. Kürzen Sie die Nachricht oder wählen Sie ein Modell mit größerem Kontextfenster.',
    'fr': 'Cette demande dépasse la capacité de contexte du modèle choisi. Raccourcissez le message ou choisissez un modèle avec une fenêtre de contexte plus grande.',
    'es': 'Esta solicitud supera el límite de contexto del modelo seleccionado. Acorte el mensaje o elija un modelo con mayor capacidad de contexto.',
    'zh': '此请求超出了所选模型的上下文容量。请缩短消息或选择支持更大上下文的模型。',
    'ar': 'يتجاوز هذا الطلب سعة السياق للنموذج المحدد. اختصر الرسالة أو اختر نموذجًا بسياق أكبر.',
}

def friendly_context_error(language):
    code = str(language or 'en').strip().lower().replace('_', '-').split('-')[0]
    aliases = {'turkish':'tr','english':'en','german':'de','french':'fr','spanish':'es','chinese':'zh','arabic':'ar'}
    return _MESSAGES.get(aliases.get(code, code), _MESSAGES['en'])
