---
name: criacao-de-video-ia
description: Planeja e produz vídeos narrativos por cenas usando OpenRouter ou fal.ai para referências visuais, modelos de vídeo, ElevenLabs, Mirelo, Sync Labs e opcionalmente Hyperframes, com persistência de jobs, retomada segura e gates editoriais. Pedidos explícitos de geração autorizam a tentativa solicitada e as referências indicadas, sem confirmação redundante. Não use para uma edição simples de vídeo já existente.
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
- Linguagem natural inequívoca conta como autorização. Pedidos como “gere”, “crie”, “produza”, “pode gerar”, “pode seguir”, “faça agora” ou equivalentes autorizam uma tentativa do lote e escopo descritos. Não exija a palavra “autorizo” nem uma segunda mensagem.
- Quando o usuário indicar um arquivo local específico como referência e pedir a geração, isso também autoriza enviar exatamente esse arquivo ao provedor escolhido na mesma mensagem ou ao provedor padrão do projeto. Informe de forma declarativa arquivo, provedor, modelo e custo estimado quando disponível; não termine essa comunicação em pergunta.
- Essa autorização não cobre arquivos apenas anexados ou encontrados no projeto que o usuário não indicou, arquivos extras, outras cenas ou finalidades diferentes. Também não cobre uma troca de provedor/modelo proposta pelo agente, ampliação do lote nem nova tentativa potencialmente cobrada após resultado incerto. Se a própria mensagem do usuário pedir a troca e a geração, o novo escopo está autorizado.
- Se o pedido ativo já autoriza a geração, execute o comando pago diretamente com `--yes-paid`; não rode primeiro o modo de prévia e não peça confirmação redundante. O modo sem `--yes-paid` serve somente quando o usuário pediu orçamento/preview ou ainda não pediu a geração.
- Polling, download, consulta de status, reconciliação de job e reaproveitamento de resultado existente não são novas gerações e não exigem autorização adicional.
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

Os gates abaixo são marcos editoriais, não permissões repetidas para cada chamada. Aprovação em linguagem natural conta: “ficou bom”, “pode seguir”, “pode gerar” e equivalentes bastam quando o contexto deixa claro o material aprovado. Registre o gate e prossiga na mesma resposta quando o usuário também pedir a próxima etapa.

### Aprovação 1 — referências

Organize a história e uma bíblia visual. Use cenas em torno de 5 segundos, exceto quando fala, ação ou duração definida pelo usuário exigir outra medida. Gere referências com o provedor explicitamente escolhido — OpenRouter ou fal.ai — e apresente-as antes de usá-las em etapas posteriores. Uma referência que o usuário forneceu e designou para a cena já está aprovada como entrada dessa geração; referências novas geradas pelo fluxo ainda precisam de revisão. Depois da aprovação, registre:

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
scripts/video-ai update-scene --project <slug> --file <scene-patch.json> --change-type <visual|dialogue|sfx|all> --reason "<motivo>"
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

Sem `--yes-paid`, os comandos de geração mostram somente o escopo e param. Use esse modo apenas para orçamento/preview. Quando o usuário já pediu a geração daquele lote, use a flag na primeira execução e não exija uma segunda mensagem de confirmação.

## Recuperação e alterações

- Consulte `show` antes de agir. Reaproveite ações `completed` com o mesmo hash de entrada.
- Para fal.ai e ElevenLabs, um erro de rede depois do envio é `submission_unknown`; não reenvie automaticamente.
- Para Sync, reutilize o mesmo corpo e `Idempotency-Key` gravados.
- Para arquivos locais do Sync, use `sync-upload`; persista apenas hash, caminho e `asset_id`, nunca a URL de upload assinada.
- Use `invalidate-scene` para uma alteração pontual; ele preserva originais e marca somente etapas descendentes como obsoletas.
- Para alterar o conteúdo de uma cena já planejada, use `update-scene` com um patch parcial e o tipo da mudança. Ele preserva os campos não informados e os gates `references` e `script`, invalida somente os derivados afetados e reabre apenas o gate `review`.
- Corrija e repita sem nova autorização somente quando houver evidência de que nenhuma solicitação chegou ao provedor e nenhuma cobrança ocorreu. Após request/job ID, `submission_unknown` ou resultado possivelmente cobrado, reconcilie a ação existente e peça nova autorização apenas antes de criar outra tentativa paga.
- Nunca apague resultados anteriores. Novas tentativas recebem um novo ID e novos caminhos.

Ao entregar, informe o caminho absoluto do arquivo final e um quadro curto de evidências: integração implementada, autenticação observada e quais provedores tiveram geração real aprovada.
