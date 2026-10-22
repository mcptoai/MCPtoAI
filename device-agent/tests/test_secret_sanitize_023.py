"""Terminale yapıştırılan API anahtarlarının bozulması (macOS/Windows, 0.2.3): kaçış dizileri kaydedilmez, eskiden bozuk kaydedilmişler okunurken düzelir."""
import asyncio
import logging
import sys
from dataclasses import replace

import pytest

from mcptoai_agent import __main__ as cli, secret_store as ss
from mcptoai_agent.config import settings

ESC_O, ESC_I = "\x1b[O", "\x1b[I"                       # terminalin odak çıktı/girdi bildirimleri
KEY = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_abcdefgh"


def plant(name, value):
    """Eski sürümün yazdığı bozuk kaydı doğrudan depoya koyar (yeni set_secret bunu zaten reddederdi)."""
    secrets = dict(ss.read_vault() or {})
    secrets[name] = value
    ss._backend.set(ss.VAULT_ACCOUNT, ss._serialize(secrets))


@pytest.fixture(autouse=True)
def fresh_warnings():
    ss._warned_keys.clear()
    yield
    ss._warned_keys.clear()


@pytest.mark.parametrize("raw", [
    ESC_O + ESC_I + KEY, KEY + ESC_O, ESC_I + KEY + ESC_O,           # gerçek olay: başta ve sonda odak dizileri
    "\x1b[200~" + KEY + "\x1b[201~",                                  # yapıştırma işaretleri (bracketed paste)
    " \t" + KEY + " \r\n", "\x1b]0;pencere başlığı\x07" + KEY, "\x1bO" + KEY,
    KEY[:14] + "\x00" + KEY[14:], KEY[:20] + " " + KEY[20:],           # NUL ve iç boşluk
])
def test_paste_residue_is_removed(raw):
    assert ss.sanitize_api_key(raw) == KEY


def test_clean_keys_and_odd_inputs_are_left_alone():
    assert ss.sanitize_api_key(KEY) == KEY
    assert ss.sanitize_api_key("") == "" and ss.sanitize_api_key(None) == "" and ss.sanitize_api_key(123) == ""
    assert ss.sanitize_api_key("gsk_Ab-Cd_Ef.12+34/56=") == "gsk_Ab-Cd_Ef.12+34/56="      # sağlayıcıların gerçek karakter kümeleri


def test_saving_cleans_api_keys_in_every_write_path():
    ss.set_secret("api_key:anthropic", ESC_O + KEY + ESC_I)
    asyncio.run(ss.aset_secret("api_key:openai", ESC_I + KEY))
    ss.set_secrets({"api_key:groq": KEY + ESC_O})
    for name in ("anthropic", "openai", "groq"):
        assert ss.read_vault()[f"api_key:{name}"] == KEY, name                         # depoda da temiz (yalnızca okurken değil)


def test_other_secrets_may_hold_newlines_but_never_escape_sequences():
    ss.set_secret("mcp:token", "satır1\nsatır2\tsekme")                                # meşru: değişmez
    assert ss.get_secret("mcp:token") == "satır1\nsatır2\tsekme"
    for bad in ("a\x1bb", "a\x00b", "a\x7fb"):
        with pytest.raises(ValueError, match="control characters"):
            ss.set_secret("mcp:token", bad)
        with pytest.raises(ValueError):
            asyncio.run(ss.aset_secret("mcp:token", bad))
        with pytest.raises(ValueError):
            ss.set_secrets({"mcp:token": bad})


def test_previously_corrupted_keys_heal_on_read_and_warn_once(caplog):
    plant("api_key:anthropic", ESC_O + ESC_I + KEY)                                    # eski sürümün bozuk kaydı
    with caplog.at_level(logging.WARNING, logger="mcptoai.secrets"):
        assert ss.get_secret("api_key:anthropic") == KEY
        assert ss.get_secret("api_key:anthropic") == KEY
    warnings = [r for r in caplog.records if r.name == "mcptoai.secrets"]
    assert len(warnings) == 1 and "keys set" in warnings[0].getMessage()
    assert KEY not in warnings[0].getMessage()                                          # uyarı anahtarı yazdırmaz
    assert ss.read_vault()["api_key:anthropic"] == ESC_O + ESC_I + KEY                  # okuma depoyu yeniden yazmaz


def test_the_provider_receives_the_healed_key():
    from mcptoai_agent.providers import make_provider
    plant("api_key:anthropic", ESC_O + KEY + ESC_I)
    provider = make_provider(replace(settings, provider="anthropic", model="claude-sonnet-4-5-20250929"))
    assert provider.client.api_key == KEY


def test_keys_set_from_a_pipe_cleans_the_input(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(ESC_O + KEY + ESC_I + "\n"))
    cli._set_key("anthropic", from_stdin=True)
    assert ss.read_vault()["api_key:anthropic"] == KEY
    assert "Removed terminal control characters" in capsys.readouterr().err


def test_keys_set_from_a_terminal_cleans_the_input(monkeypatch, capsys):
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": ESC_I + KEY + ESC_O)
    cli._set_key("anthropic")
    assert ss.read_vault()["api_key:anthropic"] == KEY


def test_a_clean_key_gives_no_notice_and_an_empty_one_saves_nothing(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(KEY + "\n"))
    cli._set_key("anthropic", from_stdin=True)
    assert "Removed" not in capsys.readouterr().err
    monkeypatch.setattr(sys, "stdin", io.StringIO(ESC_O + ESC_I + "\n"))
    with pytest.raises(SystemExit):
        cli._set_key("openai", from_stdin=True)
    assert "api_key:openai" not in (ss.read_vault() or {})


def test_a_legacy_corrupted_key_never_blocks_writing_other_secrets():
    """Regresyon: kontrol karakteri reddi kasanın TAMAMINA uygulansaydı, eski bozuk tek anahtar her yazmayı engellerdi."""
    plant("api_key:anthropic", ESC_O + ESC_I + KEY)
    ss.set_secret("mcp:oauth-token", "yeni-jeton")                      # başka bir sır hâlâ kaydedilebilir
    ss.set_secret("api_key:openai", KEY)
    ss.delete_secret("mcp:oauth-token")
    assert ss.get_secret("api_key:anthropic") == KEY                    # bozuk kayıt okunurken düzelir
    assert ss.read_vault()["api_key:anthropic"] == ESC_O + ESC_I + KEY  # ve depoda olduğu gibi kalır (sessizce yeniden yazılmaz)


def test_bulk_reads_heal_corrupted_keys_too():
    """get_secrets toplu okuma yolu da (ör. sağlayıcı listesi) bozuk anahtarı düzeltir."""
    plant("api_key:anthropic", ESC_O + ESC_I + KEY)
    ss.set_secret("api_key:openai", KEY)
    assert ss.get_secrets(["api_key:anthropic", "api_key:openai", "api_key:yok"]) == {"api_key:anthropic": KEY, "api_key:openai": KEY}
