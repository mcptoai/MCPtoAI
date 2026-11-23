"""Stable, actionable category-only folder errors (no private absolute paths)."""
from __future__ import annotations


def folder_error_reason(exc: BaseException) -> str:
    reason=str(exc)
    if isinstance(exc,FileExistsError) or 'name_collision' in reason:
        return 'already_exists: target or intermediate folder name is already in use'
    if 'reparse_symlink' in reason or 'symlink' in reason:
        return 'reparse_symlink: symbolic link traversal is forbidden'
    if 'reparse_junction_or_mount_point' in reason:
        return 'reparse_junction: junction/mount-point traversal is forbidden'
    if 'reparse_unknown_reparse_tag' in reason:
        return 'reparse_unknown: unsupported reparse tag (blocked by default)'
    if 'workspace_not_approved' in reason or 'not an approved root' in reason:
        return 'unapproved_root: choose one of the device-advertised allowed folders'
    if 'workspace_invalid' in reason or 'workspace_argument' in reason:
        return 'invalid_root: select an existing approved absolute directory'
    if 'protected_path' in reason or 'Protected location' in reason:
        return 'protected_path: this location is not writable by remote tools'
    if 'subfolder_invalid' in reason or 'component_limit' in reason or 'absolute_or_ambiguous' in reason:
        return 'invalid_relative_path: ' + (reason.split(':',1)[1] if 'invalid_component:' in reason else 'remove traversal, reserved names, or excess nesting')
    if isinstance(exc,PermissionError):
        return 'access_denied: filesystem permission or directory safety check denied the operation'
    if isinstance(exc,FileNotFoundError):
        return 'not_found: an expected workspace or directory no longer exists'
    return 'folder_operation_failed: check the allowed root and destination name'

# The code prefix stays stable across locales so an LLM can distinguish a
# successful no-op from a refusal without guessing other tools.
_LANGS = ('en', 'tr', 'de', 'fr', 'es', 'zh', 'ar')
_TRANSLATIONS = {
    'already_exists': (
        'The folder already exists; no change was needed.',
        'Klasör zaten mevcut; değişiklik gerekmedi.',
        'Der Ordner existiert bereits; keine Änderung nötig.',
        'Le dossier existe déjà ; aucune modification nécessaire.',
        'La carpeta ya existe; no se necesitan cambios.',
        '文件夹已存在；无需更改。',
        'المجلد موجود بالفعل؛ لا حاجة إلى أي تغيير.'),
    'name_collision': (
        'A file or differently cased name blocks this folder; choose a different name.',
        'Dosya veya farklı büyük/küçük harfli ad çakışıyor; başka ad seçin.',
        'Eine Datei oder abweichende Schreibweise blockiert den Ordner; anderen Namen wählen.',
        'Un fichier ou un nom avec une casse différente bloque le dossier ; choisissez un autre nom.',
        'Un archivo o un nombre con otras mayúsculas bloquea la carpeta; elija otro nombre.',
        '文件或大小写不同的名称冲突；请选择其他名称。',
        'يوجد ملف أو اسم مختلف في حالة الأحرف؛ اختر اسمًا آخر.'),
    'reparse_symlink': ('Symbolic link traversal is blocked.', 'Sembolik bağlantıdan geçiş engellendi.', 'Symbolische Links dürfen nicht durchlaufen werden.', 'Le parcours d’un lien symbolique est interdit.', 'Está prohibido atravesar enlaces simbólicos.', '禁止通过符号链接。', 'يُمنع المرور عبر الروابط الرمزية.'),
    'reparse_junction': ('Junction or mount point traversal is blocked.', 'Junction veya bağlama noktasından geçiş engellendi.', 'Junctions und Einhängepunkte sind gesperrt.', 'Le parcours des jonctions ou points de montage est interdit.', 'Se prohíbe atravesar uniones o puntos de montaje.', '禁止通过联接点或挂载点。', 'يُمنع المرور عبر نقاط الوصل أو التركيب.'),
    'reparse_unknown': ('Unsupported reparse point; access blocked.', 'Desteklenmeyen yeniden ayrıştırma noktası; erişim engellendi.', 'Unbekannter Reparse-Punkt; Zugriff gesperrt.', 'Point de réanalyse non pris en charge ; accès bloqué.', 'Punto de análisis desconocido; acceso bloqueado.', '不支持的重解析点；已阻止访问。', 'نقطة إعادة تحليل غير مدعومة؛ تم حظر الوصول.'),
    'unapproved_root': ('Select an approved workspace root.', 'Onaylı bir çalışma alanı kökü seçin.', 'Einen genehmigten Arbeitsbereich wählen.', 'Sélectionnez un dossier racine autorisé.', 'Seleccione una raíz de trabajo aprobada.', '请选择已批准的工作区根目录。', 'اختر مجلد مساحة عمل معتمدًا.'),
    'invalid_root': ('Select an existing absolute workspace root.', 'Var olan mutlak bir çalışma alanı kökü seçin.', 'Einen vorhandenen absoluten Stammordner wählen.', 'Sélectionnez un dossier racine absolu existant.', 'Seleccione una raíz absoluta existente.', '请选择现有的绝对路径工作区根目录。', 'اختر مجلد عمل موجودًا بمسار مطلق.'),
    'protected_path': ('This location is protected.', 'Bu konum korumalıdır.', 'Dieser Speicherort ist geschützt.', 'Cet emplacement est protégé.', 'Esta ubicación está protegida.', '此位置受保护。', 'هذا الموقع محمي.'),
    'invalid_relative_path': ('Invalid relative path; remove traversal or reserved names.', 'Geçersiz göreli yol; üst dizine çıkışı ve ayrılmış adları kaldırın.', 'Ungültiger relativer Pfad; Traversierung und reservierte Namen entfernen.', 'Chemin relatif invalide ; retirez les traversées et noms réservés.', 'Ruta relativa no válida; elimine recorridos y nombres reservados.', '相对路径无效；请移除越级路径或保留名称。', 'مسار نسبي غير صالح؛ أزل اجتياز المجلدات والأسماء المحجوزة.'),
    'access_denied': ('Filesystem permission or safety check denied access.', 'Dosya sistemi izni veya güvenlik kontrolü erişimi reddetti.', 'Dateisystemberechtigung oder Sicherheitsprüfung verweigert Zugriff.', 'Une autorisation ou vérification de sécurité a refusé l’accès.', 'Un permiso o control de seguridad denegó el acceso.', '文件权限或安全检查拒绝访问。', 'رفض إذن الملفات أو فحص الأمان الوصول.'),
    'not_found': ('Workspace or parent directory no longer exists.', 'Çalışma alanı veya üst klasör artık mevcut değil.', 'Arbeitsbereich oder übergeordneter Ordner existiert nicht mehr.', 'Le dossier de travail ou parent n’existe plus.', 'El espacio de trabajo o la carpeta superior ya no existe.', '工作区或父目录已不存在。', 'لم يعد مجلد العمل أو المجلد الأب موجودًا.'),
    'folder_operation_failed': ('Folder operation failed; check the approved root.', 'Klasör işlemi başarısız; onaylı kökü kontrol edin.', 'Ordneraktion fehlgeschlagen; genehmigten Stammordner prüfen.', 'Échec de l’opération ; vérifiez le dossier racine autorisé.', 'Falló la operación; compruebe la raíz aprobada.', '文件夹操作失败；请检查已批准的根目录。', 'فشلت عملية المجلد؛ تحقق من المجلد الجذر المعتمد.'),
}


def localized_folder_status(code: str, language: str = 'en') -> str:
    """Stable machine-readable code followed by short human-facing translation."""
    lang = str(language or 'en').strip().lower().replace('_', '-').split('-')[0]
    aliases = {'turkish':'tr','english':'en','german':'de','french':'fr',
               'spanish':'es','chinese':'zh','arabic':'ar'}
    lang = aliases.get(lang, lang)
    index = _LANGS.index(lang) if lang in _LANGS else 0
    return code + ': ' + _TRANSLATIONS.get(code, _TRANSLATIONS['folder_operation_failed'])[index]


def folder_error_localized(exc: BaseException, language: str = 'en') -> str:
    original = folder_error_reason(exc)
    code = original.split(':', 1)[0]
    if code == 'already_exists':
        code = 'name_collision'  # Existing safe folders are handled as a success before this point.
    return localized_folder_status(code, language)


def existing_approved_folder(workspace: str, relative_path: str, roots, *, check_path):
    """Read-only exact-name / no-reparse validation of an existing target.

    A file collision, case alias, junction, symlink or unsafe workspace cannot be
    reported as a successful no-op, even when mkdir raised FileExistsError.
    """
    from mcptoai_core.safe_subfolders import _parts, plan_inbound_subfolder
    normalized = '/'.join(_parts(relative_path, allow_windows_separators=True))
    target, missing = plan_inbound_subfolder(workspace, normalized, roots, check_path=check_path)
    return target if not missing and target.is_dir() else None
