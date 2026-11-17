# Fluxo de produção

## 1. História e cenas

Transforme a entrada em uma história objetiva. Uma cena representa uma unidade filmável e resulta em um arquivo separado. Use cerca de 5 segundos como ponto de partida, mas deixe fala e ação definirem a duração real. Duração expressa pelo usuário prevalece.

Antes de gerar qualquer mídia, registre para cada cena: intenção, ação visível, personagem, fala, direção vocal, sons, duração, continuidade de entrada/saída e referências necessárias.

## 2. Bíblia visual e referências

Defina personagens (traços estáveis, roupa, acessórios), cenários, paleta, luz, lente/câmera e estilo. Gere folhas de referência com o provedor escolhido pelo usuário. OpenRouter usa sua Image API dedicada; fal.ai usa a fila do modelo configurado. As imagens são exploratórias até a Aprovação 1. Depois dela, marque os arquivos aprovados no plano; não use rascunhos rejeitados como referência e nunca faça fallback silencioso entre provedores.

## 3. Roteiro final

Apresente apenas conteúdo editorial: cena, ação, duração, fala, personagem, direção de voz e som. Mantenha os prompts de modelo em arquivos internos do projeto. Aguarde a Aprovação 2.

## 4. Vozes

Associe cada personagem a um `voice_id` persistente. Gere cada fala separadamente quando isso facilitar sincronização e refação. Meça duração real com `ffprobe`; ajuste a cena antes do vídeo. Não estique ou corte fala sem aprovação quando isso mudar interpretação.

## 5. Vídeo por cena

Use Seedance em uma solicitação por cena. Inclua a bíblia visual relevante e referências aprovadas. Defina movimento e câmera; não redescreva inutilmente o que a referência já fixa. Registre modelo, versão, request ID, payload hash e resultado.

## 6. Som por cena

Gere SFX/ambiente com Mirelo a partir do clipe. Evite fala, narração e expressões vocais já produzidas pela ElevenLabs. Verifique duração e complemente silêncio/ambiente se o áudio não cobrir a cena.

## 7. Lip sync seletivo

Use Sync somente quando houver personagem visível falando. O áudio deve ser a fala aprovada do personagem. Não aplique lip sync em narração off-screen, boca fora de quadro ou cenas sem fala.

## 8. Montagem de revisão

Roteie a montagem pelo `$hyperframes`. Use clipe sincronizado quando houver lip sync e o clipe Seedance original nas demais cenas. Coloque vozes e SFX uma vez só. Rode `check`, abra o preview e aguarde a Aprovação 3.

## 9. Final

Renderize com qualidade `delivery`, confirme arquivo não vazio e valide duração/streams com `ffprobe`. Entregue o caminho absoluto e a matriz de evidências das integrações.

## Refação localizada

Uma mudança visual invalida Seedance, Mirelo, Sync e montagem daquela cena. Uma mudança de fala invalida ElevenLabs, duração, Seedance quando a ação/timing mudar, Sync e montagem. Uma mudança apenas de SFX invalida Mirelo e montagem. Nunca invalide cenas independentes sem dependência real.
