# Wan — referência operacional

Leia este arquivo antes de uma geração paga com Wan e confirme a documentação oficial do endpoint escolhido.

## Seleção

- Preferência do Gospelzim: `alibaba/wan-3.0/reference-to-video` via fal.ai quando disponível no projeto.
- Alternativas Wan só podem ser usadas se forem registradas explicitamente no plano e no estado, por exemplo uma variante `wan/v2.6` ou `wan/v2.7`.
- Não trate o nome “Wan” como uma autorização para trocar de versão depois que um job foi submetido.

## Continuidade

As fichas de personagem são imagens estáticas. Wan 3 aceita referências de imagem no endpoint reference-to-video; a documentação atual também descreve referências de vídeo, áudio, duração, proporção e resolução. Use apenas os campos aceitos pelo schema vigente e associe cada imagem à personagem por posição/nome no prompt.

## Prompt de movimento

Escreva internamente prompts que combinem: personagem nomeado + ação física simples + emoção + cenário infantil cristão + câmera + luz + continuidade. Prefira um movimento principal por clipe: cantar olhando para a câmera, levantar as mãos em oração, caminhar até um amigo, abraçar, dançar em roda ou apontar para um elemento do cenário. Evite ações incompatíveis com a pose da ficha, mãos em excesso, troca de roupa, texto legível em objetos e cortes internos.

## Áudio

Se a cena receber ElevenLabs/Mirelo depois, use `audio: false` ou o equivalente aceito pela variante. Se áudio nativo for aprovado, registre que fala, trilha e SFX vieram do Wan e não os duplique na montagem.

## Fontes

- Canal: https://www.youtube.com/@gospelzimoficial
- Wan 3 reference-to-video: https://fal.ai/models/alibaba/wan-3.0/reference-to-video/api
- Catálogo Wan: https://fal.ai/wan-3
