# Criação de Vídeo IA

Skill para planejar e produzir vídeos narrativos por cenas com continuidade visual e sonora, aprovações humanas e retomada segura de jobs.

Ela integra fluxos com OpenRouter ou fal.ai para referências visuais, Seedance para vídeo, ElevenLabs para vozes, Mirelo para efeitos e ambiência, Sync Labs para lip sync e Hyperframes para montagem.

O modelo visual padrão no OpenRouter é o Nano Banana 2 (`google/gemini-3.1-flash-image`). Ele pode ser substituído em `project.json` ou por `--model` sem fallback silencioso.

## Instalação rápida

Com o instalador aberto de Agent Skills:

```bash
npx skills add Maaaneeel/criacao-de-video-ia --skill criacao-de-video-ia -g
```

Ou clone diretamente para o Codex:

```bash
git clone https://github.com/Maaaneeel/criacao-de-video-ia.git ~/.codex/skills/criacao-de-video-ia
```

Depois, abra o diretório do projeto em que deseja produzir o vídeo e execute:

```bash
~/.codex/skills/criacao-de-video-ia/scripts/video-ai prepare-env
~/.codex/skills/criacao-de-video-ia/scripts/video-ai diagnose
```

O `project.json` usa `.` como raiz por padrão. Portanto, rode os comandos a partir da pasta do seu projeto. Se preferir uma raiz fixa, substitua `.` por um caminho absoluto local.

## Credenciais

O comando `prepare-env` cria ou complementa um `.env` local com estes campos:

```dotenv
OPENROUTER_API_KEY=
ELEVENLABS_API_KEY=
FAL_KEY=
SYNC_API_KEY=
```

Nunca versionar o `.env`. O arquivo já está protegido pelo `.gitignore`.

## Uso

Em uma conversa com o agente, peça algo como:

> Use $criacao-de-video-ia para transformar minha ideia em um vídeo por cenas, com referências, vozes, lip sync e montagem.

Consulte [SKILL.md](SKILL.md) para o fluxo completo e [references/operations.md](references/operations.md) para os comandos e a recuperação de jobs.

Há um prompt inicial para cartoon infantil gospel em [examples/cartoon-infantil-gospel.md](examples/cartoon-infantil-gospel.md).

## Requisitos

- Python 3.11 ou superior
- `ffmpeg` e `ffprobe`
- Node.js e `npx` quando a montagem usar Hyperframes
- Contas e créditos nos provedores escolhidos

## Segurança e custos

- As chaves são lidas somente do `.env` do projeto.
- A skill não inclui credenciais nem resultados autenticados.
- Gerações pagas exigem um pedido explícito para o lote e registram o job antes do envio.
- Em resultados incertos, o job existente é consultado antes de qualquer nova cobrança.

## Teste local

```bash
python3 scripts/self_test.py
```

O teste não faz chamadas pagas e não precisa de credenciais reais.

## Licença

MIT. Consulte [LICENSE](LICENSE).

