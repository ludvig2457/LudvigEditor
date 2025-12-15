import sys
import os
import subprocess
import socket
import json
import threading
import zipfile
import tempfile
import shutil
import importlib.util
import traceback
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path
import webbrowser  # Для открытия ссылки на скачивание Git

from PyQt6.QtWidgets import *
from PyQt6.QtGui import (QAction, QKeySequence, QFileSystemModel, QShortcut, 
                         QCursor, QIcon, QFont, QPixmap, QColor, QPalette)
from PyQt6.QtCore import (QUrl, Qt, QDir, QTimer, QThread, pyqtSignal, 
                          QObject, QSettings, QStandardPaths, QSize, 
                          QMimeData, QByteArray, QBuffer, QIODevice)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript

# ===== Конфигурация =====
APP_NAME = "LudvigEditor"
APP_VERSION = "1.0.0" # Текущая версия
UPDATE_URL = "https://github.com/ludvig2457/LudvigEditor/raw/refs/heads/main/update.txt"
SETTINGS = QSettings("Ludvig2457", APP_NAME)

# ===== Папки расширений =====
EXT_DIR = os.path.join(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation), APP_NAME, "extensions")
EXT_INSTALLED = os.path.join(EXT_DIR, "installed")
EXT_MANIFEST = os.path.join(EXT_DIR, "manifest.json")
EXT_STORAGE = os.path.join(EXT_DIR, "storage")
EXT_SCRIPTS = os.path.join(EXT_DIR, "scripts")

for path in [EXT_DIR, EXT_INSTALLED, EXT_STORAGE, EXT_SCRIPTS]:
    os.makedirs(path, exist_ok=True)

# ===== Проверка интернета =====
def check_internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception:
        return False

# ===== Класс манифеста расширения =====
class ExtensionManifest:
    def __init__(self, manifest_path: str):
        self.manifest_path = manifest_path
        self.load()
    
    def load(self):
        """Загружаем манифест из файла"""
        try:
            with open(self.manifest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            data = {}
            print(f"Error loading manifest {self.manifest_path}: {e}")
        
        self.name = data.get('name', 'unknown')
        self.version = data.get('version', '1.0.0')
        self.description = data.get('description', '')
        self.author = data.get('author', 'Unknown')
        self.main = data.get('main', 'main.js')
        self.icon = data.get('icon')
        self.enabled = data.get('enabled', True)
        self.dependencies = data.get('dependencies', {})
        self.contributes = data.get('contributes', {})
        self.activation_events = data.get('activationEvents', [])
        self.extension_dir = os.path.dirname(self.manifest_path)
        
        # Определяем тип расширения
        if self.main.endswith('.js'):
            self.type = 'js'
        elif self.main.endswith('.py'):
            self.type = 'python'
        else:
            self.type = 'unknown'
    
    def save(self):
        """Сохраняем манифест в файл"""
        data = {
            'name': self.name,
            'version': self.version,
            'description': self.description,
            'author': self.author,
            'main': self.main,
            'icon': self.icon,
            'enabled': self.enabled,
            'dependencies': self.dependencies,
            'contributes': self.contributes,
            'activationEvents': self.activation_events
        }
        
        try:
            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving manifest: {e}")
            return False
    
    def get_main_path(self) -> str:
        """Получаем полный путь к главному файлу"""
        return os.path.join(self.extension_dir, self.main)
    
    def get_icon_path(self) -> Optional[str]:
        """Получаем путь к иконке"""
        if self.icon:
            return os.path.join(self.extension_dir, self.icon)
        return None
    
    def to_dict(self) -> dict:
        """Преобразуем в словарь для отображения"""
        return {
            'name': self.name,
            'version': self.version,
            'description': self.description,
            'author': self.author,
            'enabled': self.enabled,
            'type': self.type,
            'path': self.extension_dir,
            'main': self.main
        }

# ===== Менеджер расширений =====
class ExtensionManager(QObject):
    # Сигналы для уведомлений
    extension_loaded = pyqtSignal(str)      # Имя расширения
    extension_unloaded = pyqtSignal(str)    # Имя расширения
    extension_error = pyqtSignal(str, str)  # Имя расширения, ошибка
    extension_installed = pyqtSignal(str)   # Имя расширения
    extension_uninstalled = pyqtSignal(str) # Имя расширения
    
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.extensions: Dict[str, ExtensionManifest] = {}
        self.loaded_extensions: Dict[str, Any] = {}
        self.python_extensions: Dict[str, Any] = {}
        self.js_extensions: Dict[str, str] = {}
        
        self.load_manifest()
        self.scan_extensions()
    
    def load_manifest(self):
        """Загружаем манифест расширений"""
        if os.path.exists(EXT_MANIFEST):
            try:
                with open(EXT_MANIFEST, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for ext_path, ext_data in data.items():
                        if os.path.exists(ext_path):
                            ext = ExtensionManifest(ext_path)
                            self.extensions[ext.name] = ext
            except Exception as e:
                self.editor.log(f"❌ Error loading manifest: {e}")
    
    def save_manifest(self):
        """Сохраняем манифест расширений"""
        data = {}
        for ext in self.extensions.values():
            data[ext.manifest_path] = ext.to_dict()
        
        try:
            with open(EXT_MANIFEST, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            self.editor.log(f"❌ Error saving manifest: {e}")
            return False
    
    def scan_extensions(self):
        """Сканируем папки на наличие расширений"""
        if not os.path.exists(EXT_INSTALLED):
            return []
        
        extensions_found = []
        for item in os.listdir(EXT_INSTALLED):
            ext_path = os.path.join(EXT_INSTALLED, item)
            manifest_path = os.path.join(ext_path, 'package.json')
            
            if os.path.exists(manifest_path):
                try:
                    ext = ExtensionManifest(manifest_path)
                    self.extensions[ext.name] = ext
                    extensions_found.append(ext)
                    self.editor.log(f"🔍 Found extension: {ext.name} v{ext.version}")
                    
                    # Автозагрузка если включено
                    if ext.enabled:
                        self.load_extension(ext.name)
                        
                except Exception as e:
                    self.editor.log(f"❌ Error loading extension {manifest_path}: {e}")
        
        self.save_manifest()
        return extensions_found
    
    def install_extension(self, path: str) -> bool:
        """Устанавливаем расширение из файла или папки"""
        try:
            if os.path.isfile(path) and path.endswith('.zip'):
                return self.install_from_zip(path)
            elif os.path.isfile(path):
                # Одиночный файл (JS или Python)
                return self.install_single_file(path)
            elif os.path.isdir(path):
                # Папка с расширением
                return self.install_from_folder(path)
            else:
                self.editor.log(f"❌ Invalid path: {path}")
                return False
        except Exception as e:
            self.editor.log(f"❌ Installation failed: {e}")
            traceback.print_exc()
            return False
    
    def install_from_zip(self, zip_path: str) -> bool:
        """Устанавливаем из ZIP архива"""
        temp_dir = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            
            # Ищем package.json
            for root, dirs, files in os.walk(temp_dir):
                if 'package.json' in files:
                    success = self.install_from_folder(root)
                    if success:
                        self.editor.log(f"✅ Extension installed from ZIP: {zip_path}")
                        return True
            
            self.editor.log(f"❌ No package.json found in ZIP: {zip_path}")
            return False
            
        except Exception as e:
            self.editor.log(f"❌ Error extracting ZIP: {e}")
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    def install_single_file(self, file_path: str) -> bool:
        """Устанавливаем одиночный файл (JS или Python)"""
        filename = os.path.basename(file_path)
        name, ext = os.path.splitext(filename)
        
        # Ограничиваем имя для безопасности
        name = name.replace(' ', '_').replace('.', '_')[:50]
        
        if ext.lower() == '.js':
            return self._create_js_extension(name, file_path)
        elif ext.lower() == '.py':
            return self._create_python_extension(name, file_path)
        else:
            self.editor.log(f"❌ Unsupported file type: {ext}")
            return False
    
    def _create_js_extension(self, name: str, js_path: str) -> bool:
        """Создаем JS расширение"""
        try:
            ext_dir = os.path.join(EXT_INSTALLED, name)
            os.makedirs(ext_dir, exist_ok=True)
            
            # Читаем JS код
            with open(js_path, 'r', encoding='utf-8') as f:
                js_code = f.read()
            
            # Создаем базовый манифест
            manifest = {
                'name': name,
                'version': '1.0.0',
                'description': f'JavaScript extension: {name}',
                'main': os.path.basename(js_path),
                'author': 'Unknown',
                'enabled': True,
                'contributes': {
                    'commands': [],
                    'menus': {},
                    'views': {}
                }
            }
            
            # Сохраняем манифест
            manifest_path = os.path.join(ext_dir, 'package.json')
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2)
            
            # Копируем JS файл
            shutil.copy2(js_path, os.path.join(ext_dir, os.path.basename(js_path)))
            
            # Загружаем расширение
            ext = ExtensionManifest(manifest_path)
            self.extensions[ext.name] = ext
            self.save_manifest()
            
            if ext.enabled:
                self.load_extension(ext.name)
            
            self.extension_installed.emit(ext.name)
            self.editor.log(f"✅ JS extension installed: {ext.name}")
            return True
            
        except Exception as e:
            self.editor.log(f"❌ Error creating JS extension: {e}")
            return False
    
    def _create_python_extension(self, name: str, py_path: str) -> bool:
        """Создаем Python расширение"""
        try:
            ext_dir = os.path.join(EXT_INSTALLED, name)
            os.makedirs(ext_dir, exist_ok=True)
            
            # Создаем базовый манифест
            manifest = {
                'name': name,
                'version': '1.0.0',
                'description': f'Python extension: {name}',
                'main': os.path.basename(py_path),
                'author': 'Unknown',
                'enabled': True,
                'contributes': {
                    'commands': [],
                    'menus': {},
                    'views': {}
                }
            }
            
            # Сохраняем манифест
            manifest_path = os.path.join(ext_dir, 'package.json')
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2)
            
            # Копируем Python файл
            shutil.copy2(py_path, os.path.join(ext_dir, os.path.basename(py_path)))
            
            # Загружаем расширение
            ext = ExtensionManifest(manifest_path)
            self.extensions[ext.name] = ext
            self.save_manifest()
            
            if ext.enabled:
                self.load_extension(ext.name)
            
            self.extension_installed.emit(ext.name)
            self.editor.log(f"✅ Python extension installed: {ext.name}")
            return True
            
        except Exception as e:
            self.editor.log(f"❌ Error creating Python extension: {e}")
            return False
    
    def install_from_folder(self, folder_path: str) -> bool:
        """Устанавливаем из папки (полное расширение с package.json)"""
        manifest_path = os.path.join(folder_path, 'package.json')
        if not os.path.exists(manifest_path):
            self.editor.log(f"❌ No package.json found in {folder_path}")
            return False
        
        try:
            # Читаем манифест для получения имени
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest_data = json.load(f)
            
            ext_name = manifest_data.get('name', os.path.basename(folder_path))
            dest_dir = os.path.join(EXT_INSTALLED, ext_name)
            
            # Удаляем старую версию если есть
            if os.path.exists(dest_dir):
                shutil.rmtree(dest_dir)
            
            # Копируем всю папку
            shutil.copytree(folder_path, dest_dir)
            
            # Загружаем манифест
            new_manifest_path = os.path.join(dest_dir, 'package.json')
            ext = ExtensionManifest(new_manifest_path)
            self.extensions[ext.name] = ext
            self.save_manifest()
            
            if ext.enabled:
                self.load_extension(ext.name)
            
            self.extension_installed.emit(ext.name)
            self.editor.log(f"✅ Extension installed: {ext.name} v{ext.version}")
            return True
            
        except Exception as e:
            self.editor.log(f"❌ Error installing from folder: {e}")
            traceback.print_exc()
            return False
    
    def load_extension(self, name: str) -> bool:
        """Загружаем расширение"""
        if name not in self.extensions:
            self.editor.log(f"❌ Extension not found: {name}")
            return False
        
        ext = self.extensions[name]
        
        if not ext.enabled:
            self.editor.log(f"⚠️ Extension disabled: {name}")
            return False
        
        if name in self.loaded_extensions:
            self.editor.log(f"⚠️ Extension already loaded: {name}")
            return True
        
        try:
            if ext.type == 'js':
                return self._load_js_extension(ext)
            elif ext.type == 'python':
                return self._load_python_extension(ext)
            else:
                self.editor.log(f"❌ Unknown extension type: {ext.type}")
                return False
                
        except Exception as e:
            self.editor.log(f"❌ Error loading extension {name}: {e}")
            traceback.print_exc()
            self.extension_error.emit(name, str(e))
            return False
    
    def _load_js_extension(self, ext: ExtensionManifest) -> bool:
        """Загружаем JavaScript расширение"""
        main_path = ext.get_main_path()
        if not os.path.exists(main_path):
            self.editor.log(f"❌ Main file not found: {main_path}")
            return False
        
        try:
            with open(main_path, 'r', encoding='utf-8') as f:
                js_code = f.read()
            
            # Сохраняем код расширения
            self.js_extensions[ext.name] = js_code
            
            # Загружаем во все открытые вкладки
            for view in self.editor.get_all_views():
                self._inject_js_to_view(view, ext.name, js_code)
            
            self.loaded_extensions[ext.name] = ext
            self.extension_loaded.emit(ext.name)
            
            self.editor.log(f"✅ JS extension loaded: {ext.name}")
            return True
            
        except Exception as e:
            self.editor.log(f"❌ Error loading JS extension: {e}")
            return False
    
    def _inject_js_to_view(self, view, ext_name: str, js_code: str):
        """Инжектим JS код в WebView"""
        # Создаем безопасную обертку для кода
        wrapped_code = f"""
        (function() {{
            try {{
                // Регистрируем расширение
                if (!window.__ludvigExtensions) {{
                    window.__ludvigExtensions = {{}};
                }}
                
                // Сохраняем оригинальный код
                window.__ludvigExtensions['{ext_name}'] = {json.dumps(js_code)};
                
                // Выполняем код
                {js_code}
                
                console.log('✅ Extension loaded: {ext_name}');
            }} catch (e) {{
                console.error('❌ Extension error ({ext_name}):', e);
            }}
        }})();
        """
        
        # Запускаем код в WebView
        view.page().runJavaScript(wrapped_code)
    
    def _load_python_extension(self, ext: ExtensionManifest) -> bool:
        """Загружаем Python расширение"""
        main_path = ext.get_main_path()
        if not os.path.exists(main_path):
            self.editor.log(f"❌ Main file not found: {main_path}")
            return False
        
        try:
            # Загружаем Python модуль
            module_name = f"ludvig_extension_{ext.name.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(module_name, main_path)
            
            if spec is None:
                self.editor.log(f"❌ Failed to load Python module: {ext.name}")
                return False
            
            module = importlib.util.module_from_spec(spec)
            
            # Добавляем путь к расширению в sys.path
            if ext.extension_dir not in sys.path:
                sys.path.insert(0, ext.extension_dir)
            
            # Добавляем API в модуль
            module.api = self.editor.api
            module.editor = self.editor
            
            # Выполняем модуль
            spec.loader.exec_module(module)
            
            # Вызываем activate если есть
            if hasattr(module, 'activate'):
                module.activate(self.editor.api)
            
            # Сохраняем модуль
            self.python_extensions[ext.name] = module
            self.loaded_extensions[ext.name] = ext
            
            self.extension_loaded.emit(ext.name)
            self.editor.log(f"✅ Python extension loaded: {ext.name}")
            return True
            
        except Exception as e:
            self.editor.log(f"❌ Error loading Python extension: {e}")
            traceback.print_exc()
            return False
    
    def unload_extension(self, name: str) -> bool:
        """Выгружаем расширение"""
        if name not in self.loaded_extensions:
            return False
        
        ext = self.loaded_extensions[name]
        
        try:
            if ext.type == 'js':
                # Удаляем из всех вкладок
                for view in self.editor.get_all_views():
                    view.page().runJavaScript(f"""
                        if (window.__ludvigExtensions && window.__ludvigExtensions['{name}']) {{
                            delete window.__ludvigExtensions['{name}'];
                            console.log('Extension unloaded: {name}');
                        }}
                    """)
                
                # Удаляем из кэша
                if name in self.js_extensions:
                    del self.js_extensions[name]
                    
            elif ext.type == 'python':
                # Вызываем deactivate если есть
                if name in self.python_extensions:
                    module = self.python_extensions[name]
                    if hasattr(module, 'deactivate'):
                        module.deactivate()
                    del self.python_extensions[name]
            
            # Удаляем из загруженных
            del self.loaded_extensions[name]
            self.extension_unloaded.emit(name)
            
            self.editor.log(f"✅ Extension unloaded: {name}")
            return True
            
        except Exception as e:
            self.editor.log(f"❌ Error unloading extension: {e}")
            return False
    
    def toggle_extension(self, name: str) -> bool:
        """Включаем/выключаем расширение"""
        if name not in self.extensions:
            return False
        
        ext = self.extensions[name]
        ext.enabled = not ext.enabled
        ext.save()
        
        if ext.enabled:
            success = self.load_extension(name)
        else:
            success = self.unload_extension(name)
        
        if success:
            status = "enabled" if ext.enabled else "disabled"
            self.editor.log(f"🔧 Extension {name} {status}")
        
        return success
    
    def uninstall_extension(self, name: str) -> bool:
        """Удаляем расширение полностью"""
        if name not in self.extensions:
            return False
        
        ext = self.extensions[name]
        
        # Выгружаем если загружено
        if name in self.loaded_extensions:
            self.unload_extension(name)
        
        # Удаляем папку расширения
        ext_dir = ext.extension_dir
        try:
            if os.path.exists(ext_dir) and ext_dir.startswith(EXT_INSTALLED):
                shutil.rmtree(ext_dir, ignore_errors=True)
            
            # Удаляем из списков
            del self.extensions[name]
            if name in self.loaded_extensions:
                del self.loaded_extensions[name]
            if name in self.js_extensions:
                del self.js_extensions[name]
            if name in self.python_extensions:
                del self.python_extensions[name]
            
            # Сохраняем манифест
            self.save_manifest()
            
            self.extension_uninstalled.emit(name)
            self.editor.log(f"🗑 Extension uninstalled: {name}")
            return True
            
        except Exception as e:
            self.editor.log(f"❌ Error uninstalling extension: {e}")
            return False
    
    def get_extension_list(self) -> List[dict]:
        """Получаем список всех расширений"""
        result = []
        for name, ext in self.extensions.items():
            ext_dict = ext.to_dict()
            ext_dict['loaded'] = name in self.loaded_extensions
            ext_dict['has_errors'] = False  # Можно добавить проверку ошибок
            result.append(ext_dict)
        
        # Сортируем по имени
        result.sort(key=lambda x: x['name'].lower())
        return result
    
    def reload_all_extensions(self):
        """Перезагружаем все расширения"""
        loaded = list(self.loaded_extensions.keys())
        for name in loaded:
            self.unload_extension(name)
        
        for name, ext in self.extensions.items():
            if ext.enabled:
                self.load_extension(name)
    
    def reload_extension(self, name: str) -> bool:
        """Перезагружаем конкретное расширение"""
        if name not in self.extensions:
            return False
        
        was_loaded = name in self.loaded_extensions
        
        if was_loaded:
            self.unload_extension(name)
        
        if self.extensions[name].enabled:
            return self.load_extension(name)
        
        return True
    
# ===== GIT Менеджер (без зависимостей) =====
class GitManager(QObject):
    """Менеджер Git интеграции с graceful degradation"""
    
    # Сигналы для UI
    git_status_changed = pyqtSignal(str, dict)
    git_branch_changed = pyqtSignal(str, str)
    git_commit_made = pyqtSignal(str, str)
    git_error = pyqtSignal(str, str)
    git_not_installed = pyqtSignal()  # Новый сигнал
    
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.git_installed = False
        self.git_path = None
        self.user_declined_git = False  # Флаг, что пользователь отказался
        self._init_git()
    
    def _init_git(self):
        """Инициализация Git (без ошибок)"""
        try:
            self.git_path = self._find_git_executable()
            self.git_installed = self.git_path is not None
        except:
            self.git_installed = False
    
    def _find_git_executable(self):
        """Находим путь к git.exe"""
        possible_paths = [
            'git',  # Если в PATH
            'C:\\Program Files\\Git\\bin\\git.exe',
            'C:\\Program Files (x86)\\Git\\bin\\git.exe',
            'C:\\Program Files\\Git\\cmd\\git.exe',
            'C:\\Users\\' + os.getlogin() + '\\AppData\\Local\\Programs\\Git\\bin\\git.exe',
        ]
        
        for path in possible_paths:
            try:
                result = subprocess.run(
                    [path, '--version'],
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=2
                )
                if result.returncode == 0 and 'git version' in result.stdout:
                    return path
            except:
                continue
        
        return None
    
    def _run_git_command(self, cwd: str, *args) -> dict:
        """Выполняет Git команду с обработкой отсутствия Git"""
        if not self.git_installed:
            # Если пользователь еще не отказывался, предлагаем установить
            if not self.user_declined_git:
                self._offer_git_installation()
            return {'success': False, 'error': 'Git не установлен'}
        
        try:
            cmd = [self.git_path] + list(args)
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=30
            )
            
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout.strip(),
                'stderr': result.stderr.strip(),
                'returncode': result.returncode
            }
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Таймаут выполнения команды'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _offer_git_installation(self):
        """Предлагаем пользователю установить Git"""
        reply = QMessageBox.question(
            self.editor,
            "Git не установлен",
            "Для работы с Git требуется установить Git.\n\n"
            "Хотите открыть страницу скачивания Git?",
            QMessageBox.StandardButton.Yes | 
            QMessageBox.StandardButton.No |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # Открываем страницу скачивания Git
            webbrowser.open("https://git-scm.com/download/win")
            
            # Спрашиваем после открытия страницы
            QMessageBox.information(
                self.editor,
                "Установка Git",
                "После установки Git:\n"
                "1. Перезапустите программу\n"
                "2. Убедитесь, что Git добавлен в PATH\n"
                "3. Функции Git будут доступны автоматически"
            )
        elif reply == QMessageBox.StandardButton.No:
            self.user_declined_git = True
            self.editor.log("⚠️ Пользователь отказался от установки Git. Функции Git отключены.", "warning")
    
    def check_git_available(self, show_message=False) -> bool:
        """Проверяем доступность Git с опциональным сообщением"""
        if not self.git_installed and show_message and not self.user_declined_git:
            self._offer_git_installation()
        return self.git_installed
    
    def get_repo_root(self, path: str) -> Optional[str]:
        """Находим корень Git репозитория (работает даже без Git)"""
        try:
            current = Path(path)
            
            # Если это файл, берем его папку
            if current.is_file():
                current = current.parent
            
            while current != current.parent:
                git_dir = current / '.git'
                if git_dir.exists():
                    return str(current)
                current = current.parent
        except:
            pass
        
        return None
    
    # Все методы ниже проверяют доступность Git перед выполнением
    
    def init_repo(self, path: str) -> bool:
        """Инициализируем новый репозиторий"""
        if not self.check_git_available(show_message=True):
            return False
        
        result = self._run_git_command(path, 'init')
        if result['success']:
            self.editor.log(f"✅ Git репозиторий создан: {path}", "info")
        else:
            self.git_error.emit(path, result['error'])
        return result['success']
    
    def get_status(self, path: str) -> dict:
        """Получаем статус Git"""
        repo_root = self.get_repo_root(path)
        if not repo_root:
            return {'is_git': False}
        
        if not self.check_git_available():
            return {'is_git': True, 'git_available': False}
        
        status_result = self._run_git_command(repo_root, 'status', '--porcelain')
        branch_result = self._run_git_command(repo_root, 'branch', '--show-current')
        
        if not status_result['success'] or not branch_result['success']:
            return {'is_git': True, 'git_available': False}
        
        status = {
            'is_git': True,
            'git_available': True,
            'repo_root': repo_root,
            'branch': branch_result['stdout'] if branch_result['stdout'] else 'unknown',
            'has_changes': bool(status_result['stdout']),
        }
        
        # Парсим статус файлов
        changed_files = []
        untracked_files = []
        
        for line in status_result['stdout'].split('\n'):
            if not line.strip():
                continue
            
            status_code = line[:2].strip()
            file_path = line[3:]
            
            if status_code == '??':
                untracked_files.append(file_path)
            else:
                change_type = 'modified'
                staged = status_code[0] != ' '
                if status_code[1] == 'M':
                    change_type = 'modified'
                elif status_code[1] == 'A':
                    change_type = 'added'
                elif status_code[1] == 'D':
                    change_type = 'deleted'
                elif status_code[1] == 'R':
                    change_type = 'renamed'
                
                changed_files.append({
                    'path': file_path,
                    'change_type': change_type,
                    'staged': staged
                })
        
        status['changed_files'] = changed_files
        status['untracked_files'] = untracked_files
        
        # Отправляем сигнал
        self.git_status_changed.emit(path, status)
        return status
    
    def stage_file(self, path: str, file_path: str) -> bool:
        """Добавляем файл в stage"""
        if not self.check_git_available(show_message=True):
            return False
        
        repo_root = self.get_repo_root(path)
        if not repo_root:
            return False
        
        # Делаем путь относительным
        rel_path = os.path.relpath(file_path, repo_root) if os.path.isabs(file_path) else file_path
        result = self._run_git_command(repo_root, 'add', rel_path)
        
        if result['success']:
            self.editor.log(f"📦 Staged: {rel_path}", "info")
        else:
            self.git_error.emit(path, result['error'])
        
        return result['success']
    
    def commit(self, path: str, message: str) -> bool:
        """Создаём коммит"""
        if not self.check_git_available(show_message=True):
            return False
        
        repo_root = self.get_repo_root(path)
        if not repo_root:
            return False
        
        result = self._run_git_command(repo_root, 'commit', '-m', message)
        
        if result['success']:
            # Получаем хэш последнего коммита
            hash_result = self._run_git_command(repo_root, 'rev-parse', '--short', 'HEAD')
            commit_hash = hash_result['stdout'] if hash_result['success'] else 'unknown'
            self.git_commit_made.emit(path, commit_hash)
            self.editor.log(f"💾 Коммит создан: {message}", "success")
        else:
            self.git_error.emit(path, result['error'])
        
        return result['success']
    
    def create_branch(self, path: str, branch_name: str) -> bool:
        """Создаём новую ветку"""
        if not self.check_git_available(show_message=True):
            return False
        
        repo_root = self.get_repo_root(path)
        if not repo_root:
            return False
        
        result = self._run_git_command(repo_root, 'branch', branch_name)
        
        if result['success']:
            self.editor.log(f"🌿 Ветка создана: {branch_name}", "info")
        else:
            self.git_error.emit(path, result['error'])
        
        return result['success']
    
    def checkout_branch(self, path: str, branch_name: str) -> bool:
        """Переключаемся на ветку"""
        if not self.check_git_available(show_message=True):
            return False
        
        repo_root = self.get_repo_root(path)
        if not repo_root:
            return False
        
        result = self._run_git_command(repo_root, 'checkout', branch_name)
        
        if result['success']:
            self.git_branch_changed.emit(path, branch_name)
            self.editor.log(f"🔄 Переключился на ветку: {branch_name}", "info")
        else:
            self.git_error.emit(path, result['error'])
        
        return result['success']
    
    def pull(self, path: str) -> dict:
        """Pull из удалённого репозитория"""
        if not self.check_git_available(show_message=True):
            return {'success': False, 'error': 'Git не установлен'}
        
        repo_root = self.get_repo_root(path)
        if not repo_root:
            return {'success': False, 'error': 'No repository'}
        
        result = self._run_git_command(repo_root, 'pull')
        
        if result['success']:
            self.editor.log(f"⬇️ Pull выполнен", "info")
        else:
            self.editor.log(f"❌ Pull ошибка: {result['error']}", "error")
        
        return result
    
    def push(self, path: str) -> dict:
        """Push в удалённый репозиторий"""
        if not self.check_git_available(show_message=True):
            return {'success': False, 'error': 'Git не установлен'}
        
        repo_root = self.get_repo_root(path)
        if not repo_root:
            return {'success': False, 'error': 'No repository'}
        
        result = self._run_git_command(repo_root, 'push')
        
        if result['success']:
            self.editor.log(f"⬆️ Push выполнен", "info")
        else:
            self.editor.log(f"❌ Push ошибка: {result['error']}", "error")
        
        return result
    
    def get_branches(self, path: str) -> List[str]:
        """Получаем список веток"""
        if not self.check_git_available():
            return []
        
        repo_root = self.get_repo_root(path)
        if not repo_root:
            return []
        
        result = self._run_git_command(repo_root, 'branch', '--list')
        if not result['success']:
            return []
        
        branches = []
        for line in result['stdout'].split('\n'):
            if line.strip():
                branch = line.strip().lstrip('* ')
                if branch:
                    branches.append(branch)
        
        return branches
    
    def get_history(self, path: str, limit: int = 20) -> List[dict]:
        """Получаем историю коммитов"""
        if not self.check_git_available():
            return []
        
        repo_root = self.get_repo_root(path)
        if not repo_root:
            return []
        
        result = self._run_git_command(
            repo_root, 
            'log', 
            f'--max-count={limit}',
            '--pretty=format:%H|%an|%ad|%s',
            '--date=short'
        )
        
        if not result['success']:
            return []
        
        history = []
        for line in result['stdout'].split('\n'):
            if not line.strip():
                continue
            
            try:
                commit_hash, author, date, message = line.split('|', 3)
                history.append({
                    'hash': commit_hash[:7],
                    'message': message.strip(),
                    'author': author.strip(),
                    'date': date.strip(),
                    'files': []
                })
            except:
                continue
        
        return history

# ===== Менеджер обновлений =====
class UpdateManager(QObject):
    """Менеджер проверки обновлений"""
    
    update_available = pyqtSignal(str, str)  # Новая версия, описание
    update_error = pyqtSignal(str)  # Ошибка
    update_downloaded = pyqtSignal(str)  # Файл обновления скачан
    
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.last_check = None
        self.check_on_startup = True
        self.auto_check_interval = 24 * 60 * 60 * 1000  # 24 часа в миллисекундах
    
    def check_for_updates(self, auto_check=False):
        """Проверяем наличие обновлений"""
        if not check_internet():
            if not auto_check:
                QMessageBox.warning(self.editor, "Нет интернета", 
                                  "Проверка обновлений требует подключения к интернету.")
            return
        
        # Показываем статус
        if not auto_check:
            self.editor.statusBar().showMessage("🔍 Проверка обновлений...")
        
        # Запускаем в отдельном потоке
        thread = threading.Thread(target=self._check_update_thread, args=(auto_check,))
        thread.daemon = True
        thread.start()
    
    def _check_update_thread(self, auto_check=False):
        """Поток для проверки обновлений"""
        try:
            # Проверяем наличие urllib
            try:
                import urllib.request
                import urllib.error
            except ImportError:
                if not auto_check:
                    QTimer.singleShot(0, lambda: self._show_check_error(
                        "Библиотека urllib недоступна. Установите Python с полным набором библиотек."
                    ))
                return
            
            # Загружаем файл обновлений
            req = urllib.request.Request(UPDATE_URL)
            req.add_header('User-Agent', 'LudvigEditor Update Checker')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode('utf-8').strip()
            
            # Парсим файл обновлений
            lines = content.split('\n')
            latest_version = None
            description = ""
            
            for line in lines:
                if '-' in line:
                    version_part, desc_part = line.split('-', 1)
                    version = version_part.strip()
                    desc = desc_part.strip()
                    
                    # Проверяем формат версии
                    if self._is_valid_version(version):
                        latest_version = version
                        description = desc
                        break
            
            if latest_version and self._is_newer_version(latest_version, APP_VERSION):
                # Обновление доступно
                QTimer.singleShot(0, lambda: self._show_update_available(
                    latest_version, description, auto_check
                ))
            elif not auto_check:
                QTimer.singleShot(0, lambda: self._show_no_updates())
            
            # Сохраняем время последней проверки
            self.last_check = datetime.now()
            
        except urllib.error.URLError as e:
            if not auto_check:
                QTimer.singleShot(0, lambda: self._show_network_error(e))
        except Exception as e:
            if not auto_check:
                QTimer.singleShot(0, lambda: self._show_check_error(e))
        finally:
            QTimer.singleShot(0, lambda: self.editor.statusBar().clearMessage())
    
    def _is_valid_version(self, version: str) -> bool:
        """Проверяем корректность формата версии"""
        try:
            parts = version.split('.')
            if len(parts) != 3:
                return False
            for part in parts:
                int(part)  # Проверяем что это числа
            return True
        except:
            return False
    
    def _is_newer_version(self, new_version: str, current_version: str) -> bool:
        """Сравниваем версии"""
        try:
            new_parts = list(map(int, new_version.split('.')))
            current_parts = list(map(int, current_version.split('.')))
            
            for i in range(3):
                if new_parts[i] > current_parts[i]:
                    return True
                elif new_parts[i] < current_parts[i]:
                    return False
            return False  # Версии равны
        except:
            return False
    
    def _show_update_available(self, new_version: str, description: str, auto_check: bool):
        """Показываем уведомление об обновлении"""
        message = f"""
        Доступно обновление!
        
        Текущая версия: {APP_VERSION}
        Новая версия: {new_version}
        
        Описание:
        {description}
        
        Хотите скачать и установить обновление?
        """
        
        if auto_check:
            # Для авто-проверки показываем неблокирующее уведомление
            self.editor.log(f"🔄 Доступно обновление {new_version}: {description}", "info")
            
            # Можно показать сообщение в статус баре
            self.editor.statusBar().showMessage(
                f"🔄 Доступно обновление {new_version}. Нажмите 'Справка → Проверить обновления'", 
                10000  # 10 секунд
            )
        else:
            # Для ручной проверки показываем диалог
            reply = QMessageBox.question(
                self.editor, "Доступно обновление", message,
                QMessageBox.StandardButton.Yes | 
                QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Ignore,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.download_update(new_version)
            elif reply == QMessageBox.StandardButton.Ignore:
                self._ignore_version(new_version)
    
    def _show_no_updates(self):
        """Показываем сообщение об отсутствии обновлений"""
        QMessageBox.information(
            self.editor, "Обновления не найдены",
            f"У вас установлена последняя версия ({APP_VERSION})."
        )
    
    def _show_network_error(self, error):
        """Показываем ошибку сети"""
        QMessageBox.warning(
            self.editor, "Ошибка сети",
            f"Не удалось проверить обновления:\n\n{error}"
        )
    
    def _show_check_error(self, error):
        """Показываем ошибку проверки"""
        QMessageBox.critical(
            self.editor, "Ошибка проверки",
            f"Ошибка при проверке обновлений:\n\n{error}"
        )
    
    def _ignore_version(self, version: str):
        """Игнорируем эту версию"""
        SETTINGS.setValue(f"ignored_version_{version}", True)
        self.editor.log(f"Версия {version} проигнорирована", "info")
    
    def download_update(self, version: str):
        """Скачиваем обновление"""
        # URL для скачивания EXE файла
        download_url = f"https://github.com/ludvig2457/LudvigEditor/releases/download/v{version}/LudvigEditor_{version}.exe"
        
        # Предлагаем имя файла
        suggested_name = f"LudvigEditor_{version}.exe"
        
        # Показываем диалог сохранения
        save_path, _ = QFileDialog.getSaveFileName(
            self.editor, "Скачать обновление",
            suggested_name,
            "Executable Files (*.exe);;All Files (*.*)"
        )
        
        if not save_path:
            return
        
        # Проверяем наличие urllib
        try:
            import urllib.request
            # Запускаем скачивание в отдельном потоке
            self.editor.statusBar().showMessage(f"⬇️ Скачивание обновления {version}...")
            
            thread = threading.Thread(target=self._download_thread, args=(download_url, save_path, version))
            thread.daemon = True
            thread.start()
        except ImportError:
            # Если urllib недоступен, предлагаем открыть ссылку в браузере
            reply = QMessageBox.question(
                self.editor, "Библиотека не найдена",
                f"Библиотека urllib недоступна.\n\n"
                f"Хотите открыть ссылку в браузере для скачивания?\n\n"
                f"{download_url}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                webbrowser.open(download_url)
    
    def _download_thread(self, url: str, save_path: str, version: str):
        """Поток для скачивания"""
        try:
            import urllib.request
            
            def progress_hook(count, block_size, total_size):
                if total_size > 0:
                    percent = min(100, int(count * block_size * 100 / total_size))
                    QTimer.singleShot(0, lambda: self._update_progress(percent, version))
            
            urllib.request.urlretrieve(url, save_path, progress_hook)
            
            QTimer.singleShot(0, lambda: self._download_complete(save_path, version))
            
        except Exception as e:
            QTimer.singleShot(0, lambda: self._download_error(e))
    
    def _update_progress(self, percent: int, version: str):
        """Обновляем прогресс в статус баре"""
        self.editor.statusBar().showMessage(f"⬇️ Скачивание {version}: {percent}%")
    
    def _download_complete(self, save_path: str, version: str):
        """Скачивание завершено"""
        self.editor.statusBar().showMessage(f"✅ Обновление {version} скачано", 5000)
        self.update_downloaded.emit(save_path)
        
        reply = QMessageBox.question(
            self.editor, "Скачивание завершено",
            f"Обновление {version} скачано:\n{save_path}\n\n"
            "Что вы хотите сделать?",
            QMessageBox.StandardButton.Open | 
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Open
        )
        
        if reply == QMessageBox.StandardButton.Open:
            # Запускаем установщик
            try:
                if os.name == 'nt':  # Windows
                    subprocess.Popen([save_path])
                else:
                    QMessageBox.information(self.editor, "Запуск", 
                                        "Запустите скачанный файл вручную.")
            except Exception as e:
                QMessageBox.warning(self.editor, "Ошибка запуска", 
                                f"Не удалось запустить установщик:\n{e}")
        
        elif reply == QMessageBox.StandardButton.Save:
            # Просто сохраняем файл, ничего не делаем
            pass
    
    def _download_error(self, error):
        """Ошибка скачивания"""
        self.editor.statusBar().showMessage("❌ Ошибка скачивания", 5000)
        QMessageBox.critical(
            self.editor, "Ошибка скачивания",
            f"Не удалось скачать обновление:\n\n{error}"
        )
    
    def setup_auto_check(self):
        """Настраиваем автоматическую проверку обновлений"""
        # Проверяем настройки
        if self.check_on_startup:
            # Проверяем при запуске (с задержкой 3 секунды)
            QTimer.singleShot(3000, lambda: self.check_for_updates(auto_check=True))
        
        # Настраиваем периодическую проверку
        self.auto_check_timer = QTimer()
        self.auto_check_timer.timeout.connect(
            lambda: self.check_for_updates(auto_check=True)
        )
        self.auto_check_timer.start(self.auto_check_interval)

# ===== API для расширений =====
class EditorAPI(QObject):
    """API который предоставляется расширениям"""
    
    # Сигналы для расширений
    file_opened = pyqtSignal(str)
    file_saved = pyqtSignal(str)
    file_closed = pyqtSignal(str)
    editor_ready = pyqtSignal()
    
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.extensions = editor.ext_manager
    
    def log(self, message: str, level: str = "info"):
        """Логирование в терминал редактора"""
        self.editor.log(message, level)
    
    def show_message(self, message: str, title: str = "Message", 
                     icon: str = "information"):
        """Показать диалоговое сообщение"""
        if icon == "information":
            QMessageBox.information(self.editor, title, message)
        elif icon == "warning":
            QMessageBox.warning(self.editor, title, message)
        elif icon == "critical":
            QMessageBox.critical(self.editor, title, message)
        else:
            QMessageBox.information(self.editor, title, message)
    
    def get_current_file(self) -> Optional[str]:
        """Получить путь к текущему открытому файлу"""
        return self.editor.get_current_file()
    
    def get_current_code(self) -> str:
        """Получить код из текущего редактора"""
        return self.editor.get_current_code()
    
    def set_current_code(self, code: str):
        """Установить код в текущем редакторе"""
        self.editor.set_current_code(code)
    
    def save_current_file(self):
        """Сохранить текущий файл"""
        self.editor.save_current()
    
    def run_current_file(self):
        """Запустить текущий файл"""
        self.editor.run_code()
    
    def open_file(self, path: str):
        """Открыть файл в редакторе"""
        self.editor.open_tab(path)
    
    def create_file(self, path: str, content: str = ""):
        """Создать новый файл"""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.editor.open_tab(path)
            return True
        except Exception as e:
            self.log(f"❌ Error creating file: {e}", "error")
            return False
    
    def execute_command(self, command: str, cwd: str = None) -> dict:
        """Выполнить команду в терминале"""
        try:
            if cwd is None:
                cwd = os.getcwd()
            
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            
            return {
                'success': result.returncode == 0,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'returncode': result.returncode
            }
        except Exception as e:
            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'returncode': -1
            }
    
    def register_command(self, command_id: str, title: str, 
                         callback: Callable, icon: str = ""):
        """Зарегистрировать команду в редакторе"""
        # TODO: Реализовать систему команд
        self.log(f"Command registered: {command_id} - {title}")
        return True
    
    def add_menu_item(self, menu_path: str, title: str, 
                      callback: Callable, shortcut: str = ""):
        """Добавить пункт в меню"""
        # TODO: Реализовать добавление в меню
        self.log(f"Menu item added: {menu_path}/{title}")
        return True
    
    def add_toolbar_button(self, icon: str, tooltip: str, 
                           callback: Callable):
        """Добавить кнопку в тулбар"""
        # TODO: Реализовать добавление кнопок
        self.log(f"Toolbar button added: {tooltip}")
        return True
    
    def get_settings(self, key: str, default=None):
        """Получить значение настройки"""
        return SETTINGS.value(key, default)
    
    def set_settings(self, key: str, value):
        """Установить значение настройки"""
        SETTINGS.setValue(key, value)
    
    def show_status_message(self, message: str, timeout: int = 3000):
        """Показать сообщение в статус баре"""
        self.editor.statusBar().showMessage(message, timeout)
    
    def create_webview(self, html: str = "") -> QWebEngineView:
        """Создать новый WebView (для расширений с UI)"""
        view = QWebEngineView()
        if html:
            view.setHtml(html)
        return view

# ===== Welcome Screen =====
class WelcomeScreen(QWidget):
    def __init__(self, open_file_cb, open_folder_cb, open_extensions_cb):
        super().__init__()
        self.setup_ui(open_file_cb, open_folder_cb, open_extensions_cb)
    
    def setup_ui(self, open_file_cb, open_folder_cb, open_extensions_cb):
        self.setStyleSheet("""
            QWidget { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #4b2fbf, stop:0.5 #2b1a55, stop:1 #14142e); 
                color: white; 
            }
            QPushButton { 
                background: rgba(255, 255, 255, 0.12); 
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 12px; 
                padding: 16px 24px; 
                font-size: 15px; 
                font-weight: 500;
                min-width: 200px;
            }
            QPushButton:hover { 
                background: rgba(255, 255, 255, 0.22); 
                border-color: rgba(255, 255, 255, 0.3);
            }
            QLabel { 
                color: white; 
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(24)
        
        # Заголовок
        title = QLabel("⚡ LudvigEditor")
        title.setStyleSheet("""
            font-size: 48px; 
            font-weight: 700; 
            margin-bottom: 8px;
            background: linear-gradient(90deg, #9b5de5, #f15bb5, #00bbf9);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        """)
        
        subtitle = QLabel("VS Code style • Web + PyQt6 • Full Extensions Support")
        subtitle.setStyleSheet("font-size: 16px; opacity: 0.8; margin-bottom: 32px;")
        
        # Кнопки
        btn_open = QPushButton("📂 Open File")
        btn_folder = QPushButton("📁 Open Folder")
        btn_extensions = QPushButton("🧩 Extensions Manager")
        
        btn_open.clicked.connect(open_file_cb)
        btn_folder.clicked.connect(open_folder_cb)
        btn_extensions.clicked.connect(open_extensions_cb)
        
        # Статистика
        stats_frame = QFrame()
        stats_frame.setStyleSheet("""
            QFrame {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 12px;
                padding: 16px;
                margin-top: 24px;
            }
        """)
        stats_layout = QVBoxLayout(stats_frame)
        stats_title = QLabel("Editor Stats")
        stats_title.setStyleSheet("font-size: 14px; font-weight: 600; margin-bottom: 12px;")
        stats_layout.addWidget(stats_title)
        
        # TODO: Добавить статистику
        
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(btn_open)
        layout.addWidget(btn_folder)
        layout.addWidget(btn_extensions)
        layout.addWidget(stats_frame)
        
        layout.addStretch()

# ===== Расширенный виджет расширений =====
class ExtensionsWidget(QWidget):
    def __init__(self, ext_manager):
        super().__init__()
        self.ext_manager = ext_manager
        self.setup_ui()
        
    def setup_ui(self):
        self.setStyleSheet("""
            QWidget { 
                background: #1c1c3c; 
                color: white; 
            }
            QListWidget { 
                background: #16172e; 
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            }
            QListWidget::item:selected {
                background: rgba(91, 60, 196, 0.3);
                border-radius: 6px;
            }
            QPushButton { 
                background: #3f2b96; 
                border: none; 
                border-radius: 8px; 
                padding: 10px 16px; 
                color: white; 
                font-weight: 500;
            }
            QPushButton:hover { 
                background: #5b3cc4; 
            }
            QPushButton:disabled {
                background: #2a1d66;
                color: rgba(255, 255, 255, 0.5);
            }
            QLineEdit, QComboBox {
                background: rgba(255, 255, 255, 0.1);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                padding: 8px 12px;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #9b5de5;
                outline: none;
            }
            QLabel {
                color: #dcd7ff;
            }
            QTabWidget::pane {
                border: none;
                background: transparent;
            }
            QTabBar::tab {
                background: rgba(255, 255, 255, 0.1);
                color: white;
                padding: 10px 20px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: rgba(91, 60, 196, 0.8);
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background: rgba(91, 60, 196, 0.5);
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        # Панель инструментов
        toolbar = QHBoxLayout()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search extensions...")
        self.search_input.textChanged.connect(self.filter_extensions)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Enabled", "Disabled", "JavaScript", "Python"])
        self.filter_combo.currentTextChanged.connect(self.filter_extensions)
        
        btn_install = QPushButton("📦 Install")
        btn_install.clicked.connect(self.install_extension)
        
        btn_reload = QPushButton("🔄 Reload All")
        btn_reload.clicked.connect(self.reload_all)
        
        btn_market = QPushButton("🌐 Marketplace")
        btn_market.clicked.connect(self.open_marketplace)
        
        toolbar.addWidget(QLabel("Search:"))
        toolbar.addWidget(self.search_input, 1)
        toolbar.addWidget(QLabel("Filter:"))
        toolbar.addWidget(self.filter_combo)
        toolbar.addWidget(btn_install)
        toolbar.addWidget(btn_reload)
        toolbar.addWidget(btn_market)
        
        layout.addLayout(toolbar)
        
        # Список расширений
        self.ext_list = QListWidget()
        self.ext_list.itemClicked.connect(self.on_extension_selected)
        self.ext_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ext_list.customContextMenuRequested.connect(self.show_context_menu)
        
        layout.addWidget(self.ext_list)
        
        # Информационная панель
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background: rgba(0, 0, 0, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 16px;
            }
        """)
        info_layout = QVBoxLayout(info_frame)
        
        self.info_label = QLabel("Select an extension to view details")
        self.info_label.setStyleSheet("font-size: 14px;")
        self.info_label.setWordWrap(True)
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        self.details_text.setStyleSheet("""
            QTextEdit {
                background: transparent;
                border: none;
                font-family: 'Consolas', monospace;
                font-size: 12px;
                color: #b0b0ff;
            }
        """)
        
        info_layout.addWidget(self.info_label)
        info_layout.addWidget(self.details_text)
        
        layout.addWidget(info_frame)
        
        # Загружаем список
        self.refresh_list()
    
    def refresh_list(self):
        """Обновляем список расширений"""
        self.ext_list.clear()
        extensions = self.ext_manager.get_extension_list()
        
        for ext in extensions:
            item = QListWidgetItem()
            
            # Иконка статуса
            if ext['loaded']:
                status_icon = "✅"
                status_text = "Enabled"
            else:
                if ext['enabled']:
                    status_icon = "⚠️"
                    status_text = "Error"
                else:
                    status_icon = "❌"
                    status_text = "Disabled"
            
            # Иконка типа
            if ext['type'] == 'js':
                type_icon = "🧩"
                type_text = "JS"
            elif ext['type'] == 'python':
                type_icon = "🐍"
                type_text = "Python"
            else:
                type_icon = "❓"
                type_text = "Unknown"
            
            item.setText(f"{status_icon} {type_icon} {ext['name']} v{ext['version']}")
            item.setData(Qt.ItemDataRole.UserRole, ext)
            
            # Цвет в зависимости от статуса
            if not ext['enabled']:
                item.setForeground(QColor(100, 100, 100))
            elif not ext['loaded'] and ext['enabled']:
                item.setForeground(QColor(255, 165, 0))  # Оранжевый для ошибок
            
            self.ext_list.addItem(item)
    
    def filter_extensions(self):
        """Фильтруем расширения по поиску и типу"""
        search_text = self.search_input.text().lower()
        filter_type = self.filter_combo.currentText()
        
        for i in range(self.ext_list.count()):
            item = self.ext_list.item(i)
            ext = item.data(Qt.ItemDataRole.UserRole)
            
            show = True
            
            # Фильтр по поиску
            if search_text:
                if search_text not in ext['name'].lower() and \
                   search_text not in ext['description'].lower() and \
                   search_text not in ext['author'].lower():
                    show = False
            
            # Фильтр по типу
            if filter_type == "Enabled" and not ext['loaded']:
                show = False
            elif filter_type == "Disabled" and ext['loaded']:
                show = False
            elif filter_type == "JavaScript" and ext['type'] != 'js':
                show = False
            elif filter_type == "Python" and ext['type'] != 'python':
                show = False
            
            item.setHidden(not show)
    
    def on_extension_selected(self, item):
        """Обработка выбора расширения"""
        ext = item.data(Qt.ItemDataRole.UserRole)
        
        # Обновляем информацию
        self.info_label.setText(f"""
        <b>{ext['name']}</b> v{ext['version']}<br>
        <i>{ext['description']}</i><br>
        Author: {ext['author']} • Type: {ext['type']}<br>
        Status: {'✅ Enabled' if ext['loaded'] else '❌ Disabled'}
        """)
        
        # Показываем детали
        details = f"""Path: {ext['path']}
Main file: {ext['main']}
Type: {ext['type']}
Enabled: {ext['enabled']}
Loaded: {ext['loaded']}

Dependencies: {json.dumps(ext.get('dependencies', {}), indent=2)}
"""
        self.details_text.setText(details)
    
    def show_context_menu(self, position):
        """Показываем контекстное меню для расширения"""
        item = self.ext_list.itemAt(position)
        if not item:
            return
        
        ext = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu()
        
        # Основные действия
        if ext['loaded']:
            disable_action = menu.addAction("🚫 Disable")
            disable_action.triggered.connect(lambda: self.toggle_extension(ext['name']))
        else:
            enable_action = menu.addAction("✅ Enable")
            enable_action.triggered.connect(lambda: self.toggle_extension(ext['name']))
        
        reload_action = menu.addAction("🔄 Reload")
        reload_action.triggered.connect(lambda: self.reload_extension(ext['name']))
        
        menu.addSeparator()
        
        # Дополнительные действия
        open_folder_action = menu.addAction("📁 Open Folder")
        open_folder_action.triggered.connect(lambda: self.open_extension_folder(ext['path']))
        
        menu.addSeparator()
        
        # Опасные действия
        uninstall_action = menu.addAction("🗑 Uninstall")
        uninstall_action.triggered.connect(lambda: self.uninstall_extension(ext['name']))
        
        menu.exec(self.ext_list.mapToGlobal(position))
    
    def toggle_extension(self, name: str):
        """Включаем/выключаем расширение"""
        self.ext_manager.toggle_extension(name)
        self.refresh_list()
        self.clear_selection()
    
    def reload_extension(self, name: str):
        """Перезагружаем расширение"""
        self.ext_manager.reload_extension(name)
        self.refresh_list()
        self.clear_selection()
    
    def uninstall_extension(self, name: str):
        """Удаляем расширение"""
        reply = QMessageBox.question(
            self, "Uninstall Extension",
            f"Are you sure you want to uninstall '{name}'?\n\n"
            "This action cannot be undone!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success = self.ext_manager.uninstall_extension(name)
            if success:
                self.refresh_list()
                self.clear_selection()
    
    def open_extension_folder(self, path: str):
        """Открываем папку расширения"""
        try:
            if os.name == 'nt':  # Windows
                os.startfile(path)
            elif os.name == 'posix':  # Linux/Mac
                subprocess.run(['xdg-open', path])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Cannot open folder: {e}")
    
    def install_extension(self):
        """Устанавливаем новое расширение"""
        dialog = QFileDialog(self, "Install Extension")
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setNameFilter(
            "Extension files (*.zip *.js *.py);;"
            "ZIP archives (*.zip);;"
            "JavaScript files (*.js);;"
            "Python files (*.py);;"
            "All files (*.*)"
        )
        
        if dialog.exec():
            for file_path in dialog.selectedFiles():
                success = self.ext_manager.install_extension(file_path)
                if success:
                    QMessageBox.information(self, "Success", 
                                          f"Extension installed successfully!")
                else:
                    QMessageBox.warning(self, "Error", 
                                      f"Failed to install extension from:\n{file_path}")
            
            self.refresh_list()
    
    def reload_all(self):
        """Перезагружаем все расширения"""
        reply = QMessageBox.question(
            self, "Reload All Extensions",
            "Are you sure you want to reload all extensions?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.ext_manager.reload_all_extensions()
            self.refresh_list()
    
    def open_marketplace(self):
        """Открываем маркетплейс расширений"""
        # TODO: Реализовать маркетплейс
        QMessageBox.information(self, "Extension Marketplace", 
                              "The extension marketplace is coming soon!\n\n"
                              "For now, you can install extensions from local files.")
    
    def clear_selection(self):
        """Очищаем выделение и информацию"""
        self.ext_list.clearSelection()
        self.info_label.setText("Select an extension to view details")
        self.details_text.clear()

# ===== GIT Widget =====
class GitWidget(QWidget):
    """Виджет для работы с Git с поддержкой graceful degradation"""
    
    def __init__(self, git_manager, editor):
        super().__init__()
        self.git_manager = git_manager
        self.editor = editor
        self.current_path = None
        self.setup_ui()
        
        # Отображаем статус Git при создании
        self.update_git_status_display()
    
    def setup_ui(self):
        """Настраиваем интерфейс"""
        self.setStyleSheet("""
            QWidget {
                background: #1c1c3c;
                color: white;
            }
            QPushButton {
                background: #2d2b55;
                border: 1px solid #4b2fbf;
                border-radius: 6px;
                padding: 8px 12px;
                color: white;
                font-size: 12px;
                margin: 2px;
            }
            QPushButton:hover {
                background: #3f2b96;
            }
            QPushButton:disabled {
                background: #444;
                color: #888;
                border-color: #666;
            }
            QListWidget {
                background: #16172e;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                font-size: 12px;
            }
            QTextEdit {
                background: #0f1224;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                color: #dcd7ff;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
            QLabel {
                color: #9b5de5;
                font-weight: 600;
            }
            #warning_label {
                color: #ff6b6b;
                font-weight: bold;
                padding: 10px;
                background: rgba(255, 107, 107, 0.1);
                border-radius: 6px;
                border: 1px solid #ff6b6b;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Статус Git
        self.status_label = QLabel("Проверка Git...")
        layout.addWidget(self.status_label)
        
        # Предупреждение если Git не установлен
        self.warning_label = QLabel("⚠️ Git не установлен. Нажмите 'Установить Git' для активации функций.")
        self.warning_label.setObjectName("warning_label")
        self.warning_label.setVisible(False)
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)
        
        # Кнопки управления
        btn_layout = QHBoxLayout()
        
        self.btn_install_git = QPushButton("⬇️ Установить Git")
        self.btn_install_git.clicked.connect(self.install_git)
        
        self.btn_init = QPushButton("🚀 Init Git")
        self.btn_init.clicked.connect(self.init_git)
        self.btn_init.setEnabled(False)
        
        self.btn_status = QPushButton("📊 Status")
        self.btn_status.clicked.connect(self.show_status)
        self.btn_status.setEnabled(False)
        
        self.btn_stage = QPushButton("📦 Stage")
        self.btn_stage.clicked.connect(self.stage_current)
        self.btn_stage.setEnabled(False)
        
        self.btn_commit = QPushButton("💾 Commit")
        self.btn_commit.clicked.connect(self.commit_changes)
        self.btn_commit.setEnabled(False)
        
        self.btn_pull = QPushButton("⬇️ Pull")
        self.btn_pull.clicked.connect(self.pull_changes)
        self.btn_pull.setEnabled(False)
        
        self.btn_push = QPushButton("⬆️ Push")
        self.btn_push.clicked.connect(self.push_changes)
        self.btn_push.setEnabled(False)
        
        btn_layout.addWidget(self.btn_install_git)
        btn_layout.addWidget(self.btn_init)
        btn_layout.addWidget(self.btn_status)
        btn_layout.addWidget(self.btn_stage)
        btn_layout.addWidget(self.btn_commit)
        btn_layout.addWidget(self.btn_pull)
        btn_layout.addWidget(self.btn_push)
        
        layout.addLayout(btn_layout)
        
        # Поле для сообщения коммита
        self.commit_message = QLineEdit()
        self.commit_message.setPlaceholderText("Commit message...")
        self.commit_message.setEnabled(False)
        layout.addWidget(self.commit_message)
        
        # Список изменённых файлов
        self.changes_list = QListWidget()
        self.changes_list.itemClicked.connect(self.on_file_selected)
        layout.addWidget(self.changes_list, 2)
        
        # История коммитов
        history_label = QLabel("📜 История коммитов:")
        layout.addWidget(history_label)
        
        self.history_list = QListWidget()
        layout.addWidget(self.history_list, 1)
        
        # Подключаем сигналы
        self.git_manager.git_status_changed.connect(self.on_git_status_changed)
        self.git_manager.git_branch_changed.connect(self.on_branch_changed)
        self.git_manager.git_commit_made.connect(self.on_commit_made)
        self.git_manager.git_error.connect(self.on_git_error)
        self.git_manager.git_not_installed.connect(self.on_git_not_installed)
    
    def update_git_status_display(self):
        """Обновляем отображение статуса Git"""
        if self.git_manager.git_installed:
            self.status_label.setText("✅ Git: Установлен")
            self.warning_label.setVisible(False)
            self.btn_install_git.setVisible(False)
            
            # Включаем все кнопки
            self.btn_init.setEnabled(True)
            self.btn_status.setEnabled(True)
            self.btn_stage.setEnabled(True)
            self.btn_commit.setEnabled(True)
            self.btn_pull.setEnabled(True)
            self.btn_push.setEnabled(True)
            self.commit_message.setEnabled(True)
            
            # Обновляем информацию если есть путь
            if self.current_path:
                self.refresh_git_info()
        else:
            self.status_label.setText("❌ Git: Не установлен")
            self.warning_label.setVisible(True)
            self.btn_install_git.setVisible(True)
            
            # Отключаем все кнопки кроме установки
            self.btn_init.setEnabled(False)
            self.btn_status.setEnabled(False)
            self.btn_stage.setEnabled(False)
            self.btn_commit.setEnabled(False)
            self.btn_pull.setEnabled(False)
            self.btn_push.setEnabled(False)
            self.commit_message.setEnabled(False)
            
            # Очищаем списки
            self.changes_list.clear()
            self.history_list.clear()
            self.changes_list.addItem("Установите Git для отображения изменений")
            self.history_list.addItem("Установите Git для отображения истории")
    
    def install_git(self):
        """Предлагаем установить Git"""
        self.git_manager._offer_git_installation()
        # Обновляем статус после предложения
        self.update_git_status_display()
    
    def update_path(self, path: str):
        """Обновляем текущий путь"""
        self.current_path = path
        self.update_git_status_display()
    
    def refresh_git_info(self):
        """Обновляем Git информацию"""
        if not self.current_path or not self.git_manager.git_installed:
            return
        
        status = self.git_manager.get_status(self.current_path)
        if status.get('is_git'):
            branch = status.get('branch', 'unknown')
            has_changes = status.get('has_changes', False)
            untracked = status.get('untracked', False)
            git_available = status.get('git_available', True)
            
            if not git_available:
                self.status_label.setText("Git: ⚠️ Ошибка доступа")
                return
            
            status_text = f"Git: 🌿 {branch}"
            if has_changes:
                status_text += " ⚠️ Изменения"
            if untracked:
                status_text += " ❓ Новые файлы"
            
            self.status_label.setText(status_text)
            
            # Обновляем список изменений
            self.update_changes_list(status)
            
            # Обновляем историю
            self.update_history_list()
        else:
            self.status_label.setText("Git: Не инициализирован")
            self.changes_list.clear()
            self.history_list.clear()
            self.changes_list.addItem("Нажмите '🚀 Init Git' для инициализации Git репозитория")
    
    def update_changes_list(self, status: dict):
        """Обновляем список изменений"""
        self.changes_list.clear()
        
        changed_files = status.get('changed_files', [])
        untracked_files = status.get('untracked_files', [])
        
        if not changed_files and not untracked_files:
            self.changes_list.addItem("Нет изменений")
            return
        
        for file in changed_files:
            item = QListWidgetItem()
            icon = "📦" if file['staged'] else "✏️"
            item.setText(f"{icon} {file['path']} ({file['change_type']})")
            self.changes_list.addItem(item)
        
        for file in untracked_files:
            item = QListWidgetItem(f"❓ {file} (untracked)")
            self.changes_list.addItem(item)
    
    def update_history_list(self):
        """Обновляем историю коммитов"""
        if not self.current_path or not self.git_manager.git_installed:
            return
        
        history = self.git_manager.get_history(self.current_path, 10)
        self.history_list.clear()
        
        if not history:
            self.history_list.addItem("Нет истории коммитов")
            return
        
        for commit in history:
            item_text = f"🔹 {commit['hash']}: {commit['message']}\n   👤 {commit['author']} | 📅 {commit['date']}"
            item = QListWidgetItem(item_text)
            self.history_list.addItem(item)
    
    def on_git_not_installed(self):
        """Обработка отсутствия Git"""
        self.update_git_status_display()
    
    # Остальные методы остаются такими же, но с проверкой git_installed
    
    def init_git(self):
        """Инициализируем Git репозиторий"""
        if not self.git_manager.git_installed:
            self.install_git()
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку!")
            return
        
        success = self.git_manager.init_repo(self.current_path)
        if success:
            self.refresh_git_info()
    
    def show_status(self):
        """Показываем статус Git"""
        if not self.git_manager.git_installed:
            self.install_git()
            return
        
        if not self.current_path:
            return
        
        status = self.git_manager.get_status(self.current_path)
        
        if not status.get('is_git'):
            QMessageBox.information(self, "Git Status", "Не Git репозиторий")
            return
        
        # Показываем подробный статус
        status_text = f"""
        🌿 Ветка: {status.get('branch', 'unknown')}
        📊 Изменения: {'Есть' if status.get('has_changes') else 'Нет'}
        ❓ Новые файлы: {len(status.get('untracked_files', []))}
        
        Изменённые файлы:
        """
        
        for file in status.get('changed_files', []):
            status_text += f"\n  {'[STAGED]' if file['staged'] else '[UNSTAGED]'} {file['path']} ({file['change_type']})"
        
        for file in status.get('untracked_files', []):
            status_text += f"\n  [UNTRACKED] {file}"
        
        QMessageBox.information(self, "Git Status", status_text)
    
    def stage_current(self):
        """Добавляем текущий файл в stage"""
        if not self.git_manager.git_installed:
            self.install_git()
            return
        
        current_file = self.editor.get_current_file()
        if not current_file or not self.current_path:
            return
        
        success = self.git_manager.stage_file(self.current_path, current_file)
        if success:
            self.refresh_git_info()
    
    def commit_changes(self):
        """Создаём коммит"""
        if not self.git_manager.git_installed:
            self.install_git()
            return
        
        if not self.current_path:
            return
        
        message = self.commit_message.text().strip()
        if not message:
            QMessageBox.warning(self, "Ошибка", "Введите сообщение коммита!")
            return
        
        success = self.git_manager.commit(self.current_path, message)
        if success:
            self.commit_message.clear()
            self.refresh_git_info()
    
    def pull_changes(self):
        """Pull изменений"""
        if not self.git_manager.git_installed:
            self.install_git()
            return
        
        if not self.current_path:
            return
        
        result = self.git_manager.pull(self.current_path)
        if result['success']:
            self.refresh_git_info()
        else:
            QMessageBox.warning(self, "Pull ошибка", result['error'])
    
    def push_changes(self):
        """Push изменений"""
        if not self.git_manager.git_installed:
            self.install_git()
            return
        
        if not self.current_path:
            return
        
        result = self.git_manager.push(self.current_path)
        if result['success']:
            self.refresh_git_info()
        else:
            QMessageBox.warning(self, "Push ошибка", result['error'])
    
    def on_git_status_changed(self, path: str, status: dict):
        """Обработка изменения статуса Git"""
        if path == self.current_path:
            self.refresh_git_info()
    
    def on_branch_changed(self, path: str, branch: str):
        """Обработка смены ветки"""
        if path == self.current_path:
            self.editor.log(f"🌿 Ветка изменена: {branch}", "info")
    
    def on_commit_made(self, path: str, commit_hash: str):
        """Обработка создания коммита"""
        if path == self.current_path:
            self.editor.log(f"💾 Коммит создан: {commit_hash[:7]}", "success")
    
    def on_git_error(self, path: str, error: str):
        """Обработка ошибки Git"""
        self.editor.log(f"❌ Git ошибка: {error}", "error")
    
    def on_file_selected(self, item):
        """Обработка выбора файла"""
        # TODO: Показать diff файла
        pass

# ===== Главный редактор =====
class LudvigEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1400, 900)
        
        # Сначала создаем GitManager но не логируем
        self.git_manager = GitManager(self)
        
        # Пока не создаем ext_manager здесь!
        # self.ext_manager = ExtensionManager(self)  # ← КОММЕНТИРУЕМ ЭТО
        
        # А ЭТУ СТРОЧКУ ТОЖЕ КОММЕНТИРУЕМ
        # self.api = EditorAPI(self)
        
        # Список вкладок
        self.tabs_data = []  # [(path, view, language), ...]
        
        # Настройка UI (ЭТО СОЗДАЕТ TERMINAL!)
        self.setup_ui()
        self.setup_shortcuts()
        
        # ТЕПЕРЬ создаем менеджеры
        self.ext_manager = ExtensionManager(self)  # ← ПЕРЕНЕСЛИ СЮДА!
        self.api = EditorAPI(self)  # ← И ЭТО ТОЖЕ!

        # Менеджер обновлений
        self.update_manager = UpdateManager(self)

        # Настраиваем автоматическую проверку
        self.update_manager.setup_auto_check()
        
        # ТЕПЕРЬ настраиваем сигналы (ext_manager уже создан!)
        self.setup_signals()
        
        # Загружаем настройки
        self.restore_settings()
        
        # Загружаем локальный редактор если нужно
        self.setup_editor_url()
        
        # ТЕПЕРЬ создаем виджеты (после setup_ui)
        self.ext_widget = ExtensionsWidget(self.ext_manager)
        self.ext_widget.setVisible(False)
        
        self.git_widget = GitWidget(self.git_manager, self)
        self.git_widget.setVisible(False)
        
        # Добавляем виджеты в splitter
        self.main_splitter.addWidget(self.ext_widget)
        self.main_splitter.addWidget(self.git_widget)
        
        # Обновляем размеры splitter
        self.main_splitter.setSizes([200, 800, 300, 300])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setStretchFactor(3, 0)
        
        # ТЕПЕРЬ можно логировать (terminal уже создан!)
        if self.git_manager.git_installed:
            self.log("✅ Git обнаружен и готов к работе", "success")
        else:
            self.log("⚠️ Git не установлен. Функции Git будут доступны после установки.", "warning")
    
    def setup_editor_url(self):
        """Настраиваем URL редактора"""
        global EDITOR_URL
        
        # Создаем локальный редактор если нет интернета
        LOCAL_EDITOR_PATH = os.path.join(os.path.dirname(__file__), "editor.html")
        
        if not check_internet() and not os.path.exists(LOCAL_EDITOR_PATH):
            # Используем упрощенную версию из кода выше
            html_content = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>LudvigEditor</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<style>
html, body {
    margin: 0;
    height: 100%;
    overflow: hidden;
    background: linear-gradient(135deg, #4b2fbf, #2b1a55, #14142e);
    font-family: system-ui;
}

/* ===== TOP BAR ===== */
#topbar {
    height: 46px;
    display: flex;
    align-items: center;
    padding: 0 14px;
    color: #fff;
    font-weight: 600;
    letter-spacing: .4px;
    background: linear-gradient(135deg, rgba(90,60,200,.85), rgba(60,40,160,.85));
    backdrop-filter: blur(20px) saturate(160%);
    box-shadow: 0 6px 30px rgba(0,0,0,.5);
    border-bottom: 1px solid rgba(255,255,255,.12);
    position: relative;
    gap: 10px;
}

/* ===== SEARCH INPUT ===== */
#searchInput {
    padding: 4px 8px;
    border-radius: 6px;
    border: none;
    outline: none;
    opacity: 0.85;
    font-size: 14px;
    background: rgba(255,255,255,.12);
    color: #fff;
}

/* ===== LANGUAGE SELECT ===== */
#langSelect {
    padding: 4px 8px;
    border-radius: 6px;
    border: none;
    font-size: 14px;
    background: rgba(255,255,255,.12);
    color: #fff; /* отображение в панели */
}

/* Сделаем текст внутри раскрывающегося списка чёрным на светлом фоне */
#langSelect option {
    color: black;
    background: white;
}

/* ===== EDITOR ===== */
#editor {
    width: 100%;
    height: calc(100% - 46px);
}

/* ===== SCROLLBAR ===== */
::-webkit-scrollbar { width: 10px; }
::-webkit-scrollbar-thumb { background: rgba(130,130,220,.4); border-radius: 10px; }
</style>

<script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs/loader.min.js"></script>
</head>

<body>
<div id="topbar">
    ⚡ LudvigEditor — VS Code style
    <input type="text" id="searchInput" placeholder="Search..." />
    <select id="langSelect">
        <option value="python">Python</option>
        <option value="javascript">JavaScript</option>
        <option value="typescript">TypeScript</option>
        <option value="html">HTML</option>
        <option value="css">CSS</option>
        <option value="json">JSON</option>
        <option value="c">C</option>
        <option value="cpp">C++</option>
        <option value="java">Java</option>
        <option value="markdown">Markdown</option>
        <option value="shell">Bash</option>
        <option value="ruby">Ruby</option>
        <option value="php">PHP</option>
        <option value="go">Go</option>
        <option value="rust">Rust</option>
        <option value="kotlin">Kotlin</option>
        <option value="swift">Swift</option>
        <option value="lua">Lua</option>
        <option value="sql">SQL</option>
        <option value="yaml">YAML</option>
        <option value="xml">XML</option>
        <option value="plaintext">Plain Text</option>
    </select>
</div>
<div id="editor"></div>

<script>
require.config({ paths: { vs: "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs" } });

require(["vs/editor/editor.main"], function () {

    // ===== THEME =====
    monaco.editor.defineTheme("ludvig-gradient", {
        base: "vs-dark",
        inherit: true,
        rules: [
            { token: "comment", foreground: "7fd88b" },
            { token: "keyword", foreground: "c792ea" },
            { token: "number", foreground: "b5cea8" },
            { token: "string", foreground: "f6c177" },
            { token: "type.identifier", foreground: "4ec9b0" },
            { token: "function", foreground: "82aaff" },
        ],
        colors: {
            "editor.background": "#0f1224",
            "editor.lineHighlightBackground": "#1c2040",
            "editorCursor.foreground": "#ffffff",
            "editor.selectionBackground": "#2f3368",
        }
    });

    // ===== EDITOR =====
    window.editor = monaco.editor.create(document.getElementById("editor"), {
        value: "# LudvigEditor\nprint('Gradient future 🚀')",
        language: "python",
        theme: "ludvig-gradient",
        automaticLayout: true,
        fontFamily: "JetBrains Mono, Consolas, monospace",
        fontSize: 14,
        fontLigatures: true,
        smoothScrolling: true,
        cursorSmoothCaretAnimation: "on",
        minimap: { enabled: true },
        wordWrap: "on",
        dragAndDrop: true
    });

    // ===== LANGUAGE SWITCH =====
    const langSelect = document.getElementById("langSelect");
    langSelect.addEventListener("change", () => {
        monaco.editor.setModelLanguage(editor.getModel(), langSelect.value);
    });

    // ===== SEARCH =====
    const searchInput = document.getElementById("searchInput");
    searchInput.addEventListener("input", () => {
        const term = searchInput.value;
        const findController = editor.getContribution('editor.contrib.findController');
        if(term) {
            editor.getAction('actions.find').run().then(() => {
                findController.getState().change({ searchString: term }, false);
            });
        } else {
            findController.getState().change({ searchString: '' }, false);
        }
    });

    // ===== API FOR PYQT =====
    window.setCode = (code, lang = "python") => {
        monaco.editor.setModelLanguage(editor.getModel(), lang);
        editor.setValue(code);
    };

    window.getCode = () => editor.getValue();
    window.pySave = null; // Для PyQt6
});
</script>
</body>
</html>"""
            
            try:
                with open(LOCAL_EDITOR_PATH, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                # Используем обычный print вместо log
                print("ℹ️ Создан локальный редактор (интернет отсутствует)")
            except Exception as e:
                print(f"❌ Ошибка создания локального редактора: {e}")
        
        # Устанавливаем URL
        if not check_internet():
            EDITOR_URL = QUrl.fromLocalFile(LOCAL_EDITOR_PATH)
        else:
            EDITOR_URL = QUrl("https://ludvig2457.github.io/editor.html")

    def check_updates(self):
        """Проверка обновлений"""
        if hasattr(self, 'update_manager'):
            self.update_manager.check_for_updates(auto_check=False)

    def on_update_downloaded(self, file_path: str):
        """Обработка скачанного обновления"""
        self.log(f"✅ Обновление скачано: {file_path}", "success")
    
    def setup_ui(self):
        """Настраиваем пользовательский интерфейс"""
        # Центральный виджет
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Боковая панель
        self.sidebar = self.create_sidebar()
        main_layout.addWidget(self.sidebar)
        
        # Основная область
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Проводник файлов
        self.explorer = self.create_explorer()
        self.main_splitter.addWidget(self.explorer)
        
        # Область редактора
        self.editor_area = QSplitter(Qt.Orientation.Vertical)
        
        # Вкладки
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.setMovable(True)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.style_tabs()
        
        # Терминал
        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.style_terminal()
        
        # Welcome screen
        self.welcome = WelcomeScreen(
            self.open_file,
            self.open_folder,
            self.show_extensions
        )
        
        # Stack для переключения
        self.stack = QStackedWidget()
        self.stack.addWidget(self.welcome)
        
        editor_splitter = QSplitter(Qt.Orientation.Vertical)
        editor_splitter.addWidget(self.tabs)
        editor_splitter.addWidget(self.terminal)
        editor_splitter.setStretchFactor(0, 3)
        editor_splitter.setStretchFactor(1, 1)
        
        self.stack.addWidget(editor_splitter)
        self.editor_area.addWidget(self.stack)
        self.main_splitter.addWidget(self.editor_area)
        
        # Виджеты расширений и Git будут добавлены позже в __init__
        # self.ext_widget = None
        # self.git_widget = None
        
        # Настройка разделителей (пока только для explorer и editor)
        self.main_splitter.setSizes([200, 800])
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(self.main_splitter)
        
        # Статус бар
        self.status_bar = self.statusBar()
        self.setup_status_bar()
        
        # Меню
        self.setup_menu()

    def complete_initialization(self):
        """Завершаем инициализацию после создания UI"""
        # Создаем виджет расширений
        if hasattr(self, 'ext_manager') and self.ext_manager:
            self.ext_widget = ExtensionsWidget(self.ext_manager)
            self.ext_widget.setVisible(False)
            self.main_splitter.addWidget(self.ext_widget)
        
        # Создаем Git widget
        if hasattr(self, 'git_manager') and self.git_manager:
            self.git_widget = GitWidget(self.git_manager, self)
            self.git_widget.setVisible(False)
            self.main_splitter.addWidget(self.git_widget)
        
        # Обновляем размеры splitter
        if hasattr(self, 'ext_widget') and self.ext_widget and hasattr(self, 'git_widget') and self.git_widget:
            self.main_splitter.setSizes([200, 800, 300, 300])
            self.main_splitter.setStretchFactor(0, 0)
            self.main_splitter.setStretchFactor(1, 1)
            self.main_splitter.setStretchFactor(2, 0)
            self.main_splitter.setStretchFactor(3, 0)

    @property
    def current_path(self) -> Optional[str]:
        """Получаем текущий путь (папку проекта)"""
        current_file = self.get_current_file()
        if current_file:
            return os.path.dirname(current_file)
        
        # Если файл не открыт, пробуем получить из проводника
        if hasattr(self, 'explorer') and self.explorer.model():
            root_path = self.explorer.model().rootPath()
            if root_path and os.path.exists(root_path):
                return root_path
        
        return None
    
    def create_sidebar(self) -> QWidget:
        """Создаем боковую панель"""
        sidebar = QFrame()
        sidebar.setFixedWidth(60)
        sidebar.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3f2b96, stop:1 #1a1b3a);
                border-right: 1px solid rgba(255, 255, 255, 0.1);
            }
            QPushButton {
                background: transparent;
                border: none;
                color: white;
                padding: 12px;
                font-size: 20px;
                border-radius: 6px;
                margin: 4px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.15);
            }
            QPushButton:checked {
                background: rgba(255, 255, 255, 0.25);
            }
        """)
        
        layout = QVBoxLayout(sidebar)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(8)
        layout.setContentsMargins(4, 10, 4, 10)
        
        # Кнопки
        self.btn_explorer = QPushButton("📁")
        self.btn_explorer.setCheckable(True)
        self.btn_explorer.setToolTip("Explorer")
        self.btn_explorer.clicked.connect(self.toggle_explorer)
        
        self.btn_search = QPushButton("🔍")
        self.btn_search.setToolTip("Search")
        self.btn_search.clicked.connect(self.show_search)
        
        # ДОБАВЛЯЕМ КНОПКУ GIT
        self.btn_git = QPushButton("🐙")
        self.btn_git.setCheckable(True)
        self.btn_git.setToolTip("Git")
        self.btn_git.clicked.connect(self.toggle_git)
        
        self.btn_extensions = QPushButton("🧩")
        self.btn_extensions.setCheckable(True)
        self.btn_extensions.setToolTip("Extensions")
        self.btn_extensions.clicked.connect(self.toggle_extensions)
        
        self.btn_debug = QPushButton("🐞")
        self.btn_debug.setToolTip("Debug")
        self.btn_debug.clicked.connect(self.show_debug)
        
        layout.addWidget(self.btn_explorer)
        layout.addWidget(self.btn_search)
        layout.addWidget(self.btn_git)  # ← ДОБАВЬ ЭТО
        layout.addWidget(self.btn_extensions)
        layout.addWidget(self.btn_debug)
        layout.addStretch()
        
        # Нижние кнопки
        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setToolTip("Settings")
        self.btn_settings.clicked.connect(self.show_settings)
        
        layout.addWidget(self.btn_settings)
        
        return sidebar
    
    def toggle_git(self):
        """Показываем/скрываем Git панель"""
        visible = not self.git_widget.isVisible()
        self.git_widget.setVisible(visible)
        self.btn_git.setChecked(visible)
        
        if visible and self.current_path:
            self.git_widget.update_path(self.current_path)
    
    def create_explorer(self) -> QTreeView:
        """Создаем проводник файлов"""
        model = QFileSystemModel()
        model.setRootPath("")
        model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | 
                       QDir.Filter.NoDotAndDotDot)
        
        explorer = QTreeView()
        explorer.setModel(model)
        explorer.setHeaderHidden(True)
        explorer.setAnimated(True)
        explorer.setIndentation(15)
        explorer.setSortingEnabled(True)
        
        # Настраиваем колонки
        explorer.hideColumn(1)  # Size
        explorer.hideColumn(2)  # Type
        explorer.hideColumn(3)  # Date modified
        
        # Стили
        explorer.setStyleSheet("""
            QTreeView {
                background: #16172e;
                color: #e0e0ff;
                border: none;
                font-size: 13px;
                outline: none;
            }
            QTreeView::item {
                padding: 4px;
                border-radius: 4px;
            }
            QTreeView::item:selected {
                background: #5b3cc4;
                color: white;
            }
            QTreeView::item:hover {
                background: rgba(255, 255, 255, 0.1);
            }
            QHeaderView::section {
                background: #1a1b3a;
                color: #a0a0ff;
                padding: 4px;
                border: none;
            }
        """)
        
        # Контекстное меню
        explorer.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        explorer.customContextMenuRequested.connect(self.explorer_menu)
        
        # Двойной клик для открытия файлов
        explorer.doubleClicked.connect(self.open_from_explorer)
        
        return explorer
    
    def setup_status_bar(self):
        """Настраиваем статус бар"""
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background: rgba(26, 27, 58, 0.9);
                color: #a0a0ff;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
                font-size: 12px;
            }
        """)
        
        # Виджеты статус бара
        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label)
        
        self.position_label = QLabel("Ln 1, Col 1")
        self.status_bar.addPermanentWidget(self.position_label)
        
        self.encoding_label = QLabel("UTF-8")
        self.status_bar.addPermanentWidget(self.encoding_label)
        
        self.line_endings_label = QLabel("LF")
        self.status_bar.addPermanentWidget(self.line_endings_label)
        
        self.language_label = QLabel("Plain Text")
        self.status_bar.addPermanentWidget(self.language_label)
    
    def setup_menu(self):
        """Настраиваем главное меню"""
        menubar = self.menuBar()
        menubar.setStyleSheet("""
            QMenuBar {
                background: rgba(40, 41, 82, 0.9);
                color: white;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            }
            QMenuBar::item {
                padding: 5px 10px;
                background: transparent;
            }
            QMenuBar::item:selected {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 4px;
            }
            QMenu {
                background: rgba(40, 41, 82, 0.95);
                color: white;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 6px;
                padding: 5px;
            }
            QMenu::item {
                padding: 5px 20px 5px 20px;
            }
            QMenu::item:selected {
                background: rgba(91, 60, 196, 0.7);
                border-radius: 4px;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 0.1);
                margin: 5px 10px;
            }
        """)
        
        # Меню File
        file_menu = menubar.addMenu("&File")
        
        new_file = QAction("&New File", self)
        new_file.setShortcut(QKeySequence("Ctrl+N"))
        new_file.triggered.connect(self.new_file)
        file_menu.addAction(new_file)
        
        open_file = QAction("&Open File...", self)
        open_file.setShortcut(QKeySequence("Ctrl+O"))
        open_file.triggered.connect(self.open_file)
        file_menu.addAction(open_file)
        
        open_folder = QAction("Open &Folder...", self)
        open_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        open_folder.triggered.connect(self.open_folder)
        file_menu.addAction(open_folder)
        
        file_menu.addSeparator()
        
        save = QAction("&Save", self)
        save.setShortcut(QKeySequence("Ctrl+S"))
        save.triggered.connect(self.save_current)
        file_menu.addAction(save)
        
        save_as = QAction("Save &As...", self)
        save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        save_as.triggered.connect(self.save_as)
        file_menu.addAction(save_as)
        
        save_all = QAction("Save A&ll", self)
        save_all.setShortcut(QKeySequence("Ctrl+Alt+S"))
        save_all.triggered.connect(self.save_all)
        file_menu.addAction(save_all)
        
        file_menu.addSeparator()
        
        close_file = QAction("&Close File", self)
        close_file.setShortcut(QKeySequence("Ctrl+W"))
        close_file.triggered.connect(self.close_current)
        file_menu.addAction(close_file)
        
        close_all = QAction("Close &All", self)
        close_all.setShortcut(QKeySequence("Ctrl+Shift+W"))
        close_all.triggered.connect(self.close_all)
        file_menu.addAction(close_all)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Меню Edit
        edit_menu = menubar.addMenu("&Edit")
        
        undo = QAction("&Undo", self)
        undo.setShortcut(QKeySequence("Ctrl+Z"))
        undo.triggered.connect(self.undo_current)
        edit_menu.addAction(undo)
        
        redo = QAction("&Redo", self)
        redo.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        redo.triggered.connect(self.redo_current)
        edit_menu.addAction(redo)
        
        edit_menu.addSeparator()
        
        cut = QAction("Cu&t", self)
        cut.setShortcut(QKeySequence("Ctrl+X"))
        cut.triggered.connect(self.cut_current)
        edit_menu.addAction(cut)
        
        copy = QAction("&Copy", self)
        copy.setShortcut(QKeySequence("Ctrl+C"))
        copy.triggered.connect(self.copy_current)
        edit_menu.addAction(copy)
        
        paste = QAction("&Paste", self)
        paste.setShortcut(QKeySequence("Ctrl+V"))
        paste.triggered.connect(self.paste_current)
        edit_menu.addAction(paste)
        
        edit_menu.addSeparator()
        
        find = QAction("&Find...", self)
        find.setShortcut(QKeySequence("Ctrl+F"))
        find.triggered.connect(self.find_in_file)
        edit_menu.addAction(find)
        
        replace = QAction("&Replace...", self)
        replace.setShortcut(QKeySequence("Ctrl+H"))
        replace.triggered.connect(self.replace_in_file)
        edit_menu.addAction(replace)
        
        # Меню View
        view_menu = menubar.addMenu("&View")
        
        toggle_explorer = QAction("&Explorer", self)
        toggle_explorer.setCheckable(True)
        toggle_explorer.setChecked(True)
        toggle_explorer.triggered.connect(self.toggle_explorer)
        view_menu.addAction(toggle_explorer)
        
        toggle_git = QAction("🐙 &Git", self)
        toggle_git.setCheckable(True)
        toggle_git.triggered.connect(self.toggle_git)
        view_menu.addAction(toggle_git)
        
        toggle_extensions = QAction("E&xtensions", self)
        toggle_extensions.setCheckable(True)
        toggle_extensions.triggered.connect(self.toggle_extensions)
        view_menu.addAction(toggle_extensions)
        
        toggle_terminal = QAction("&Terminal", self)
        toggle_terminal.setCheckable(True)
        toggle_terminal.setChecked(True)
        toggle_terminal.triggered.connect(self.toggle_terminal)
        view_menu.addAction(toggle_terminal)
        
        view_menu.addSeparator()
        
        fullscreen = QAction("&Full Screen", self)
        fullscreen.setShortcut(QKeySequence("F11"))
        fullscreen.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(fullscreen)
        
        # Меню Run
        run_menu = menubar.addMenu("&Run")
        
        run_file = QAction("&Run File", self)
        run_file.setShortcut(QKeySequence("F5"))
        run_file.triggered.connect(self.run_code)
        run_menu.addAction(run_file)
        
        debug_file = QAction("&Debug File", self)
        debug_file.setShortcut(QKeySequence("F6"))
        debug_file.triggered.connect(self.debug_code)
        run_menu.addAction(debug_file)
        
        # Меню Git
        git_menu = menubar.addMenu("🐙 &Git")
        
        init_git = QAction("🚀 &Init Repository", self)
        init_git.setShortcut(QKeySequence("Ctrl+Shift+G"))
        init_git.triggered.connect(self.init_git_repo)
        git_menu.addAction(init_git)
        
        git_menu.addSeparator()
        
        git_status = QAction("📊 &Status", self)
        git_status.setShortcut(QKeySequence("Ctrl+Shift+S"))
        git_status.triggered.connect(self.show_git_status)
        git_menu.addAction(git_status)
        
        stage_current = QAction("📦 &Stage File", self)
        stage_current.setShortcut(QKeySequence("Ctrl+Alt+S"))
        stage_current.triggered.connect(self.stage_git_file)
        git_menu.addAction(stage_current)
        
        stage_all = QAction("📦 Stage &All", self)
        stage_all.triggered.connect(self.stage_all_git)
        git_menu.addAction(stage_all)
        
        git_menu.addSeparator()
        
        git_commit = QAction("💾 &Commit", self)
        git_commit.setShortcut(QKeySequence("Ctrl+Shift+C"))
        git_commit.triggered.connect(self.commit_git)
        git_menu.addAction(git_commit)
        
        git_menu.addSeparator()
        
        git_pull = QAction("⬇️ &Pull", self)
        git_pull.setShortcut(QKeySequence("Ctrl+Shift+P"))
        git_pull.triggered.connect(self.pull_git)
        git_menu.addAction(git_pull)
        
        git_push = QAction("⬆️ Pu&sh", self)
        git_push.setShortcut(QKeySequence("Ctrl+Shift+U"))
        git_push.triggered.connect(self.push_git)
        git_menu.addAction(git_push)
        
        git_menu.addSeparator()
        
        create_branch = QAction("🌿 &Create Branch...", self)
        create_branch.triggered.connect(self.create_git_branch)
        git_menu.addAction(create_branch)
        
        checkout_branch = QAction("🔄 Checkout &Branch...", self)
        checkout_branch.triggered.connect(self.checkout_git_branch)
        git_menu.addAction(checkout_branch)
        
        git_menu.addSeparator()
        
        show_git_log = QAction("📜 Show &Log", self)
        show_git_log.triggered.connect(self.show_git_log)
        git_menu.addAction(show_git_log)
        
        # Меню Extensions
        extensions_menu = menubar.addMenu("E&xtensions")
        
        install_ext = QAction("&Install Extension...", self)
        install_ext.triggered.connect(self.install_extension)
        extensions_menu.addAction(install_ext)
        
        manage_ext = QAction("&Manage Extensions", self)
        manage_ext.triggered.connect(self.show_extensions)
        extensions_menu.addAction(manage_ext)
        
        extensions_menu.addSeparator()
        
        reload_ext = QAction("&Reload All Extensions", self)
        reload_ext.triggered.connect(self.reload_extensions)
        extensions_menu.addAction(reload_ext)
        
        # Меню Help
        help_menu = menubar.addMenu("&Help")
        
        docs = QAction("&Documentation", self)
        docs.triggered.connect(self.show_docs)
        help_menu.addAction(docs)

        check_updates = QAction("🔍 Проверить обновления", self)
        check_updates.triggered.connect(self.check_updates)
        help_menu.addAction(check_updates)
        
        about = QAction("&About", self)
        about.triggered.connect(self.show_about)
        help_menu.addAction(about)

    def init_git_repo(self):
        """Инициализируем Git репозиторий"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙 в боковой панели) для установки.\n"
                                "Или используйте меню 🐙 → Git → 'Установить Git'")
            # Показываем Git панель для установки
            if hasattr(self, 'git_widget'):
                self.git_widget.setVisible(True)
                self.btn_git.setChecked(True)
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку!")
            return
        
        reply = QMessageBox.question(
            self, "Init Git Repository",
            f"Создать Git репозиторий в папке:\n{self.current_path}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success = self.git_manager.init_repo(self.current_path)
            if success:
                self.log("✅ Git репозиторий создан", "success")
                if hasattr(self, 'git_widget') and self.git_widget.isVisible():
                    self.git_widget.refresh_git_info()

    def show_git_status(self):
        """Показываем статус Git"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙 в боковой панели) для установки.\n"
                                "Или используйте меню 🐙 → Git → 'Установить Git'")
            # Показываем Git панель для установки
            if hasattr(self, 'git_widget'):
                self.git_widget.setVisible(True)
                self.btn_git.setChecked(True)
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку или файл!")
            return
        
        # Автоматически показываем Git панель
        if hasattr(self, 'git_widget') and not self.git_widget.isVisible():
            self.toggle_git()
        
        status = self.git_manager.get_status(self.current_path)
        
        if not status.get('is_git'):
            reply = QMessageBox.question(
                self, "Git Status", 
                "Не Git репозиторий.\n\n"
                "Хотите инициализировать Git в этой папке?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.init_git_repo()
            return
        
        # Показываем подробный статус
        branch = status.get('branch', 'unknown')
        has_changes = status.get('has_changes', False)
        untracked_count = len(status.get('untracked_files', []))
        changed_count = len(status.get('changed_files', []))
        
        status_text = f"""
        📍 Папка: {os.path.basename(self.current_path)}
        🌿 Ветка: {branch}
        📊 Состояние: {f'⚠️ {changed_count} изменённых, {untracked_count} новых' if has_changes else '✅ Чистый'}
        
        Файлы:
        """
        
        # Изменённые файлы
        changed_files = status.get('changed_files', [])
        untracked_files = status.get('untracked_files', [])
        
        if changed_files:
            status_text += "\n📝 Изменённые файлы:"
            for file in changed_files:
                status_icon = "📦" if file['staged'] else "✏️"
                staged_text = "[STAGED]" if file['staged'] else "[UNSTAGED]"
                status_text += f"\n  {status_icon} {staged_text} {file['path']} ({file['change_type']})"
        
        if untracked_files:
            status_text += "\n❓ Новые файлы:"
            for file in untracked_files:
                status_text += f"\n  ❓ [UNTRACKED] {file}"
        
        if not changed_files and not untracked_files:
            status_text += "\n  ✅ Нет изменений"
        
        # Показываем диалог
        dialog = QDialog(self)
        dialog.setWindowTitle("Git Status")
        dialog.setMinimumSize(500, 400)
        
        layout = QVBoxLayout(dialog)
        
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Consolas", 10))
        text_edit.setText(status_text)
        
        layout.addWidget(text_edit)
        
        # Кнопки действий
        button_box = QDialogButtonBox()
        
        if has_changes:
            stage_all_btn = button_box.addButton("📦 Stage All", QDialogButtonBox.ButtonRole.ActionRole)
            stage_all_btn.clicked.connect(lambda: self.stage_all_git())
            stage_all_btn.clicked.connect(dialog.accept)
            
            commit_btn = button_box.addButton("💾 Commit", QDialogButtonBox.ButtonRole.ActionRole)
            commit_btn.clicked.connect(lambda: self.commit_git())
            commit_btn.clicked.connect(dialog.accept)
        
        refresh_btn = button_box.addButton("🔄 Refresh", QDialogButtonBox.ButtonRole.ActionRole)
        refresh_btn.clicked.connect(lambda: self.show_git_status())
        refresh_btn.clicked.connect(dialog.accept)
        
        close_btn = button_box.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        close_btn.clicked.connect(dialog.reject)
        
        layout.addWidget(button_box)
        
        dialog.exec()

    def stage_git_file(self):
        """Добавляем текущий файл в stage"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙) для установки.")
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку или файл!")
            return
        
        current_file = self.get_current_file()
        if not current_file:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте файл!")
            return
        
        success = self.git_manager.stage_file(self.current_path, current_file)
        if success:
            self.log(f"📦 Файл добавлен в stage: {os.path.basename(current_file)}", "info")
            # Обновляем Git виджет если открыт
            if hasattr(self, 'git_widget') and self.git_widget.isVisible():
                self.git_widget.refresh_git_info()
        else:
            self.log(f"❌ Не удалось добавить файл в stage", "error")

    def stage_all_git(self):
        """Добавляем все файлы в stage"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙) для установки.")
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку!")
            return
        
        status = self.git_manager.get_status(self.current_path)
        if not status.get('is_git'):
            QMessageBox.warning(self, "Ошибка", "Не Git репозиторий!")
            return
        
        changed_files = status.get('changed_files', [])
        untracked_files = status.get('untracked_files', [])
        
        if not changed_files and not untracked_files:
            QMessageBox.information(self, "Stage All", "Нет файлов для добавления в stage")
            return
        
        reply = QMessageBox.question(
            self, "Stage All Files",
            f"Добавить в stage:\n"
            f"• {len([f for f in changed_files if not f['staged']])} неиндексированных изменений\n"
            f"• {len(untracked_files)} новых файлов\n\n"
            f"Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Добавляем неиндексированные изменения
        staged_count = 0
        for file in changed_files:
            if not file['staged']:
                if self.git_manager.stage_file(self.current_path, file['path']):
                    staged_count += 1
        
        # Добавляем новые файлы
        for file in untracked_files:
            if self.git_manager.stage_file(self.current_path, file):
                staged_count += 1
        
        self.log(f"📦 Добавлено в stage: {staged_count} файлов", "info")
        
        # Обновляем Git виджет если открыт
        if hasattr(self, 'git_widget') and self.git_widget.isVisible():
            self.git_widget.refresh_git_info()

    def commit_git(self):
        """Создаём Git коммит"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙) для установки.")
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку!")
            return
        
        # Проверяем есть ли что коммитить
        status = self.git_manager.get_status(self.current_path)
        if not status.get('is_git'):
            QMessageBox.warning(self, "Ошибка", "Не Git репозиторий!")
            return
        
        has_staged = any(file['staged'] for file in status.get('changed_files', []))
        has_changes = status.get('has_changes', False)
        
        if not has_staged and has_changes:
            reply = QMessageBox.question(
                self, "Нет staged файлов",
                "Нет файлов в stage. Хотите сначала добавить все изменения в stage?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | 
                QMessageBox.StandardButton.Cancel
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.stage_all_git()
                # Перепроверяем статус
                status = self.git_manager.get_status(self.current_path)
                has_staged = any(file['staged'] for file in status.get('changed_files', []))
                if not has_staged:
                    QMessageBox.warning(self, "Ошибка", "Всё ещё нет файлов в stage!")
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        
        # Запрашиваем сообщение коммита
        dialog = QDialog(self)
        dialog.setWindowTitle("Git Commit")
        dialog.setMinimumSize(400, 300)
        
        layout = QVBoxLayout(dialog)
        
        # Поле для сообщения
        message_label = QLabel("Сообщение коммита:")
        layout.addWidget(message_label)
        
        message_edit = QTextEdit()
        message_edit.setPlaceholderText("Введите сообщение коммита...")
        message_edit.setMinimumHeight(100)
        
        # Предзаполняем стандартные сообщения
        default_messages = [
            "Update",
            "Fix bug",
            "Add feature",
            "Refactor code",
            "Initial commit"
        ]
        
        # Показываем staged файлы
        if has_staged:
            files_label = QLabel("Файлы в stage:")
            layout.addWidget(files_label)
            
            files_text = QTextEdit()
            files_text.setReadOnly(True)
            files_text.setMaximumHeight(80)
            
            staged_files = [f"• {file['path']} ({file['change_type']})" 
                        for file in status.get('changed_files', []) 
                        if file['staged']]
            
            files_text.setText("\n".join(staged_files[:10]))  # Показываем первые 10
            if len(staged_files) > 10:
                files_text.append(f"\n... и ещё {len(staged_files) - 10} файлов")
            
            layout.addWidget(files_text)
        
        layout.addWidget(message_edit)
        
        # Кнопки
        button_box = QDialogButtonBox()
        
        # Кнопки с быстрыми сообщениями
        for msg in default_messages:
            btn = QPushButton(msg)
            btn.clicked.connect(lambda checked, m=msg: message_edit.setText(m))
            layout.addWidget(btn)
        
        commit_btn = button_box.addButton("💾 Commit", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        
        layout.addWidget(button_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            message = message_edit.toPlainText().strip()
            if not message:
                QMessageBox.warning(self, "Ошибка", "Сообщение коммита не может быть пустым!")
                return
            
            success = self.git_manager.commit(self.current_path, message)
            if success:
                self.log(f"💾 Коммит создан: {message}", "success")
                # Обновляем Git виджет если открыт
                if hasattr(self, 'git_widget') and self.git_widget.isVisible():
                    self.git_widget.refresh_git_info()
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось создать коммит!")

    def pull_git(self):
        """Pull из Git"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙) для установки.")
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку!")
            return
        
        reply = QMessageBox.question(
            self, "Git Pull",
            "Выполнить pull из удалённого репозитория?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # Сохраняем все файлы перед pull
        self.save_all()
        
        result = self.git_manager.pull(self.current_path)
        if result['success']:
            self.log("⬇️ Pull выполнен успешно", "info")
            
            # Показываем результат
            if result.get('stdout'):
                QMessageBox.information(self, "Pull Result", result['stdout'])
            
            # Обновляем Git виджет если открыт
            if hasattr(self, 'git_widget') and self.git_widget.isVisible():
                self.git_widget.refresh_git_info()
        else:
            error_msg = result.get('error', 'Неизвестная ошибка')
            self.log(f"❌ Pull ошибка: {error_msg}", "error")
            QMessageBox.critical(self, "Pull Error", f"Ошибка при выполнении pull:\n\n{error_msg}")

    def push_git(self):
        """Push в Git"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙) для установки.")
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку!")
            return
        
        # Проверяем есть ли что пушить
        status = self.git_manager.get_status(self.current_path)
        if not status.get('is_git'):
            QMessageBox.warning(self, "Ошибка", "Не Git репозиторий!")
            return
        
        reply = QMessageBox.question(
            self, "Git Push",
            "Выполнить push в удалённый репозиторий?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        result = self.git_manager.push(self.current_path)
        if result['success']:
            self.log("⬆️ Push выполнен успешно", "info")
            
            # Показываем результат
            if result.get('stdout'):
                QMessageBox.information(self, "Push Result", result['stdout'])
            
            # Обновляем Git виджет если открыт
            if hasattr(self, 'git_widget') and self.git_widget.isVisible():
                self.git_widget.refresh_git_info()
        else:
            error_msg = result.get('error', 'Неизвестная ошибка')
            self.log(f"❌ Push ошибка: {error_msg}", "error")
            
            # Показываем подробную ошибку
            error_text = f"Ошибка при выполнении push:\n\n{error_msg}"
            if result.get('stderr'):
                error_text += f"\n\nДетали:\n{result['stderr']}"
            
            QMessageBox.critical(self, "Push Error", error_text)

    def create_git_branch(self):
        """Создаём новую ветку"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙) для установки.")
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку!")
            return
        
        # Получаем текущую ветку
        status = self.git_manager.get_status(self.current_path)
        if not status.get('is_git'):
            QMessageBox.warning(self, "Ошибка", "Не Git репозиторий!")
            return
        
        current_branch = status.get('branch', 'unknown')
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Create Git Branch")
        dialog.setMinimumSize(400, 200)
        
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel(f"Текущая ветка: {current_branch}"))
        layout.addWidget(QLabel("Имя новой ветки:"))
        
        branch_edit = QLineEdit()
        branch_edit.setPlaceholderText("feature/new-feature")
        layout.addWidget(branch_edit)
        
        # Подсказки для имён веток
        tips_label = QLabel("Подсказки:\n"
                        "• feature/имя-фичи\n"
                        "• bugfix/описание-бага\n"
                        "• hotfix/срочное-исправление\n"
                        "• release/версия")
        tips_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(tips_label)
        
        button_box = QDialogButtonBox()
        create_btn = button_box.addButton("🌿 Create Branch", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        
        layout.addWidget(button_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            branch_name = branch_edit.text().strip()
            if not branch_name:
                QMessageBox.warning(self, "Ошибка", "Имя ветки не может быть пустым!")
                return
            
            success = self.git_manager.create_branch(self.current_path, branch_name)
            if success:
                self.log(f"🌿 Ветка создана: {branch_name}", "info")
                
                # Предлагаем переключиться на новую ветку
                reply = QMessageBox.question(
                    self, "Switch to New Branch",
                    f"Ветка '{branch_name}' создана.\n\n"
                    f"Хотите переключиться на неё?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.Yes:
                    self.checkout_git_branch()
                
                # Обновляем Git виджет если открыт
                if hasattr(self, 'git_widget') and self.git_widget.isVisible():
                    self.git_widget.refresh_git_info()
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось создать ветку!")

    def checkout_git_branch(self):
        """Переключаемся на ветку"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙) для установки.")
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку!")
            return
        
        branches = self.git_manager.get_branches(self.current_path)
        if not branches:
            QMessageBox.information(self, "Git Branches", "Нет доступных веток")
            return
        
        # Получаем текущую ветку
        status = self.git_manager.get_status(self.current_path)
        current_branch = status.get('branch', 'unknown') if status.get('is_git') else 'unknown'
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Checkout Git Branch")
        dialog.setMinimumSize(300, 400)
        
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel(f"Текущая ветка: {current_branch}"))
        layout.addWidget(QLabel("Выберите ветку:"))
        
        branch_list = QListWidget()
        for branch in branches:
            item = QListWidgetItem(branch)
            if branch == current_branch:
                item.setText(f"✅ {branch} (current)")
                item.setForeground(QColor(0, 200, 0))
            branch_list.addItem(item)
        
        layout.addWidget(branch_list)
        
        button_box = QDialogButtonBox()
        checkout_btn = button_box.addButton("🔄 Checkout", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        
        layout.addWidget(button_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_items = branch_list.selectedItems()
            if not selected_items:
                return
            
            branch = selected_items[0].text()
            # Убираем эмодзи если есть
            if branch.startswith("✅ "):
                branch = branch[2:].replace(" (current)", "")
            
            # Сохраняем все файлы перед переключением
            self.save_all()
            
            success = self.git_manager.checkout_branch(self.current_path, branch)
            if success:
                self.log(f"🔄 Переключился на ветку: {branch}", "info")
                
                # Обновляем Git виджет если открыт
                if hasattr(self, 'git_widget') and self.git_widget.isVisible():
                    self.git_widget.refresh_git_info()
                
                # Показываем уведомление
                QMessageBox.information(self, "Branch Switched", 
                                    f"Успешно переключились на ветку: {branch}")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось переключиться на ветку!")

    def show_git_log(self):
        """Показываем историю коммитов"""
        if not hasattr(self, 'git_manager') or not self.git_manager.git_installed:
            QMessageBox.information(self, "Git не установлен", 
                                "Для использования Git требуется установить Git.\n\n"
                                "Откройте Git панель (кнопка 🐙) для установки.")
            return
        
        if not self.current_path:
            QMessageBox.warning(self, "Ошибка", "Сначала откройте папку!")
            return
        
        history = self.git_manager.get_history(self.current_path, 50)
        if not history:
            QMessageBox.information(self, "Git Log", "Нет истории коммитов")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Git Log")
        dialog.setMinimumSize(700, 500)
        
        layout = QVBoxLayout(dialog)
        
        # Фильтр поиска
        search_layout = QHBoxLayout()
        search_label = QLabel("🔍 Поиск:")
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Поиск по сообщению или автору...")
        search_layout.addWidget(search_label)
        search_layout.addWidget(search_edit)
        layout.addLayout(search_layout)
        
        # Таблица истории
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Хэш", "Сообщение", "Автор", "Дата", "Файлы"])
        table.horizontalHeader().setStretchLastSection(True)
        
        for i, commit in enumerate(history):
            table.insertRow(i)
            
            # Хэш
            hash_item = QTableWidgetItem(commit['hash'])
            hash_item.setFont(QFont("Consolas", 10))
            table.setItem(i, 0, hash_item)
            
            # Сообщение
            message_item = QTableWidgetItem(commit['message'])
            table.setItem(i, 1, message_item)
            
            # Автор
            author_item = QTableWidgetItem(commit['author'])
            table.setItem(i, 2, author_item)
            
            # Дата
            date_item = QTableWidgetItem(commit['date'])
            table.setItem(i, 3, date_item)
            
            # Файлы
            files_text = ", ".join(commit['files']) if commit['files'] else "—"
            files_item = QTableWidgetItem(files_text)
            table.setItem(i, 4, files_item)
        
        table.resizeColumnsToContents()
        layout.addWidget(table)
        
        # Информация о выбранном коммите
        info_label = QLabel("Выберите коммит для просмотра деталей")
        layout.addWidget(info_label)
        
        # Кнопки
        button_box = QDialogButtonBox()
        refresh_btn = button_box.addButton("🔄 Refresh", QDialogButtonBox.ButtonRole.ActionRole)
        close_btn = button_box.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        
        refresh_btn.clicked.connect(lambda: self.show_git_log())
        refresh_btn.clicked.connect(dialog.accept)
        close_btn.clicked.connect(dialog.reject)
        
        layout.addWidget(button_box)
        
        # Фильтрация поиска
        def filter_history():
            search_text = search_edit.text().lower()
            for i in range(table.rowCount()):
                show = False
                if search_text:
                    # Проверяем все колонки кроме файлов
                    for col in range(4):
                        item = table.item(i, col)
                        if item and search_text in item.text().lower():
                            show = True
                            break
                else:
                    show = True
                
                table.setRowHidden(i, not show)
        
        search_edit.textChanged.connect(filter_history)
        
        # Обработка выбора коммита
        def on_item_selected():
            selected_items = table.selectedItems()
            if selected_items:
                row = selected_items[0].row()
                commit = history[row]
                info_label.setText(
                    f"📌 Коммит: {commit['hash']}\n"
                    f"📝 Сообщение: {commit['message']}\n"
                    f"👤 Автор: {commit['author']}\n"
                    f"📅 Дата: {commit['date']}\n"
                    f"📁 Файлов изменено: {len(commit['files'])}"
                )
        
        table.itemSelectionChanged.connect(on_item_selected)
        
        dialog.exec()

    def install_git_tool(self):
        """Установка Git инструмента"""
        if hasattr(self, 'git_widget'):
            # Показываем Git панель
            self.git_widget.setVisible(True)
            self.btn_git.setChecked(True)
            
            # Вызываем метод установки Git
            self.git_widget.install_git()
        else:
            # Если виджет ещё не создан, предлагаем скачать Git
            reply = QMessageBox.question(
                self, "Установка Git",
                "Git требуется для работы с системами контроля версий.\n\n"
                "Хотите открыть страницу скачивания Git?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                webbrowser.open("https://git-scm.com/download/win")
                
                QMessageBox.information(
                    self,
                    "Инструкция по установке",
                    "После установки Git:\n"
                    "1. Перезапустите LudvigEditor\n"
                    "2. Убедитесь, что Git добавлен в PATH\n"
                    "3. Функции Git будут доступны автоматически\n\n"
                    "Рекомендуется выбрать опцию 'Add Git to PATH' при установке."
                )

    def on_git_status_changed(self, path: str, status: dict):
        """Обработка изменения статуса Git"""
        self.log(f"📊 Git статус обновлён: {os.path.basename(path)}", "info")
        
    def on_git_branch_changed(self, path: str, branch: str):
        """Обработка смены ветки Git"""
        self.log(f"🌿 Ветка изменена: {branch}", "info")
        
    def on_git_commit_made(self, path: str, commit_hash: str):
        """Обработка создания коммита Git"""
        self.log(f"💾 Коммит создан: {commit_hash}", "success")
        
    def on_git_error(self, path: str, error: str):
        """Обработка ошибки Git"""
        self.log(f"❌ Git ошибка: {error}", "error")
        
    def on_git_not_installed(self):
        """Обработка отсутствия Git"""
        self.log("⚠️ Git не установлен. Откройте Git панель для установки.", "warning")
    
    def setup_shortcuts(self):
        """Настраиваем горячие клавиши"""
        # Основные
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_current)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.find_in_file)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo_current)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo_current)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_file)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self.open_file)
        QShortcut(QKeySequence("F5"), self, activated=self.run_code)
        
        # Навигация по вкладкам
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=self.next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=self.previous_tab)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close_current)
        
        # Терминал
        QShortcut(QKeySequence("Ctrl+`"), self, activated=self.toggle_terminal)
        
        # Поиск
        QShortcut(QKeySequence("Ctrl+Shift+F"), self, activated=self.find_in_files)
    
    def setup_signals(self):
        """Настраиваем сигналы"""
        # Сигналы от менеджера расширений (если он создан)
        if hasattr(self, 'ext_manager') and self.ext_manager:
            self.ext_manager.extension_loaded.connect(self.on_extension_loaded)
            self.ext_manager.extension_unloaded.connect(self.on_extension_unloaded)
            self.ext_manager.extension_installed.connect(self.on_extension_installed)
            self.ext_manager.extension_uninstalled.connect(self.on_extension_uninstalled)
            self.ext_manager.extension_error.connect(self.on_extension_error)
        
        # Сигналы от API (если он создан)
        if hasattr(self, 'api') and self.api:
            self.api.editor_ready.connect(self.on_editor_ready)
            self.api.file_opened.connect(self.on_file_opened)
            self.api.file_saved.connect(self.on_file_saved)
            self.api.file_closed.connect(self.on_file_closed)
        
        # Сигналы от Git менеджера (если он создан)
        if hasattr(self, 'git_manager') and self.git_manager:
            self.git_manager.git_status_changed.connect(self.on_git_status_changed)
            self.git_manager.git_branch_changed.connect(self.on_git_branch_changed)
            self.git_manager.git_commit_made.connect(self.on_git_commit_made)
            self.git_manager.git_error.connect(self.on_git_error)
            self.git_manager.git_not_installed.connect(self.on_git_not_installed)

        # Сигналы от менеджера обновлений
        if hasattr(self, 'update_manager') and self.update_manager:
            self.update_manager.update_downloaded.connect(self.on_update_downloaded)
    
    def style_tabs(self):
        """Стилизуем вкладки"""
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background: #1a1b3a;
            }
            QTabBar::tab {
                background: rgba(255, 255, 255, 0.1);
                color: rgba(255, 255, 255, 0.7);
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
                min-width: 100px;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: rgba(91, 60, 196, 0.8);
                color: white;
                font-weight: bold;
            }
            QTabBar::tab:hover {
                background: rgba(91, 60, 196, 0.5);
            }
            QTabBar::close-button {
                image: url(none);
                subcontrol-position: right;
                padding: 2px;
            }
            QTabBar::close-button:hover {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
            }
        """)
    
    def style_terminal(self):
        """Стилизуем терминал"""
        self.terminal.setStyleSheet("""
            QTextEdit {
                background: #0f1224;
                color: #dcd7ff;
                border: none;
                border-top: 1px solid rgba(255, 255, 255, 0.1);
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                padding: 10px;
            }
            QScrollBar:vertical {
                background: rgba(255, 255, 255, 0.05);
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: rgba(130, 130, 220, 0.4);
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(130, 130, 220, 0.6);
            }
        """)
    
    # ===== Методы для работы с файлами =====
    def new_file(self):
        """Создаем новый файл"""
        dialog = QInputDialog(self)
        dialog.setWindowTitle("New File")
        dialog.setLabelText("Enter file name:")
        dialog.setTextValue("untitled.py")
        
        if dialog.exec():
            filename = dialog.textValue()
            if filename:
                # Создаем временный файл
                temp_dir = tempfile.gettempdir()
                filepath = os.path.join(temp_dir, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write("# New file\n")
                
                self.open_tab(filepath)
    
    def open_file(self):
        """Открываем файл"""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open File", "",
            "All Files (*.*);;Python Files (*.py);;JavaScript Files (*.js);;"
            "HTML Files (*.html *.htm);;CSS Files (*.css);;JSON Files (*.json)"
        )
        
        if path:
            self.open_tab(path)
    
    def open_folder(self):
        """Открываем папку"""
        path = QFileDialog.getExistingDirectory(self, "Open Folder")
        if path:
            # Устанавливаем корневую папку в проводнике
            model = self.explorer.model()
            if model:
                self.explorer.setRootIndex(model.index(path))
                self.status_label.setText(f"Project: {path}")
    
    def open_tab(self, path: str):
        """Открываем файл в новой вкладке"""
        try:
            # Читаем файл
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Определяем язык по расширению
            _, ext = os.path.splitext(path)
            ext = ext.lower()
            
            lang_map = {
                '.py': 'python',
                '.js': 'javascript',
                '.html': 'html',
                '.htm': 'html',
                '.css': 'css',
                '.json': 'json',
                '.xml': 'xml',
                '.md': 'markdown',
                '.txt': 'plaintext',
                '.c': 'c',
                '.cpp': 'cpp',
                '.h': 'c',
                '.hpp': 'cpp',
                '.java': 'java',
                '.php': 'php',
                '.rb': 'ruby',
                '.go': 'go',
                '.rs': 'rust',
                '.swift': 'swift',
                '.kt': 'kotlin',
                '.ts': 'typescript',
                '.sql': 'sql',
                '.sh': 'shell',
                '.bat': 'bat',
                '.ps1': 'powershell',
                '.yml': 'yaml',
                '.yaml': 'yaml',
                '.toml': 'toml',
                '.ini': 'ini',
                '.cfg': 'ini'
            }
            
            language = lang_map.get(ext, 'plaintext')
            
            # Создаем WebView
            view = QWebEngineView()
            view.setUrl(EDITOR_URL)
            
            # Добавляем вкладку
            tab_index = self.tabs.addTab(view, os.path.basename(path))
            self.tabs.setCurrentIndex(tab_index)
            
            # Сохраняем данные
            self.tabs_data.append({
                'path': path,
                'view': view,
                'language': language,
                'content': content
            })
            
            # Переключаемся на редактор
            self.stack.setCurrentIndex(1)
            
            # Загружаем код в редактор (с задержкой для загрузки WebView)
            QTimer.singleShot(500, lambda: self._load_code_to_view(view, content, language))
            
            # Обновляем статус
            self.status_label.setText(f"Opened: {path}")
            self.language_label.setText(language)
            
            # Сигнал для расширений
            self.api.file_opened.emit(path)
            
            # Загружаем расширения в эту вкладку
            self._load_extensions_to_view(view)
            
        except Exception as e:
            self.log(f"❌ Error opening file {path}: {e}", "error")
            QMessageBox.critical(self, "Error", f"Cannot open file:\n{path}\n\n{str(e)}")
    
    def _load_code_to_view(self, view, content: str, language: str):
        """Загружаем код в WebView"""
        escaped_content = json.dumps(content)
        js_code = f"window.setCode({escaped_content}, '{language}')"
        view.page().runJavaScript(js_code)
    
    def _load_extensions_to_view(self, view):
        """Загружаем расширения в WebView"""
        # Загружаем JS расширения
        for name, js_code in self.ext_manager.js_extensions.items():
            self.ext_manager._inject_js_to_view(view, name, js_code)
    
    def save_current(self):
        """Сохраняем текущий файл"""
        current_index = self.tabs.currentIndex()
        if current_index < 0 or current_index >= len(self.tabs_data):
            return
        
        data = self.tabs_data[current_index]
        view = data['view']
        path = data['path']
        
        # Получаем код из редактора
        view.page().runJavaScript("window.getCode()", 
            lambda content: self._save_file_content(path, content))
    
    def _save_file_content(self, path: str, content: str):
        """Сохраняем содержимое в файл"""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self.log(f"💾 Saved: {path}")
            self.status_label.setText(f"Saved: {os.path.basename(path)}")
            
            # Сигнал для расширений
            self.api.file_saved.emit(path)
            
        except Exception as e:
            self.log(f"❌ Error saving file: {e}", "error")
            QMessageBox.critical(self, "Error", f"Cannot save file:\n{path}\n\n{str(e)}")
    
    def save_as(self):
        """Сохраняем как..."""
        current_index = self.tabs.currentIndex()
        if current_index < 0 or current_index >= len(self.tabs_data):
            return
        
        data = self.tabs_data[current_index]
        view = data['view']
        old_path = data['path']
        
        # Диалог выбора файла
        path, _ = QFileDialog.getSaveFileName(
            self, "Save As", old_path,
            "All Files (*.*);;Python Files (*.py);;JavaScript Files (*.js);;"
            "HTML Files (*.html *.htm);;CSS Files (*.css);;JSON Files (*.json)"
        )
        
        if path:
            # Получаем код и сохраняем
            view.page().runJavaScript("window.getCode()", 
                lambda content: self._save_file_content(path, content))
            
            # Обновляем данные вкладки
            data['path'] = path
            self.tabs.setTabText(current_index, os.path.basename(path))
    
    def save_all(self):
        """Сохраняем все открытые файлы"""
        for i, data in enumerate(self.tabs_data):
            view = data['view']
            path = data['path']
            
            view.page().runJavaScript("window.getCode()", 
                lambda content, p=path: self._save_file_content(p, content))
    
    def close_current(self):
        """Закрываем текущую вкладку"""
        current_index = self.tabs.currentIndex()
        if current_index >= 0:
            self.close_tab(current_index)
    
    def close_tab(self, index: int):
        """Закрываем вкладку по индексу"""
        if 0 <= index < len(self.tabs_data):
            data = self.tabs_data[index]
            path = data['path']
            
            # Сигнал для расширений
            self.api.file_closed.emit(path)
            
            # Удаляем данные
            self.tabs_data.pop(index)
            self.tabs.removeTab(index)
            
            # Если вкладок не осталось, показываем welcome screen
            if self.tabs.count() == 0:
                self.stack.setCurrentIndex(0)
    
    def close_all(self):
        """Закрываем все вкладки"""
        while self.tabs.count() > 0:
            self.close_tab(0)
    
    def next_tab(self):
        """Переходим на следующую вкладку"""
        current = self.tabs.currentIndex()
        next_index = (current + 1) % self.tabs.count()
        self.tabs.setCurrentIndex(next_index)
    
    def previous_tab(self):
        """Переходим на предыдущую вкладку"""
        current = self.tabs.currentIndex()
        prev_index = (current - 1) % self.tabs.count()
        self.tabs.setCurrentIndex(prev_index)
    
    # ===== Методы для работы с кодом =====
    def undo_current(self):
        """Отменяем последнее действие"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            view = self.tabs_data[current_index]['view']
            view.page().runJavaScript("window.editor.trigger('', 'undo')")
    
    def redo_current(self):
        """Повторяем отмененное действие"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            view = self.tabs_data[current_index]['view']
            view.page().runJavaScript("window.editor.trigger('', 'redo')")
    
    def cut_current(self):
        """Вырезаем выделенный текст"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            view = self.tabs_data[current_index]['view']
            view.page().runJavaScript("document.execCommand('cut')")
    
    def copy_current(self):
        """Копируем выделенный текст"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            view = self.tabs_data[current_index]['view']
            view.page().runJavaScript("document.execCommand('copy')")
    
    def paste_current(self):
        """Вставляем текст"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            view = self.tabs_data[current_index]['view']
            view.page().runJavaScript("document.execCommand('paste')")
    
    def find_in_file(self):
        """Поиск в текущем файле"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            view = self.tabs_data[current_index]['view']
            view.page().runJavaScript("window.editor.getAction('actions.find').run()")
    
    def replace_in_file(self):
        """Замена в текущем файле"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            view = self.tabs_data[current_index]['view']
            view.page().runJavaScript("window.editor.getAction('editor.action.startFindReplaceAction').run()")
    
    def find_in_files(self):
        """Поиск по всем файлам"""
        # TODO: Реализовать поиск по файлам
        self.log("🔍 Search in files (not implemented yet)", "info")
    
    # ===== Методы запуска кода =====
    def run_code(self):
        """Запускаем текущий файл"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            data = self.tabs_data[current_index]
            path = data['path']
            
            # Сохраняем перед запуском
            self.save_current()
            
            # Определяем как запускать
            _, ext = os.path.splitext(path)
            ext = ext.lower()
            
            if ext == '.py':
                self._run_python(path)
            elif ext == '.js':
                self._run_javascript(path)
            elif ext == '.html':
                self._run_html(path)
            else:
                self.log(f"⚠️ Cannot run {ext} files", "warning")
    
    def _run_python(self, path: str):
        """Запускаем Python файл"""
        try:
            self.terminal.clear()
            self.log(f"▶ Running Python: {path}", "info")
            
            # Запускаем в отдельном потоке
            thread = threading.Thread(target=self._execute_python, args=(path,))
            thread.daemon = True
            thread.start()
            
        except Exception as e:
            self.log(f"❌ Error running Python: {e}", "error")
    
    def _execute_python(self, path: str):
        """Выполняем Python код"""
        try:
            result = subprocess.run(
                [sys.executable, path],
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            
            # Выводим результат в терминал
            output = f"""Running: {path}
Exit code: {result.returncode}

{'='*50}
STDOUT:
{result.stdout}

{'='*50}
STDERR:
{result.stderr}
{'='*50}
"""
            
            # Обновляем UI из главного потока
            QTimer.singleShot(0, lambda: self.terminal.append(output))
            
        except Exception as e:
            error_msg = f"❌ Execution error: {e}"
            QTimer.singleShot(0, lambda: self.terminal.append(error_msg))
    
    def _run_javascript(self, path: str):
        """Запускаем JavaScript файл"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                js_code = f.read()
            
            self.terminal.clear()
            self.log(f"▶ Running JavaScript: {path}", "info")
            
            # Пытаемся выполнить через node.js если установлен
            try:
                result = subprocess.run(
                    ['node', '-e', js_code],
                    capture_output=True,
                    text=True,
                    encoding='utf-8'
                )
                
                output = f"""Running JavaScript: {path}
Exit code: {result.returncode}

{'='*50}
STDOUT:
{result.stdout}

{'='*50}
STDERR:
{result.stderr}
{'='*50}
"""
                self.terminal.append(output)
                
            except FileNotFoundError:
                # Node.js не установлен, выполняем в браузере
                self.log("⚠️ Node.js not found, opening in browser", "warning")
                
                # Создаем временный HTML файл
                temp_html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Run JS: {os.path.basename(path)}</title>
</head>
<body>
    <script>
        console.log("Running: {path}");
        try {{
            {js_code}
        }} catch (e) {{
            console.error("Error:", e);
        }}
    </script>
</body>
</html>
"""
                
                # Сохраняем и открываем
                temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False)
                temp_file.write(temp_html)
                temp_file.close()
                
                import webbrowser
                webbrowser.open(f'file://{temp_file.name}')
                
        except Exception as e:
            self.log(f"❌ Error running JavaScript: {e}", "error")
    
    def _run_html(self, path: str):
        """Запускаем HTML файл в браузере"""
        try:
            import webbrowser
            webbrowser.open(f'file://{path}')
            self.log(f"🌐 Opening in browser: {path}", "info")
        except Exception as e:
            self.log(f"❌ Error opening browser: {e}", "error")
    
    def debug_code(self):
        """Запускаем отладку"""
        # TODO: Реализовать отладку
        self.log("🐞 Debug (not implemented yet)", "info")
    
    # ===== Методы для проводника =====
    def toggle_explorer(self):
        """Показываем/скрываем проводник"""
        self.explorer.setVisible(not self.explorer.isVisible())
        self.btn_explorer.setChecked(self.explorer.isVisible())
    
    def open_from_explorer(self, index):
        """Открываем файл из проводника"""
        model = self.explorer.model()
        if model:
            path = model.filePath(index)
            if os.path.isfile(path):
                self.open_tab(path)
    
    def explorer_menu(self, position):
        """Контекстное меню проводника"""
        index = self.explorer.indexAt(position)
        if not index.isValid():
            return
        
        model = self.explorer.model()
        path = model.filePath(index)
        
        menu = QMenu()
        
        if os.path.isfile(path):
            open_action = menu.addAction("📂 Open")
            open_action.triggered.connect(lambda: self.open_tab(path))
            
            menu.addSeparator()
            
            rename_action = menu.addAction("✏️ Rename")
            rename_action.triggered.connect(lambda: self.rename_file(path))
            
            delete_action = menu.addAction("🗑 Delete")
            delete_action.triggered.connect(lambda: self.delete_file(path))
            
        elif os.path.isdir(path):
            new_file_action = menu.addAction("📄 New File")
            new_file_action.triggered.connect(lambda: self.create_file_in(path))
            
            new_folder_action = menu.addAction("📁 New Folder")
            new_folder_action.triggered.connect(lambda: self.create_folder_in(path))
            
            menu.addSeparator()
            
            rename_action = menu.addAction("✏️ Rename")
            rename_action.triggered.connect(lambda: self.rename_file(path))
            
            delete_action = menu.addAction("🗑 Delete")
            delete_action.triggered.connect(lambda: self.delete_folder(path))
        
        menu.addSeparator()
        
        properties_action = menu.addAction("📊 Properties")
        properties_action.triggered.connect(lambda: self.show_properties(path))
        
        menu.exec(self.explorer.mapToGlobal(position))
    
    def create_file_in(self, folder: str):
        """Создаем файл в папке"""
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if ok and name:
            path = os.path.join(folder, name)
            with open(path, 'w', encoding='utf-8') as f:
                f.write("")
            self.open_tab(path)
    
    def create_folder_in(self, folder: str):
        """Создаем папку в папке"""
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name:
            path = os.path.join(folder, name)
            os.makedirs(path, exist_ok=True)
    
    def rename_file(self, path: str):
        """Переименовываем файл или папку"""
        new_name, ok = QInputDialog.getText(
            self, "Rename", 
            f"New name for {os.path.basename(path)}:",
            text=os.path.basename(path)
        )
        
        if ok and new_name and new_name != os.path.basename(path):
            new_path = os.path.join(os.path.dirname(path), new_name)
            try:
                os.rename(path, new_path)
                
                # Обновляем вкладку если файл открыт
                for data in self.tabs_data:
                    if data['path'] == path:
                        data['path'] = new_path
                        index = self.tabs.indexOf(data['view'])
                        self.tabs.setTabText(index, new_name)
                        break
                        
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Cannot rename:\n{str(e)}")
    
    def delete_file(self, path: str):
        """Удаляем файл"""
        reply = QMessageBox.question(
            self, "Delete File",
            f"Delete {os.path.basename(path)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(path)
                
                # Закрываем вкладку если файл открыт
                for i, data in enumerate(self.tabs_data):
                    if data['path'] == path:
                        self.close_tab(i)
                        break
                        
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Cannot delete:\n{str(e)}")
    
    def delete_folder(self, path: str):
        """Удаляем папку"""
        reply = QMessageBox.question(
            self, "Delete Folder",
            f"Delete folder {os.path.basename(path)} and all its contents?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                shutil.rmtree(path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Cannot delete folder:\n{str(e)}")
    
    def show_properties(self, path: str):
        """Показываем свойства файла/папки"""
        try:
            stat = os.stat(path)
            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime)
            
            if os.path.isfile(path):
                type_str = "File"
            else:
                type_str = "Folder"
                # Размер папки сложно посчитать
                size = "N/A"
            
            info = f"""Path: {path}
Type: {type_str}
Size: {size}
Modified: {mtime}
"""
            
            QMessageBox.information(self, "Properties", info)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot get properties:\n{str(e)}")
    
    # ===== Методы для расширений =====
    def toggle_extensions(self):
        """Показываем/скрываем менеджер расширений"""
        visible = not self.ext_widget.isVisible()
        self.ext_widget.setVisible(visible)
        self.btn_extensions.setChecked(visible)
    
    def show_extensions(self):
        """Показываем менеджер расширений"""
        self.ext_widget.setVisible(True)
        self.btn_extensions.setChecked(True)
        self.ext_widget.refresh_list()
    
    def install_extension(self):
        """Устанавливаем расширение"""
        self.ext_widget.install_extension()
    
    def reload_extensions(self):
        """Перезагружаем все расширения"""
        self.ext_widget.reload_all()
    
    def get_all_views(self):
        """Получаем все открытые WebView"""
        return [data['view'] for data in self.tabs_data]
    
    def get_current_file(self) -> Optional[str]:
        """Получаем текущий открытый файл"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            return self.tabs_data[current_index]['path']
        return None
    
    def get_current_code(self) -> str:
        """Получаем код из текущего редактора"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            # TODO: Реализовать получение кода из WebView
            return self.tabs_data[current_index]['content']
        return ""
    
    def set_current_code(self, code: str):
        """Устанавливаем код в текущем редакторе"""
        current_index = self.tabs.currentIndex()
        if 0 <= current_index < len(self.tabs_data):
            data = self.tabs_data[current_index]
            view = data['view']
            self._load_code_to_view(view, code, data['language'])
    
    def on_tab_changed(self, index: int):
        """Обработка смены вкладки"""
        if 0 <= index < len(self.tabs_data):
            data = self.tabs_data[index]
            self.language_label.setText(data['language'])
            self.status_label.setText(f"Editing: {data['path']}")
            
            # ОБНОВЛЯЕМ GIT WIDGET ПРИ СМЕНЕ ВКЛАДКИ
            if self.git_widget.isVisible():
                self.git_widget.update_path(self.current_path)
    
    def on_extension_loaded(self, name: str):
        """Обработка загрузки расширения"""
        self.log(f"✅ Extension loaded: {name}", "info")
        self.status_label.setText(f"Extension loaded: {name}")
    
    def on_extension_unloaded(self, name: str):
        """Обработка выгрузки расширения"""
        self.log(f"🚫 Extension unloaded: {name}", "info")
    
    def on_extension_installed(self, name: str):
        """Обработка установки расширения"""
        self.log(f"📦 Extension installed: {name}", "info")
        self.status_label.setText(f"Extension installed: {name}")
    
    def on_extension_uninstalled(self, name: str):
        """Обработка удаления расширения"""
        self.log(f"🗑 Extension uninstalled: {name}", "info")
    
    def on_extension_error(self, name: str, error: str):
        """Обработка ошибки расширения"""
        self.log(f"❌ Extension error ({name}): {error}", "error")
        QMessageBox.warning(self, "Extension Error", 
                          f"Error in extension '{name}':\n\n{error}")
    
    def on_editor_ready(self):
        """Обработка готовности редактора"""
        self.log("✅ Editor ready", "info")
    
    def on_file_opened(self, path: str):
        """Обработка открытия файла"""
        self.log(f"📂 File opened: {path}", "info")
    
    def on_file_saved(self, path: str):
        """Обработка сохранения файла"""
        self.log(f"💾 File saved: {path}", "info")
    
    def on_file_closed(self, path: str):
        """Обработка закрытия файла"""
        self.log(f"📂 File closed: {path}", "info")
    
    # ===== Другие методы =====
    def toggle_terminal(self):
        """Показываем/скрываем терминал"""
        self.terminal.setVisible(not self.terminal.isVisible())
    
    def show_search(self):
        """Показываем поиск"""
        self.find_in_file()
    
    def show_git(self):
        """Показываем Git панель"""
        # TODO: Реализовать Git интеграцию
        self.log("🐙 Git (not implemented yet)", "info")
    
    def show_debug(self):
        """Показываем отладчик"""
        self.debug_code()
    
    def show_settings(self):
        """Показываем настройки"""
        # TODO: Реализовать настройки
        self.log("⚙️ Settings (not implemented yet)", "info")
    
    def toggle_fullscreen(self):
        """Переключаем полноэкранный режим"""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
    
    def show_docs(self):
        """Показываем документацию"""
        QMessageBox.information(self, "Documentation",
                              "LudvigEditor Documentation\n\n"
                              "Version: 1.0.0\n"
                              "Author: Ludvig2457\n\n"
                              "A modern code editor with full extension support.")
    
    def show_about(self):
        """Показываем информацию о программе"""
        about_text = f"""
        <h2>LudvigEditor</h2>
        <p>Version: {APP_VERSION}</p>
        <p>A modern code editor with full extension support</p>
        <p>Built with PyQt6 and web technologies</p>
        <hr>
        <p>Author: Ludvig2457</p>
        <p>GitHub: <a href="https://github.com/ludvig2457">ludvig2457</a></p>
        <p>Email: ludvig@example.com</p>
        """
        
        msg = QMessageBox(self)
        msg.setWindowTitle("About LudvigEditor")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(about_text)
        msg.setIconPixmap(QPixmap())  # Можно добавить иконку
        msg.exec()
    
    def log(self, message: str, level: str = "info"):
        """Логирование в терминал с защитой от отсутствия terminal"""
        # Проверяем создан ли terminal
        if not hasattr(self, 'terminal') or self.terminal is None:
            # Если terminal ещё не создан, просто выводим в консоль
            print(f"[{level.upper()}] {message}")
            return
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if level == "error":
            color = "#ff6b6b"
            prefix = "❌"
        elif level == "warning":
            color = "#ffa500"
            prefix = "⚠️"
        elif level == "info":
            color = "#4ecdc4"
            prefix = "ℹ️"
        elif level == "success":
            color = "#5cdb95"
            prefix = "✅"
        else:
            color = "#ffffff"
            prefix = "📝"
        
        html = f'<span style="color:{color}">[{timestamp}] {prefix} {message}</span><br>'
        self.terminal.append(html)
        
        # Прокручиваем вниз
        scrollbar = self.terminal.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def restore_settings(self):
        """Восстанавливаем настройки"""
        # Геометрия окна
        geometry = SETTINGS.value("geometry")
        if geometry:
            self.restoreGeometry(QByteArray.fromHex(geometry.encode()))
        
        # Состояние разделителей
        splitter_state = SETTINGS.value("splitter_state")
        if splitter_state:
            self.main_splitter.restoreState(QByteArray.fromHex(splitter_state.encode()))
        
        # Видимость панелей
        explorer_visible = SETTINGS.value("explorer_visible", True, type=bool)
        self.explorer.setVisible(explorer_visible)
        self.btn_explorer.setChecked(explorer_visible)
        
        terminal_visible = SETTINGS.value("terminal_visible", True, type=bool)
        self.terminal.setVisible(terminal_visible)
    
    def closeEvent(self, event):
        """Обработка закрытия окна"""
        # Сохраняем настройки
        SETTINGS.setValue("geometry", self.saveGeometry().toHex().decode())
        SETTINGS.setValue("splitter_state", self.main_splitter.saveState().toHex().decode())
        SETTINGS.setValue("explorer_visible", self.explorer.isVisible())
        SETTINGS.setValue("terminal_visible", self.terminal.isVisible())
        
        # Сохраняем все файлы
        self.save_all()
        
        # Выгружаем расширения
        self.ext_manager.reload_all_extensions()
        
        event.accept()

# ===== Главная функция =====
def main():
    app = QApplication(sys.argv)
    
    # ЗАГРУЗКА ИКОНКИ ПРИЛОЖЕНИЯ
    # Сначала пробуем загрузить иконку из текущей папки
    icon_path = "LudvigEditor.png"
    
    # Если не нашли в текущей папке, пробуем рядом с исполняемым файлом
    if not os.path.exists(icon_path):
        # Получаем директорию, где находится скрипт
        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "LudvigEditor.png")
    
    # Пробуем загрузить PNG
    if os.path.exists(icon_path):
        try:
            app.setWindowIcon(QIcon(icon_path))
            print(f"✅ Иконка загружена: {icon_path}")
        except Exception as e:
            print(f"❌ Ошибка загрузки PNG иконки: {e}")
            # Пробуем альтернативные форматы
            icon_path_ico = icon_path.replace('.png', '.ico')
            if os.path.exists(icon_path_ico):
                try:
                    app.setWindowIcon(QIcon(icon_path_ico))
                    print(f"✅ Загружена ICO иконка: {icon_path_ico}")
                except Exception as e2:
                    print(f"❌ Ошибка загрузки ICO иконки: {e2}")
    else:
        # Пробуем другие возможные пути
        alt_paths = [
            "icon.png",
            "icon.ico",
            "LudvigEditor.ico",
            os.path.join(os.path.expanduser("~"), "LudvigEditor.png"),
            os.path.join(os.getcwd(), "LudvigEditor.png")
        ]
        
        for alt_path in alt_paths:
            if os.path.exists(alt_path):
                try:
                    app.setWindowIcon(QIcon(alt_path))
                    print(f"✅ Альтернативная иконка загружена: {alt_path}")
                    break
                except Exception as e:
                    continue
        
        # Если вообще не нашли иконку
        if app.windowIcon().isNull():
            print("⚠️ Иконка не найдена, используется стандартная")
    
    # Настройка стиля приложения
    app.setStyle("Fusion")
    
    # Настройка палитры
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(26, 27, 58))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(40, 41, 82))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(50, 51, 102))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(63, 43, 150))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(155, 93, 229))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(155, 93, 229))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)
    
    # Создание и запуск главного окна
    window = LudvigEditor()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
