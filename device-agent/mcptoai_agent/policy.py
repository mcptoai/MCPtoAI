"""İzin katmanı: model sadece araç ister, kararı burası verir."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Awaitable, Callable


class Decision(str, enum.Enum):
    AUTO = "auto"        # onaysız çalışır
    CONFIRM = "confirm"  # kullanıcı onayı gerekir
    DENY = "deny"        # hiç çalışmaz


# Varsayılan kurallar. Listede olmayan araçlar CONFIRM sayılır (güvenli varsayılan).
DEFAULT_RULES: dict[str, Decision] = {
    "list_dir": Decision.CONFIRM,
    "read_file": Decision.CONFIRM,
    "find_files": Decision.CONFIRM,
    "disk_usage": Decision.AUTO,
    "running_processes": Decision.AUTO,
    "write_file": Decision.CONFIRM,
    "send_artifact": Decision.CONFIRM,
    "open_app": Decision.CONFIRM,
    "capture_screen": Decision.CONFIRM,
    "open_url": Decision.CONFIRM,
    "web_fetch": Decision.AUTO,
    "generate_image": Decision.CONFIRM,
    "run_command": Decision.CONFIRM,
    "run_in_project": Decision.CONFIRM,
    # Uzun süreli görevler: başlatmak/durdurmak onay ister, durum okumak istemez.
    "job_start": Decision.CONFIRM,
    "job_stop": Decision.CONFIRM,
    "job_status": Decision.AUTO,
    "job_list": Decision.AUTO,
    "load_skill": Decision.AUTO,
    "read_skill_file": Decision.AUTO,
    "skill_data_read": Decision.AUTO,
    "skill_data_write": Decision.CONFIRM,
    "run_skill_script": Decision.CONFIRM,
}


# These capabilities can change local state, execute code, expose the screen,
# or cause an external side effect.  AUTO is never honored for them, even if
# a stale/corrupt config file says otherwise.  A live user approval is required.
FORCE_CONFIRM_TOOLS: frozenset[str] = frozenset({
    "send_artifact", "write_file", "open_app", "capture_screen", "capture_microphone",
    "generate_image",
    "capture_camera", "open_url", "run_command", "run_in_project",
    "job_start", "job_stop", "run_skill_script", "skill_data_write",
})

# Güvenilmeyen talimat (skill) bağlamdayken onay İSTEYEN araçlar. web_fetch normalde onaysızdır (kullanıcının kendi isteği),
# ama enjekte edilmiş bir skill talimatı sohbetten aldığı bilgiyi bir adresin sorgusuna iliştirip dışarı sızdırabilir:
# güvenilmeyen talimat + özel veri + onaysız dış iletişim. Kullanıcı "Allow" ya da "bir daha sorma" demiş olsa da geçerlidir.
UNTRUSTED_CONTEXT_CONFIRM_TOOLS: frozenset[str] = frozenset({"web_fetch"})

# Onay isteyici: (araç adı, argümanlar) -> onaylandı mı
Approver = Callable[[str, dict], Awaitable[bool]]


@dataclass
class ToolPolicy:
    rules: dict[str, Decision] = field(default_factory=lambda: dict(DEFAULT_RULES))
    # Oturum boyunca "bir daha sorma" denen araçlar
    session_grants: set[str] = field(default_factory=set)

    def decide(self, tool: str) -> Decision:
        if tool in self.session_grants:
            return Decision.AUTO
        return self.rules.get(tool, Decision.CONFIRM)

    async def authorize(self, tool: str, args: dict, approver: Approver, *, untrusted_context: bool = False) -> tuple[bool, str]:
        """(izin verildi mi, gerekçe) döndürür. untrusted_context: oturumda bir skill'in talimatı modelin bağlamında."""
        decision = self.decide(tool)
        if tool in FORCE_CONFIRM_TOOLS and decision is Decision.AUTO:
            decision = Decision.CONFIRM
        if untrusted_context and tool in UNTRUSTED_CONTEXT_CONFIRM_TOOLS and decision is Decision.AUTO:
            decision = Decision.CONFIRM
        if decision is Decision.AUTO:
            return True, "auto"
        if decision is Decision.DENY:
            return False, "policy_denied"
        approved = await approver(tool, args)
        return approved, "user_approved" if approved else "user_denied"

CAPABILITIES = {
 "files":{"label":"Files & Folders","tools":{"list_dir","read_file","find_files","write_file","send_artifact"},"default":Decision.CONFIRM},
 "app_control":{"label":"App Control","tools":{"open_app"},"default":Decision.CONFIRM},
 "screen":{"label":"Screen Recording","tools":{"capture_screen"},"default":Decision.CONFIRM},
 "microphone":{"label":"Microphone","tools":{"capture_microphone"},"default":Decision.DENY},
 "camera":{"label":"Camera","tools":{"capture_camera"},"default":Decision.DENY},
}
