# SkillKit TODO

## Prioridad alta

- [x] Tests unitarios para `lib/__init__.py` (resolve_model, fallbacks, skill_model_overrides)
- [ ] Tests de integración para al menos un skill completo
- [x] CI/CD propio: GitHub Actions (pytest + ruff + verify install.sh)

## Prioridad media

- [x] Empaquetado PyPI: `pyproject.toml`, publish automático en tags
- [x] Balancear `models.json`: agregar modelos directos Anthropic/OpenAI/Google
- [ ] CLI portable: `skillkit run <skill>` para independencia del agente

## Prioridad baja

- [x] Agregar disclaimer "beta / experimental" en README
