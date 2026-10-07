"""Agency OS services: CRM, price lists, workflow templates, dashboards, AI assistant.

Routes (arbiter.api.routes.{crm,pricelists,workflows,dashboards,assistant}) are thin; the
assistant's apply step calls the same service functions, so a plan applied by a human goes
through exactly the validation a hand-made request would.
"""
