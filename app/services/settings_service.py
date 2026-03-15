"""兼容入口：转发到 ``app.user.services``。"""

from app.user.services.settings_service import SettingsService

__all__ = ["SettingsService"]

