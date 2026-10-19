"""Explicit construction of application services."""

from splatforge.adapters.project_storage import LocalProjectStore
from splatforge.application.projects import ProjectService
from splatforge.core.builtin_methods import build_builtin_registry


def build_project_service() -> ProjectService:
    return ProjectService(LocalProjectStore(), build_builtin_registry())
