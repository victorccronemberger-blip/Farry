# Celular, ADB, JWT e App Check

Mapa da cópia ativa `Finally`, atualizado em 14/10/2026. A mudança é estrutural: preserva APIs, escolhas de provedor, renovação, prazos, cache, locks, campos HTTP e comportamento do painel. Não representa teste de aceitação do Minute nem alteração de suas regras de autorização.

## Onde começar

| Quero trabalhar em… | Arquivo responsável |
| --- | --- |
| Estrutura/validade local do JWT de App Check | `moneymin/mobile/appcheck/jwt.py` |
| Coordenação de emissão, cache, renovação e diagnóstico App Check | `moneymin/mobile/appcheck/runtime.py` |
| Variáveis de ambiente, identidade da configuração e caminhos | `moneymin/mobile/configuration.py` |
| Falhas, mensagens seguras e identificação de rejeição | `moneymin/mobile/appcheck/errors.py` |
| Cooldown persistido e lock entre processos | `moneymin/mobile/appcheck/persistence.py` |
| Troca Firebase do provedor debug autorizado | `moneymin/mobile/appcheck/exchange.py` |
| Localizar o executável ADB para diagnóstico público | `moneymin/mobile/android/discovery.py` |
| Inventário USB e informações públicas do aparelho | `moneymin/mobile/android/diagnostics.py` |
| Limite de integração com o provedor device existente | `moneymin/mobile/android/provider.py` |
| Binding CREATE/sidecar/headers à identidade física dinâmica | `moneymin/mobile/physical_binding.py` |
| Implementação legada do provedor device | `moneymin/roglife_appcheck/` — mapa abaixo |
| Respostas HTTP do setor móvel | `moneymin/web/routes/mobile.py` |
| Painel do celular na campanha | `desktop/src/AndroidDevicePanel.cpp` e `.hpp` |
| Notificações de conexão/desconexão USB | `desktop/src/UsbDeviceWatcher.cpp` e `.hpp` |
| Exibição/rechecagem App Check em Integrações | `desktop/src/MainWindowMobile.cpp` |
| Contrato público Python existente | `moneymin/appcheck.py`, `moneymin/integrations/android_diagnostics.py` |

## Organização e dependências

```text
Consumidores: campanhas / entrega / prontidão / cliente Minute
    -> moneymin.appcheck (fachada pública + estado histórico único)
        -> mobile.appcheck.runtime.AppCheckRuntime
            -> portas explícitas e substituíveis
            -> configuration / jwt / errors / persistence / exchange
            -> mobile.android.provider -> roglife_appcheck (legado)

HTTP: routes.integrations (handlers compatíveis)
    -> routes.mobile (request/jsonify injetados)
        -> fachada appcheck ou fachada android_diagnostics
            -> mobile.android.discovery / diagnostics

Qt: AndroidDevicePanel -> API local móvel
    UsbDeviceWatcher -> notificações USB para o painel
    MainWindowMobile -> exibição/rechecagem na página Integrações
```

Os módulos de domínio em `moneymin/mobile/` não importam a fachada `moneymin.appcheck` nem a composição `web/server.py`. O runtime recebe `AppCheckState` e `AppCheckPorts`, definidos em `mobile/appcheck/contracts.py`. As portas são operações declaradas, e não um dicionário de globals ou cópia de módulo.

### Por que a fachada ainda contém estado

`moneymin/appcheck.py` conserva `_lock`, `_identity`, `_token`, `_expires`, `_retry_at`, `_last_failure` e `_last_diagnostic`. São os mesmos nomes observados por consumidores/testes existentes. `_LegacyState` acessa esses campos por propriedades explícitas; não cria outro cache, não sincroniza cópias e não cria outro lock. `_runtime` é a única instância composta pela fachada.

`_LegacyPorts` consulta os símbolos atuais da fachada a cada operação. Assim, substituir `_exchange`, `_load_persisted_state`, `app_check_status`, `mint_app_check_token`, relógios ou transporte depois do import continua funcionando. Essa compatibilidade é intencional; não coloque novas regras de negócio na fachada.

O runtime conserva a ordem dos locks e dos efeitos. As chamadas ao provedor device permanecem fora do lock de estado; o caminho debug mantém serialização em processo e por arquivo. Alterar esses limites requer testes de concorrência e de cooldown.

## Responsabilidade de cada arquivo novo

| Arquivo | Responsabilidade e limite |
| --- | --- |
| `moneymin/mobile/__init__.py` | Marca o pacote; não inicia dispositivo, threads ou emissão. |
| `moneymin/mobile/configuration.py` | Lê configurações recebidas da fachada, calcula identidades e resolve nomes de arquivos. Não salva credenciais. |
| `moneymin/mobile/appcheck/__init__.py` | Marca o subpacote de App Check, sem estado ou efeitos. |
| `moneymin/mobile/appcheck/contracts.py` | Protocolos de estado e operações usados pelo runtime. Não implementa autenticação. |
| `moneymin/mobile/appcheck/runtime.py` | Implementa `clear_cache`, configuração observada, diagnósticos, snapshot, `mint_app_check_token`, header, `ensure_app_check_fresh` e `renew_app_check_for_batch`. Não implementa comandos de captura. |
| `moneymin/mobile/appcheck/jwt.py` | Examina formato e `exp` de um JWT compacto com relógio injetado. Não verifica assinatura, emissor nem aceitação pelo servidor. |
| `moneymin/mobile/appcheck/errors.py` | Categorias estáveis, whitelist de diagnósticos, `AppCheckExchangeError` e reconhecimento explícito de rejeição App Check. Não devolve corpo remoto. |
| `moneymin/mobile/appcheck/persistence.py` | Valida/salva metadados sanitizados de falha/cooldown e mantém o lock de troca entre processos. Não persiste JWT. |
| `moneymin/mobile/appcheck/exchange.py` | Provedor Firebase debug já existente; recebe transporte e classificador de erro. Preserva timeout e validações anteriores. |
| `moneymin/mobile/android/__init__.py` | Marca o subpacote Android, sem iniciar ADB. |
| `moneymin/mobile/android/discovery.py` | Busca ADB nas localizações públicas/configuradas existentes, com dependências explícitas. Não consulta configurações privadas do aplicativo. |
| `moneymin/mobile/android/diagnostics.py` | Snapshot público com prazo compartilhado de oito segundos, validação de serial, inventário, propriedades e classificação segura de falhas. Não eleva privilégios ou lê dados de aplicativos. |
| `moneymin/mobile/android/provider.py` | Importação tardia do provedor device legado. Não copia, reescreve ou inicializa sua implementação. |
| `moneymin/web/routes/mobile.py` | Corpos dos três handlers móveis. Usa somente `request`/`jsonify` do adaptador injetado; imports de fachadas permanecem tardios. |
| `desktop/src/MainWindowMobile.cpp` | Os dois métodos Qt existentes `renderAppCheckSnapshot` e `recheckAppCheck`, movidos sem alterar seus corpos. |

As fachadas `moneymin/appcheck.py`, `moneymin/integrations/android_diagnostics.py` e os três handlers originais de `web/routes/integrations.py` delegam aos módulos acima. Os consumidores não precisam trocar imports.

## Provedor device legado: localização preservada

O pacote abaixo pertence ao setor móvel, mas não foi movido nem teve seu algoritmo alterado. Ele usa caminhos relativos à instalação e pontos de substituição próprios; movê-lo apenas para reorganizar pastas quebraria esses contratos.

| Arquivo | O que contém |
| --- | --- |
| `moneymin/roglife_appcheck/__init__.py` | Exportações públicas do provedor. |
| `moneymin/roglife_appcheck/provider.py` | Seleção de modo device, sessão/cache do provedor, estado observado e metadados de identidade. |
| `moneymin/roglife_appcheck/config.py` | Configuração e caminhos relativos usados pelo provedor. |
| `moneymin/roglife_appcheck/adb.py` | Transporte ADB e seleção do dispositivo no provedor legado. É distinto do diagnóstico público. |
| `moneymin/roglife_appcheck/device_info.py` | Coleta dos metadados do dispositivo usados pelo provedor. |
| `moneymin/roglife_appcheck/capture.py` | Implementação legada de obtenção/renovação device; permanece opaca nesta refatoração. |
| `moneymin/roglife_appcheck/MODULE.md` | Documentação específica preexistente do pacote. |

Não una o diagnóstico público a esse transporte privado: finalidade, permissões e dados expostos são diferentes.

## JWT de conta e JWT de App Check são contratos diferentes

O JWT App Check alimenta `X-Firebase-AppCheck` através de `appcheck.get_app_check_header()`. O parser local está em `mobile/appcheck/jwt.py`.

O JWT de login da conta alimenta `Authorization: Bearer …`. Seu ciclo de login/refresh e persistência de conta continua em `moneymin/minute_api.py`, especialmente `_jwt_exp`, `_refresh`, `Session.id_token`, `Session.refresh`, `Session.request` e `Session.request_detailed`. Esse cliente é compartilhado com contas e carteira; não foi reorganizado nesta tarefa. Renovar um desses JWTs não equivale a renovar o outro.

`minute_api.require_app_check_for_write` e `_align_physical_device_headers` são interfaces consumidoras do setor móvel. Campanhas/entrega mantêm seus próprios pontos de pré-checagem e gates (`campaigns/account_delivery.py`, `campaigns/execution.py`, `delivery/admission.py`). Esses arquivos não são propriedade integral do setor móvel; não mova suas regras de envio para o runtime de autenticação.

Metadados físicos, versão e uptime exportados pelo provedor ficam em `roglife_appcheck/provider.py` (`physical_identity`, `physical_device_id`, `physical_app_version`, `physical_uptime_ns` e `physical_*_meta`). Em modo device, `moneymin/mobile/physical_binding.py` aplica a assinatura do celular conectado: para SM-S901E usa a calibração nativa portada em `resources/physical_capture_calib.json` (único envio real conhecido, `camera2`); outros modelos usam catálogo + jitter estável no SSAID. Já `moneymin/device_profile.py` continua como perfil sintético por conta fora do modo device; `moneymin/sidecar.py` só escreve o envelope.

## HTTP e UI: contratos preservados

| Método e caminho | Handler compatível | Implementação |
| --- | --- | --- |
| GET `/api/integrations/android/device` | `integrations.get_android_device` | `mobile.get_android_device` |
| GET `/api/integrations/appcheck/status` | `integrations.get_appcheck_status` | `mobile.get_appcheck_status` |
| POST `/api/integrations/appcheck/recheck` | `integrations.recheck_appcheck_integration` | `mobile.recheck_appcheck_integration` |

O registry conserva nomes, caminhos, ordem e a feature `integrations`. Os wrappers mantêm o contrato de `DependencyBindings`; não há import de `server.py` nas rotas. GET de status continua somente leitura; POST de rechecagem mantém as condições anteriores e não recebe credenciais.

`AndroidDevicePanel` é dono dos timers, seleção, gerações de callbacks e inscrição USB. `UsbDeviceWatcher` entrega notificações Windows e não controla HTTP ou autenticação. `MainWindowCampaigns.cpp` cria o painel e encaminha lifecycle pelos métodos existentes. `MainWindowIntegrations.cpp` ainda constrói o cartão e carrega o snapshot geral; delega sua exibição/rechecagem aos métodos em `MainWindowMobile.cpp`.

Em `MainWindow.hpp`, apenas as declarações de `renderAppCheckSnapshot`/`recheckAppCheck`, campos `_appCheck*` e `_campaignDevicePanel` participam dessa interface. Em `desktop/CMakeLists.txt`, a adaptação desta tarefa é uma entrada de `MainWindowMobile.cpp` na lista comum ao aplicativo e aos testes. Não trate esses dois arquivos compartilhados como exclusivos do setor móvel.

## Estado, arquivos e segurança da manutenção

Os nomes persistidos permanecem iguais: `appcheck_mint_state.json` contém falhas/cooldown sanitizados; `appcheck_exchange.lock` coordena trocas; `appcheck_pause.flag` representa a pausa local. Os caminhos vêm de `config.DATA_DIR` no momento da chamada. Sessão/cache do provedor legado continuam sob responsabilidade dele. Nenhum dado do usuário foi migrado ou apagado por esta tarefa.

Não acrescente JWTs, senhas, corpos HTTP privados ou dumps de ambiente a logs, fixtures, Git ou documentação. Um snapshot local válido não prova autorização de upload; a decisão remota e os recibos permanecem nos consumidores existentes.

## Limite de edição para agentes

Este setor é mantido separadamente pelo usuário, conforme `AGENTS.md`. Pedidos em campanhas, catálogos, contas, entrega ou integrações gerais permitem consumir as interfaces existentes, mas não modificar o funcionamento móvel. Alterações internas exigem escopo explícito que inclua celular/App Check/ADB. As instruções não impedem uma alteração móvel que o usuário já autorizou.

Para manutenção nova, escolha o módulo responsável na primeira tabela. Preserve fachadas, assinaturas, estado único, pontos de substituição tardia, formatos persistidos, locks e callbacks. Não distribua regras de autenticação por campanhas ou pela composição HTTP.

## Validação

Os testes móveis usam fixtures e substituições do limite externo. `scripts/run_tests.py` mantém perfis temporários e bloqueio de rede; agora também bloqueia processos ADB reais via evento auditável `subprocess.Popen`. O bloqueio é exclusivo do runner, não altera o aplicativo e falha imediatamente mesmo em código que captura `Exception`. Não é uma barreira do sistema operacional; mecanismos externos ao subprocesso Python não são abrangidos.

Comandos a partir da raiz:

```powershell
.\.venv\Scripts\python.exe scripts\run_tests.py --pytest -q test/test_mobile_modularization.py test/test_appcheck.py test/test_appcheck_permission_diagnostics.py test/test_appcheck_device_cache.py test/test_appcheck_integration_api.py test/test_android_device_diagnostics.py test/test_android_device_api.py test/test_modular_architecture.py test/test_offline_device_guard.py
.\scripts\build_local.ps1 -BuildOnly -SkipTests -ToolchainRoot C:\Users\victo\OneDrive\Desktop\QFar
.\.venv\Scripts\python.exe scripts\run_tests.py
```

Execute também os testes Qt móveis pelo CTest em `build-modular2`, com o mesmo ambiente Qt/MinGW do build. `-BuildOnly` não instala nem substitui a aplicação aberta. Não execute o aplicativo, campanhas ou comandos no celular como substituto desses testes.

`test/test_mobile_modularization.py` cobre estado único, hooks substituídos após import, limite device fora do lock, caminhos atuais, relógio do JWT, contratos públicos e imports de domínio. `test/test_offline_device_guard.py` cobre a proteção contra ADB real com caminhos sentinela. Os testes anteriores de App Check/Android/HTTP continuam usando os imports antigos.

Resultados e limitações desta execução ficam em [CELULAR_VALIDACAO.md](CELULAR_VALIDACAO.md).
