# Farry

Servidor de versões e distribuição Windows do QMoney. Substitui integralmente o modelo Callout.

## Estrutura

- `server.js`, `public/`: servidor Express e página de atualizações.
- `launcher/`: launcher e instalador Windows (.NET Framework 4.8, x64).
- `keys/update-public.pem`: chave pública para verificar publicações.
- `client/`: snapshot do projeto Finally em uso; contas, tokens, mídias, builds e ambientes locais ficam fora do Git.
- `tools/`: compilação, empacotamento, assinatura e publicação.

O criador de contas foi preservado conforme a decisão do proprietário. O aplicativo instalado continua funcionando independentemente deste servidor.

## Hostinger

Configuração: Express, Node 22.x, npm, branch `main`, raiz `./`, entrada `server.js`. Comando de início: `npm start`. Não requer compilação de frontend; `npm run build` valida a sintaxe.

Defina `GITHUB_TOKEN` nas variáveis de ambiente da Hostinger usando um token limitado ao repositório Farry, com `Contents: Read`. `GITHUB_REPOSITORY` é opcional e assume `victorccronemberger-blip/Farry`. O token nunca é enviado ao launcher. `PORT` é fornecida pela hospedagem.

`GET /health` mostra se o servidor está ativo e se há credencial configurada. `GET /api/releases/latest` entrega o manifesto assinado da última release estável completa. Sem release, retorna 404; sem configuração, retorna 503. A página mostra esse estado honestamente.

Os downloads são públicos para os usuários do aplicativo; somente os quatro artefatos de uma release publicada e verificada podem ser acessados. O código do repositório e suas credenciais permanecem privados. Não coloque dados pessoais ou segredos nos artefatos.

## Instalação e atualização

Execute `FarrySetup.exe`. Ele instala `FarryLauncher.exe` em `%LOCALAPPDATA%\Farry`, cria atalhos no desktop e menu Iniciar e abre o launcher. O download da primeira versão é explícito. Não requer administrador.

O launcher consulta atualizações ao abrir. Instalações ficam em `versions/<versão>`. Cada pacote tem SHA-256 e manifesto assinado RSA/SHA-256 com chave pública fixada no launcher. ZIPs com caminhos externos, links ou nomes duplicados são recusados. A versão instalada não é substituída durante o download.

A nova versão precisa confirmar prontidão do motor antes de atualizar atomicamente `current.txt`. A versão anterior e `previous.txt` permanecem disponíveis. Se o servidor estiver indisponível, `Abrir QMoney` continua funcionando para uma instalação existente. Nunca altera `%LOCALAPPDATA%\QMoney`, suas contas ou sua biblioteca.

Para remover apenas o launcher, feche-o e remova os atalhos e `%LOCALAPPDATA%\Farry`. Isso não remove os dados do QMoney. Os executáveis ainda não têm certificado Authenticode comercial; assinatura das atualizações e reputação do Windows são verificações diferentes.

## Publicar uma versão

1. Faça commit do código aprovado. Mantenha o snapshot `client/` coerente com o pacote.
2. `node tools/init-signing-key.mjs` cria a chave apenas se não existir. Guarde `secrets/update-private.pem` em backup privado; nunca publique essa chave. Não regenere a chave após distribuir launchers sem planejar a migração de confiança.
3. `./tools/test-launcher.ps1` e `./tools/build-launcher.ps1`.
4. Instale PyInstaller em `work/build-dependencies` usando o Python do projeto, e execute `./tools/package-client.ps1 -ProjectRoot <pasta-Finally-testada>`. O script empacota o motor, copia o aplicativo validado e executa a verificação em perfis temporários antes de assinar. Não instala no perfil do usuário.
5. `python tools/github_release.py --version 1.0.63 --publish`. Usa a autenticação existente do Git, cria uma release em rascunho, envia quatro artefatos e só então publica. Se um upload falhar, o rascunho não será oferecido aos clientes; remova ou conclua esse rascunho antes de repetir.

Use uma versão crescente para cada pacote novo. Não altere os artefatos de uma versão já publicada.

## Validação

`npm ci --ignore-scripts`, `npm test`, `npm run build` (Node 22). `./tools/test-launcher.ps1` valida assinatura e extração sem iniciar o aplicativo ou acessar contas reais. A CI usa uma chave efêmera somente nos testes, nunca para distribuir versões.

Limite: a validação local não substitui teste de instalação completa em outro Windows, nem garante disponibilidade de dispositivos USB, credenciais ou provedores externos.
