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

O instalador padrão preparado em `installer/Farry.iss` registra a desinstalação em Aplicativos do Windows. Instala somente o launcher por usuário, sem administrador, exige Windows 10 x64 compatível e .NET Framework 4.8, e impede instalação/desinstalação com o launcher aberto. A desinstalação remove os arquivos e atalhos instalados pelo assistente; preserva versões baixadas, ponteiros e os dados do QMoney. A instalação antiga por cópia não possui esse registro.

**Assinatura própria, sem serviço pago:** o manifesto RSA/SHA-256 continua protegendo as atualizações com a chave pública fixada no launcher. O novo instalador também pode receber Authenticode com a identidade interna Farry, incluindo o launcher e o desinstalador incorporado. A identidade fica no repositório pessoal de certificados do usuário Windows; a chave privada é não exportável e não entra no Git. Apenas o certificado público fica em `keys/internal-codesigning.cer`.

Assinatura própria não produz confiança pública automática: Windows/SmartScreen ainda podem avisar ou bloquear conforme a política do computador. O processo não importa certificados em Root/TrustedPublisher. A distribuição não depende de comprar certificado nem de publicar na Microsoft Store. Consulte a [distinção entre assinatura e reputação na documentação da Microsoft](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

Não desative Defender, SmartScreen ou Smart App Control para distribuir o aplicativo. A hospedagem continua sendo Hostinger/GitHub, sem exigir Microsoft Store.

### Compilar o instalador

Use Inno Setup 6.4 ou posterior. O compilador não é instalado automaticamente pelo projeto:

```powershell
./tools/sign-internal.ps1 -Initialize
./tools/build-launcher.ps1 -Version 1.0.64 -IsccPath 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' -InternalSigning
```

Saída padrão: `work/installer-candidate/`. A versão acima é do instalador; não afirma que existe um QMoney 1.0.64 testado. A compilação não instala nem publica. Não substitui os artefatos assinados de `dist/`. A assinatura interna é habilitada por padrão. `-InternalSigning:$false` permite explicitamente um candidato sem Authenticode para diagnóstico. Não troque a identidade interna automaticamente se a chave privada estiver indisponível.

O parâmetro `-InternalSigning` do empacotador assina QMoney.exe, QMoneyUpdater.exe e runtime/QMoneyService.exe na cópia de distribuição, antes da compressão e da assinatura de `release.json`. Os executáveis em uso não são modificados. Promova o instalador aprovado para `dist/FarrySetup.exe` antes de assinar o manifesto. Qualquer assinatura posterior muda os hashes.

O certificado interno tem validade de cinco anos, sem timestamp externo neste fluxo. A chave privada depende deste perfil Windows e não é recuperada pelo certificado público; preserve o ambiente de assinatura e planeje uma transição antes da expiração ou troca de máquina. A chave RSA existente do manifesto é independente e não foi regenerada.

## Publicar uma versão

A distribuição 1.0.64 mantém o aplicativo validado da release 1.0.63 e adiciona o instalador profissional e a assinatura interna. `version` identifica a distribuição; `application_version` identifica o aplicativo. O manifesto inclui a origem e o SHA-256 do pacote-base. Alterações de negócio locais ainda não validadas não são incorporadas ao pacote.

Para preparar uma atualização somente da distribuição, com origem autenticada e sem recompilar o aplicativo:

```powershell
./tools/prepare-distribution.ps1 -Version 1.0.64 -SourceVersion 1.0.63 -IsccPath 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' -ProjectRoot '<pasta-Finally>'
python tools/github_release.py --version 1.0.64 --artifact-directory dist/releases/1.0.64 --check
```

O script preserva os quatro artefatos originais de `dist/`, produz a nova distribuição em `dist/releases/<versão>/`, verifica o motor em perfis temporários e assina os executáveis antes da compressão e do manifesto. Uma falha interrompe a preparação; `-Resume` só permite retomar com o checkpoint do mesmo pacote-base. O verificador conserva seu timeout padrão de três segundos; a validação de distribuição usa 45 segundos para as verificações locais de prontidão durante a inicialização a frio, sem desabilitar verificações nem alterar o motor.

Após aprovação dos artefatos, publique com `--publish --artifact-directory dist/releases/<versão> --target-commit <commit-aprovado>`. A publicação exige uma versão inédita e crescente. A opção `--check` nunca cria nem publica uma release.

1. Faça commit do código aprovado. Mantenha o snapshot `client/` coerente com o pacote.
2. `node tools/init-signing-key.mjs` cria a chave apenas se não existir. Guarde `secrets/update-private.pem` em backup privado; nunca publique essa chave. Não regenere a chave após distribuir launchers sem planejar a migração de confiança.
3. `./tools/test-launcher.ps1` e a compilação com assinatura interna descrita acima. Valide o instalador antes de promover os artefatos para `dist/`.
4. Instale PyInstaller em `work/build-dependencies` usando o Python do projeto, e execute `./tools/package-client.ps1 -ProjectRoot <pasta-Finally-testada> -InternalSigning`. O script empacota o motor, copia o aplicativo validado e executa a verificação em perfis temporários antes de assinar. Não instala no perfil do usuário.
5. `python tools/github_release.py --version <nova-versao> --check` valida assinatura RSA, versão do manifesto, tamanhos e hashes completos. Só depois consulta o GitHub para exigir versão crescente e recusar versão existente. É uma operação de leitura e não cria releases; sem integridade válida ou sem acesso remoto, falha. A release 1.0.63 existente permanece intacta e não pode ser sobrescrita.
6. Quando a versão estiver aprovada e houver autorização para publicação: `python tools/github_release.py --version <nova-versao> --publish`. Usa a autenticação existente do Git, cria uma release em rascunho, envia quatro artefatos e só então publica. Se um upload falhar, o rascunho não será oferecido aos clientes; conclua o rascunho antes de repetir. `--publish-existing` também exige a validação local e verifica os hashes remotos antes de promover o rascunho.

Use uma versão crescente para cada pacote novo. Não altere os artefatos de uma versão já publicada.

## Validação

`npm ci --ignore-scripts`, `npm test`, `npm run build` (Node 22), `python -m unittest discover -s test -p "test_*.py"`. `./tools/test-launcher.ps1` valida assinatura e extração sem iniciar o aplicativo ou acessar contas reais. `./tools/test-internal-signing.ps1 -ArtifactDirectory ./work/installer-candidate` verifica a identidade e a assinatura pelo WinVerifyTrust, permitindo exclusivamente o erro esperado de raiz própria não confiável; um erro genérico não é aceito. Também confirma que adulteração produz HashMismatch. A CI usa chaves efêmeras somente nos testes, nunca para distribuir versões, com `FARRY_INTERNAL_CERTIFICATE` apontando para seu certificado descartável. O build de CI gera um candidato sem confiança pública; não publica.

Limite: a validação local não substitui teste de instalação completa em outro Windows, nem garante disponibilidade de dispositivos USB, credenciais ou provedores externos.
