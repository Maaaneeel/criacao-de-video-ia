# Operação e recuperação

## Preparação

`scripts/video-ai prepare-env` preserva linhas e valores existentes, acrescenta somente nomes ausentes e aplica permissão 0600. `diagnose` faz apenas GETs sem geração. `check-deps` verifica Python, Node, FFmpeg, ffprobe, npm/npx e executa o `doctor` do Hyperframes. A prontidão local exige Node, FFmpeg, ffprobe e Chrome; componentes opcionais e Docker não bloqueiam o render local comum.

## Estados de ação

- `prepared`: gravada antes da chamada paga.
- `submitted`: provedor devolveu request/job ID.
- `in_progress`: consulta confirmou execução.
- `completed`: resposta e download local registrados.
- `failed`: provedor devolveu falha terminal.
- `submission_unknown`: a conexão caiu depois do início do envio; não reenvie automaticamente.
- `stale`: uma alteração invalidou essa saída; o arquivo original continua preservado.

## Autorização sem confirmação duplicada

Um pedido inequívoco de geração autoriza uma tentativa do escopo descrito. Se o mesmo pedido indicar arquivos de referência, autoriza também o envio exatamente desses arquivos ao provedor escolhido ou padrão do projeto. Comunique escopo, provedor, modelo, referências e custo como informação e prossiga com `--yes-paid`; não transforme esse aviso em uma nova pergunta.

Arquivo meramente anexado, descoberto no projeto ou não indicado pelo usuário não está autorizado como referência. Não envie arquivos extras. Aprovações editoriais podem ser dadas em linguagem natural e devem ser registradas sem exigir uma fórmula específica.

O modo sem `--yes-paid` existe para orçamento/preview ou quando ainda não há pedido de geração. Se o usuário já disse “pode gerar” ou equivalente, não execute primeiro o dry-run.

## Retomada

Para fal.ai, consulte os `status_url` e `response_url` devolvidos na submissão. Para Sync, consulte `/v2/generate/{id}` e reutilize o mesmo `Idempotency-Key` somente se a submissão precisar ser reconciliada. ElevenLabs TTS é resposta direta: se o envio ficar incerto, peça decisão antes de gerar de novo.

Falha local ou validação anterior ao POST pode ser corrigida sem nova autorização. Após request/job ID, `submission_unknown` ou qualquer resultado possivelmente cobrado, consulte e reconcilie a ação existente. Polling, download e reutilização do resultado não são novas gerações e não exigem nova autorização.

Arquivos locais destinados ao Sync passam por `sync-upload`: o estado persiste somente caminho, hash e `asset_id`; nunca salve a URL assinada. Reutilize o mesmo asset em retomadas.

Para Mirelo com vídeo local, use `local_video` no payload. O comando mantém somente o caminho no estado e converte o arquivo em data URI apenas em memória no momento da submissão; arquivos acima de 8 MB exigem upload explícito em vez de base64.

OpenRouter Image API é resposta direta. Para imagem-para-imagem, use `local_references` com caminhos locais; o comando envia essas referências como data URLs somente em memória e preserva apenas os caminhos no estado. Grave a ação antes do POST, salve a imagem base64 imediatamente e registre apenas caminho, custo retornado e metadados. Uma falha de rede após o envio vira `submission_unknown`; não repita automaticamente porque a primeira imagem pode ter sido cobrada.

OpenRouter Video API é assíncrona. Grave a ação antes do POST, persista `job_id` e `polling_url`, consulte o mesmo job até um estado terminal e baixe o conteúdo autenticado imediatamente. Referências locais são codificadas em memória como data URLs; o estado guarda somente os caminhos locais, nunca o base64.

## Paralelismo

Submeta cenas independentes em paralelo apenas depois de conhecer o limite da conta. Use um processo por ação ou um pequeno lote; o estado usa bloqueio e escrita atômica. Nunca execute duas submissões para o mesmo action ID.

## Hyperframes

O comando `hyperframes` é um gate e wrapper, não um autor de composição. A composição deve ser criada pelas skills Hyperframes em `<project>/hyperframes`. `review` exige Aprovação 2; `final` exige Aprovação 3. O wrapper executa `npx hyperframes check`, `preview --background` ou `render`, e valida o arquivo final com `ffprobe`.
