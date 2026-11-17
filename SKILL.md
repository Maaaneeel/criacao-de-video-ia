---
name: criacao-de-video-ia
description: Planeja e produz vídeos narrativos por cenas usando OpenRouter ou fal.ai para referências visuais, Seedance, ElevenLabs, Mirelo, Sync Labs e opcionalmente Hyperframes, com persistência de jobs, retomada segura e aprovações antes das etapas pagas e da entrega. Use para criar ou revisar esse fluxo de produção; não use para uma edição simples de vídeo já existente.
---

# Criação de vídeo IA

Transforme uma ideia ou roteiro em cenas independentes, preserve continuidade visual e sonora e monte a revisão/final no Hyperframes. O projeto persistente configurado para esta instalação está em `project.json`; os segredos ficam exclusivamente no `.env` desse projeto.

## Regras invariáveis

- Nunca peça chaves no chat nem mostre valores, cabeçalhos autenticados ou URLs com segredos.
- Carregue credenciais somente por `scripts/video-ai`; ele usa o módulo central `video_ai_lib/config.py` e o `.env` absoluto configurado em `project.json`.
- Não inclua `.env`, credenciais ou respostas autenticadas em artefatos, prompts, estado ou logs.
- Não gere mídia para diagnosticar uma conexão. Use `scripts/video-ai diagnose`.
- Não trate autenticação como geração comprovada. Informe separadamente: implementado, autenticado e testado com geração.
- Não troque modelo ou provedor silenciosamente. Registre o identificador exato e a resposta do provedor no estado.
- Quando o usuário escolher OpenRouter para referências visuais, use `openrouter-image`, não envie `FAL_KEY` e não faça fallback para fal.ai. Referências locais entram no payload por `local_references`; o comando converte os arquivos em data URLs somente em memória. A escolha vale para o projeto atual, não como preferência universal.
- Quando o usuário escolher OpenRouter para vídeo, use `openrouter-video-submit` e `openrouter-video-poll`; aceite referências locais via `local_references` sem gravar base64 no estado. Não faça fallback silencioso para fal.ai.
- Um pedido explícito para gerar, criar ou produzir a mídia já autoriza a chamada paga necessária para o lote solicitado. Antes da chamada, informe escopo, modelo e custo estimado quando a API fornecer preço, mas não peça uma confirmação redundante: prossiga com `--yes-paid`. Essa autorização vale somente para o escopo pedido e para o provedor/modelo escolhido ou padrão configurado; não cobre ampliação do lote, troca de provedor/modelo nem nova tentativa potencialmente cobrada após resultado incerto.
- Salve a ação antes de submetê-la. Em resultado incerto, consulte o job existente; nunca crie outro para “tentar de novo”.
- Cada cena produz seu próprio clipe. Não substitua cenas separadas por um vídeo com cortes internos.
- Prepare prompts internamente. Só os mostre se o usuário pedir.
- Baixe o resultado assim que o job concluir. Links remotos são transitórios.

## Início de cada projeto

1. Execute `scripts/video-ai prepare-env`. Ele preserva o arquivo existente, acrescenta apenas campos ausentes e protege o `.env` no `.gitignore`.
2. Execute `scripts/video-ai diagnose`. Uma chave OpenRouter ausente não bloqueia o fluxo se o Codex organizar a história diretamente.
3. Execute `scripts/video-ai check-deps` antes de planejar montagem local.
4. Inicialize o estado com `scripts/video-ai init --slug <slug> --title <título> --idea-file <arquivo>`.
5. Leia [references/workflow.md](references/workflow.md). Para comandos, estado e recuperação, leia [references/operations.md](references/operations.md). Para endpoints, modelos e limites atuais, leia [references/providers.md](references/providers.md) e reconfirme a documentação oficial imediatamente antes de uma geração paga.

## Planejamento e aprovações

Crie o plano no esquema de [references/project-schema.md](references/project-schema.md) e grave-o com `scripts/video-ai set-plan --project <slug> --file <plan.json>`.

### Aprovação 1 — referências

Organize a história e uma bíblia visual. Use cenas em torno de 5 segundos, exceto quando fala, ação ou duração definida pelo usuário exigir outra medida. Gere referências com o provedor explicitamente escolhido — OpenRouter ou fal.ai — apresente-as e pare. Depois da aprovação, registre:

```bash
scripts/video-ai approve --project <slug> --gate references --notes "<resumo>"
```

### Aprovação 2 — roteiro

Mostre por cena: ação, duração, falas, personagem, direção de voz e som. Não mostre prompts por padrão. Pare. Depois da aprovação, registre:

```bash
scripts/video-ai approve --project <slug> --gate script --notes "<resumo>"
```

Só após essa aprovação gere vozes, Seedance, Mirelo e lip sync.

### Aprovação 3 — revisão

Monte a versão de revisão no Hyperframes, abra o preview e aguarde ajustes. Para “refaz só a cena 2”, invalide apenas a cena e seus descendentes. Depois da aprovação final, registre:

```bash
scripts/video-ai approve --project <slug> --gate review --notes "<resumo>"
```

Só então renderize com qualidade de entrega.

## Produção

- **Vozes:** mantenha um `voice_id` por personagem. `tts` recusa troca silenciosa. Meça o arquivo com `media-duration` e atualize o plano antes de vídeo.
- **Seedance:** gere cenas independentes. Referencie a bíblia visual e apenas as referências necessárias à cena. Submeta cenas independentes em paralelo até o limite informado pela conta; nunca paralelize duas tentativas da mesma ação.
- **Mirelo:** gere SFX/ambiente a partir do clipe e descrição sonora. Configure `preserve_speech: false` quando a fala aprovada da ElevenLabs será mixada; não duplique vozes.
- **Sync:** processe somente personagens visíveis falando. Use um `Idempotency-Key` persistido antes do envio. Cenas sem boca visível seguem direto à montagem.
- **Hyperframes:** use primeiro `$hyperframes`, depois os domínios que ele rotear. O script desta skill aplica os gates de aprovação; o Hyperframes continua responsável pela composição, check, preview e render.

## Comandos principais

```bash
scripts/video-ai --help
scripts/video-ai show --project <slug>
scripts/video-ai openrouter-image --project <slug> --scene <id> --payload <json> [--model <slug>]
scripts/video-ai openrouter-video-submit --project <slug> --scene <id> --payload <json> [--model <slug>]
scripts/video-ai openrouter-video-poll --project <slug> --action <id>
scripts/video-ai fal-submit --project <slug> --scene <id> --kind <seedream|seedance|mirelo> --payload <json>
scripts/video-ai fal-poll --project <slug> --action <id>
scripts/video-ai tts --project <slug> --scene <id> --character <nome> --voice-id <id> --text-file <txt>
scripts/video-ai sync-upload --project <slug> --scene <id> --role <video|audio> --file <arquivo> --type <VIDEO|AUDIO> --content-type <mime>
scripts/video-ai sync-submit --project <slug> --scene <id> --video-url <url> --audio-url <url>
scripts/video-ai sync-poll --project <slug> --action <id>
scripts/video-ai hyperframes --project <slug> --operation <check|preview|review|final>
```

Sem `--yes-paid`, os comandos de geração mostram somente o escopo e param. Use a flag quando o usuário pedir explicitamente a geração daquele lote; não exija uma segunda mensagem de confirmação.

## Recuperação e alterações

- Consulte `show` antes de agir. Reaproveite ações `completed` com o mesmo hash de entrada.
- Para fal.ai e ElevenLabs, um erro de rede depois do envio é `submission_unknown`; não reenvie automaticamente.
- Para Sync, reutilize o mesmo corpo e `Idempotency-Key` gravados.
- Para arquivos locais do Sync, use `sync-upload`; persista apenas hash, caminho e `asset_id`, nunca a URL de upload assinada.
- Use `invalidate-scene` para uma alteração pontual; ele preserva originais e marca somente etapas descendentes como obsoletas.
- Nunca apague resultados anteriores. Novas tentativas recebem um novo ID e novos caminhos.

Ao entregar, informe o caminho absoluto do arquivo final e um quadro curto de evidências: integração implementada, autenticação observada e quais provedores tiveram geração real aprovada.
