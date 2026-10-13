from types import SimpleNamespace

from arbiter.platform.modules import DEFAULT_MODULES, org_has_module
from arbiter.platform.permissions import has_permission


def test_modules_default_and_dependencies():
    org = SimpleNamespace(settings={})
    assert all(org_has_module(org, m) for m in DEFAULT_MODULES)
    org = SimpleNamespace(settings={"modules": ["strings"]})
    assert not org_has_module(org, "strings")  # depends on tms
    org = SimpleNamespace(settings={"modules": ["tms", "strings"]})
    assert org_has_module(org, "strings") and not org_has_module(org, "pm")


def test_permissions_builtin_roles():
    assert has_permission(SimpleNamespace(role="admin"), "anything.at_all")
    assert has_permission(SimpleNamespace(role="pm"), "jobs.write")
    assert not has_permission(SimpleNamespace(role="client"), "billing.manage")
    assert has_permission(SimpleNamespace(role="client", permissions=["billing.manage"]), "billing.manage")
