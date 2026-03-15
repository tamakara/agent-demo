"""兼容入口：转发到 ``app.user.services``。"""

from app.user.services.employee_service import EmployeeService

__all__ = ["EmployeeService"]

