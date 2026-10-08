"""Uzun süreli görev yöneticisi (jobs.py) testleri. Platformdan bağımsız: komutlar Python ile."""
import os
import subprocess
import sys
import time

import pytest

from mcptoai_linux.jobs import JobError, JobManager, parse_progress, redact

PY = f'"{sys.executable}"'


def _py(code: str) -> str:
    return f'{PY} -c "{code}"'


def _wait(manager, job_id, status="running", timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        st = manager.status(job_id)
        if st["status"] != status:
            return st
        time.sleep(0.2)
    raise AssertionError(f"görev {timeout} sn içinde '{status}' durumundan çıkmadı")


def _alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    stat = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


@pytest.fixture
def jm(tmp_path):
    return JobManager(root=tmp_path / "jobs")


def test_gorev_calisir_biter_ve_cikti_cikis_kodu_saklanir(jm):
    job = jm.start(_py("import time;print('epoch 1/3');time.sleep(1);print('epoch 3/3 bitti')"), name="deneme")
    assert job["status"] == "running" and job["id"].startswith("job-")
    st = _wait(jm, job["id"])
    assert st["status"] == "finished" and st["exit_code"] == 0
    assert "epoch 3/3 bitti" in st["output_tail"]
    assert st["progress"]["epoch"] == {"current": 3, "total": 3}


def test_hata_kodu_yakalanir(jm):
    job = jm.start(_py("import sys;sys.exit(7)"))
    st = _wait(jm, job["id"])
    assert st["status"] == "finished" and st["exit_code"] == 7


def test_agent_yeniden_baslasa_da_gorev_surer_ve_sonuc_kaybolmaz(jm, tmp_path):
    job = jm.start(_py("import time;time.sleep(2);print('tamam')"))
    # Agent yeniden başladı: yeni yönetici, eski süreç nesnesi yok.
    fresh = JobManager(root=tmp_path / "jobs")
    assert fresh.status(job["id"])["status"] == "running"
    st = _wait(fresh, job["id"])
    assert st["status"] == "finished" and st["exit_code"] == 0 and "tamam" in st["output_tail"]


def test_durdurma_alt_surecleri_de_oldurur(jm, tmp_path):
    marker = tmp_path / "child.pid"
    code = ("import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            f"open(r'{marker}','w').write(str(c.pid));time.sleep(60)")
    job = jm.start(_py(code))
    end = time.time() + 15
    while not marker.exists() and time.time() < end:
        time.sleep(0.1)
    child = int(marker.read_text())
    assert _alive(child)
    st = jm.stop(job["id"])
    assert st["status"] == "stopped"
    end = time.time() + 5
    while _alive(child) and time.time() < end:
        time.sleep(0.2)
    assert not _alive(child), "görev durdurulunca alt süreç çalışmaya devam ediyor"


@pytest.mark.skipif(os.name == "nt", reason="POSIX sinyali")
def test_disaridan_oldurulen_gorev_kesildi_olarak_algilanir(jm):
    import signal
    job = jm.start(_py("import time;time.sleep(60)"))
    os.killpg(jm._read_state(job["id"])["pid"], signal.SIGKILL)
    time.sleep(0.5)
    assert jm.status(job["id"])["status"] == "interrupted"


def test_surec_numarasi_yeniden_kullanilinca_yanlis_calisiyor_denmez(jm):
    job = jm.start(_py("import time;time.sleep(60)"))
    state = jm._read_state(job["id"])
    jm.stop(job["id"])
    # Durumu "running" yapıp pid'i alakasız canlı bir sürece (bu test süreci) çevir.
    state.update(status="running", pid=os.getpid())
    jm._write_state(job["id"], state)
    jm._procs.clear()
    assert jm.status(job["id"])["status"] == "interrupted"


def test_sirlar_cikti_ve_komutta_gizlenir(jm):
    secret = "ghp_" + "A" * 36
    job = jm.start(_py(f"print('token={secret}')"))
    st = _wait(jm, job["id"])
    assert secret not in st["output_tail"] and "[GİZLENDİ]" in st["output_tail"]
    assert secret not in st["command"]
    assert redact("sk-ant-" + "b" * 30) == "[GİZLENDİ]"


def test_model_ozeti_ve_devam_kurali(jm):
    job = jm.start(_py("print('ok')"), name="fine-tune")
    end = time.time() + 15
    while jm._exit_code(job["id"]) is None and time.time() < end:
        time.sleep(0.1)
    summary = jm.prompt_summary()  # status() çağrılmadı: sonuç henüz bildirilmedi
    assert job["id"] in summary and "fine-tune" in summary and "henüz bildirilmedi" in summary
    assert "Devam edeyim mi?" in summary
    jm.status(job["id"])  # model sonucu aldı
    assert jm.prompt_summary() == ""


def test_gecersiz_gorev_kimligi_ve_yol_hilesi_reddedilir(jm):
    for bad in ["../../etc", "job-../x", "job-ZZZ", ""]:
        with pytest.raises(JobError):
            jm.status(bad)


def test_ayni_anda_calisan_gorev_siniri(jm, monkeypatch):
    import mcptoai_linux.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "MAX_RUNNING", 1)
    job = jm.start(_py("import time;time.sleep(30)"))
    with pytest.raises(JobError, match="en fazla 1"):
        jm.start(_py("print(1)"))
    jm.stop(job["id"])


def test_ilerleme_ayrisma():
    p = parse_progress("loss 0.3\nEpoch 2/10 step 50/200\n 45%|####   |")
    assert p["epoch"] == {"current": 2, "total": 10}
    assert p["step"] == {"current": 50, "total": 200}
    assert p["percent"] == 45.0


def test_tirnak_yuzde_ve_ampersand_bozulmaz(jm):
    # Windows'ta komut toplu iş dosyasıyla çalışır: tırnaklar korunmalı, % kaçırılmalı,
    # tırnak içindeki & ayrı bir komut gibi yorumlanmamalı.
    job = jm.start(_py("print('oran 50% & tamam')"))
    st = _wait(jm, job["id"])
    assert st["status"] == "finished" and st["exit_code"] == 0
    assert "oran 50% & tamam" in st["output_tail"]


def test_iki_kontrol_arasinda_biten_gorev_kesildi_sayilmaz(jm, monkeypatch):
    # Yarış: ilk okumada çıkış kodu yok, ardından süreç kapanmış görünüyor; aradaki anda
    # görev bitip dosyayı yazmış. Görev "interrupted" değil "finished" olmalı.
    job = jm.start(_py("print(1)"))
    end = time.time() + 15
    while jm._exit_code(job["id"]) is None and time.time() < end:
        time.sleep(0.05)
    real = jm._exit_code
    calls = {"n": 0}

    def first_missing(job_id):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(job_id)

    monkeypatch.setattr(jm, "_exit_code", first_missing)
    monkeypatch.setattr(jm, "_alive", lambda job_id, pid: False)
    st = jm.status(job["id"])
    assert st["status"] == "finished" and st["exit_code"] == 0


def test_cikis_kodu_dosyasi_kilitliyken_hata_vermez(jm, monkeypatch):
    # Windows: run.cmd çıkış kodunu move ile yerine koyarken dosya kısa bir an kilitli olur.
    import pathlib
    job = jm.start(_py('import time;time.sleep(30)'))
    real = pathlib.Path.read_text

    def locked(self, *a, **k):
        if self.name == 'exit_code':
            raise PermissionError(13, 'kilitli')
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, 'read_text', locked)
    assert jm._exit_code(job['id']) is None
    monkeypatch.undo()
    jm.stop(job['id'])


def test_durum_dosyasi_kisa_kilitte_yeniden_denenir(jm, monkeypatch):
    # Başka bir süreç state.json'u değiştirirken okuma kısa bir an başarısız olabilir.
    import pathlib
    job = jm.start(_py('print(1)'))
    real = pathlib.Path.read_text
    calls = {'n': 0}

    def flaky(self, *a, **k):
        if self.name == 'state.json' and calls['n'] < 2:
            calls['n'] += 1
            raise PermissionError(13, 'kilitli')
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, 'read_text', flaky)
    assert jm._read_state(job['id'])['id'] == job['id']
    assert calls['n'] == 2


def test_dar_sutun_genisliginde_calisan_gorev_kesildi_sayilmaz(jm, monkeypatch):
    # systemd servisinde terminal yoktur; ps 80 sütunda keserdi. Kontrol /proc'tan yapılmalı.
    monkeypatch.setenv("COLUMNS", "40")
    job = jm.start(_py("import time;time.sleep(5)"))
    jm._procs.clear()  # başka bir süreçte (servis) başlatılmış gibi
    assert jm.status(job["id"])["status"] == "running"
    jm.stop(job["id"])
