# Provedores e contratos confirmados

Reconfirme estes contratos imediatamente antes de uma geração paga, pois modelos, preços e limites mudam.

## OpenRouter

- Diagnóstico: `GET https://openrouter.ai/api/v1/key`
- Autenticação: `Authorization: Bearer <key>`
- Geração de referência opcional: `POST https://openrouter.ai/api/v1/images`
- Geração de vídeo: `POST https://openrouter.ai/api/v1/videos`; consulte `GET /api/v1/videos/models`, persista o job, faça polling em `GET /api/v1/videos/{id}` e baixe em `GET /api/v1/videos/{id}/content`.
- `bytedance/seedance-2.5` aceita 4–30 s, 480p/720p, 9:16, referências multimodais e áudio opcional. Confira o catálogo em cada lote porque capacidades e preços variam.
- Descoberta de capacidade/preço: `GET /api/v1/images/models/{author}/{slug}/endpoints`
- Referências de imagem: `input_references` aceita URLs HTTP(S) ou data URLs. Use `local_references` no payload local para converter arquivos em memória, sem colocar base64 no estado.
- Resposta de imagem: `data[].b64_json`; decodifique e salve localmente, sem colocar base64 no estado.
- Modelo OpenRouter configurado inicialmente: `bytedance-seed/seedream-5-0-pro`. Registre o slug exato por ação.
- Só use OpenRouter para imagens quando o usuário o escolher. Nesse caso, não envie `FAL_KEY` e não faça fallback para fal.ai.
- A chave continua opcional para organização de história; ela só é obrigatória para operações OpenRouter.
- Referências: https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key, https://openrouter.ai/docs/api/api-reference/images/list-image-models e https://openrouter.ai/docs/features/multimodal/image-generation

## ElevenLabs

- Diagnóstico: `GET https://api.elevenlabs.io/v1/user/subscription`
- TTS: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}`
- Autenticação: `xi-api-key`
- Modelo configurado inicialmente: `eleven_v4`; consulte `GET /v1/models` e preserve o `voice_id` por personagem.
- Referências: https://elevenlabs.io/docs/api-reference/authentication e https://elevenlabs.io/docs/api-reference/text-to-speech/convert

## fal.ai

- Diagnóstico sem mídia: `GET https://api.fal.ai/v1/models/pricing?endpoint_id=<model>`
- Autenticação REST: `Authorization: Key <FAL_KEY>`
- Queue submit: `POST https://queue.fal.run/{model}`; persista imediatamente `request_id`, `status_url`, `response_url` e `cancel_url`.
- Defaults desta instalação:
  - Seedream: `bytedance/seedream/v5/pro/text-to-image`
  - Seedance: `bytedance/seedance-2.5/reference-to-video`
  - Mirelo: `mirelo-ai/sfx2.0/video-to-audio`
- Seedance 2.5 aceita até 30 segundos nos endpoints atuais; cada cena continua sendo uma geração separada.
- Mirelo `video-to-audio` aceita 1–600 s, limitado ao vídeo. Use `preserve_speech: false` quando a fala final vier da ElevenLabs.
- Referências: https://fal.ai/docs/api-reference/inference-api/queue/submit, https://fal.ai/docs/documentation/model-apis/pricing, https://fal.ai/seedance-2.5 e páginas `/api` dos modelos.

## Sync Labs

- Diagnóstico: `GET https://api.sync.so/v2/account`
- Geração: `POST https://api.sync.so/v2/generate`
- Assets locais: presign em `POST /v2/assets/upload`, PUT binário na URL assinada e registro em `POST /v2/assets`; persista apenas o `asset_id`.
- Consulta: `GET https://api.sync.so/v2/generate/{id}`
- Autenticação: `x-api-key`
- Use um `Idempotency-Key` UUID, salvo antes da primeira tentativa e repetido com corpo idêntico.
- Modelo configurado inicialmente: `sync-3`.
- Referências: https://sync.so/docs/api-reference/guides/authentication, https://sync.so/docs/api-reference/guides/idempotency e https://sync.so/docs/api-reference/api/generate-api/create

## Hyperframes

- Requer Node.js 22+, FFmpeg e ffprobe.
- Ordem: `check`, `preview --background`, aprovação, `render --quality delivery`, `ffprobe`.
- Leia `$hyperframes` e `$hyperframes-cli` antes de operar a composição.
