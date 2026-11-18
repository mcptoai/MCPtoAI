"""Safe canonical-history transfer across model changes in a relay session."""


def inherit_model_context(session, sessions, last_used, *, session_key, sid, provider, fingerprint):
    """Inherit only from the latest same-provider, same-credential session.

    Credentials, providers, and mutable history lists are never transferred.
    """
    prefix = f'{sid}:{provider}:'
    suffix = f':{fingerprint}'
    matches = [(last_used.get(key, 0), key, old)
               for key, old in sessions.items()
               if key != session_key and key.startswith(prefix)
               and key.endswith(suffix)
               and getattr(old, 'context_layers', None) is not None]
    if not matches:
        return False
    _, _, prior = max(matches, key=lambda item: (item[0], item[1]))
    session.history = list(prior.history)
    session.context_layers = prior.context_layers
    session.context_summarizer = prior.context_summarizer
    return True
