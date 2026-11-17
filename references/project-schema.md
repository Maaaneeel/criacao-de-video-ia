# Esquema do plano

O arquivo passado a `set-plan` deve ser JSON e conter `visual_bible` e `scenes`.

```json
{
  "visual_bible": {
    "style": "descrição",
    "characters": [{"id": "hero", "name": "Nome", "appearance": "...", "wardrobe": "..."}],
    "locations": [{"id": "room", "description": "..."}],
    "camera": "...",
    "palette": "..."
  },
  "scenes": [
    {
      "id": "scene-001",
      "duration_seconds": 5.0,
      "action": "...",
      "character_ids": ["hero"],
      "dialogue": [{"character_id": "hero", "text": "...", "voice_direction": "..."}],
      "sound": "...",
      "visible_speech": true,
      "continuity": "...",
      "references": []
    }
  ]
}
```

IDs de cena são estáveis. Não renumere cenas existentes ao inserir outra. Durações devem ser positivas. `visible_speech` decide se a etapa Sync é aplicável.

O estado operacional fica em `.video-ai/projects/<slug>/state.json`. Ele contém aprovações, modelos, mapa de vozes, ações, artefatos e histórico. Edite o plano pelo comando; não altere o estado manualmente enquanto houver jobs ativos.
