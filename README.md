# PALMACOR Backend MVP — Flask + Supabase

For the current 23e growth super admin login and trusted activation steps, see
[SUPER_ADMIN_SETUP.md](SUPER_ADMIN_SETUP.md). The legacy setup notes below describe
the initial MVP; the current application also requires
`migration_001_gestao23e.sql`, `migration_002_messaging_foundation.sql`, and
`migration_003_database_security_hardening.sql`.

Primeira base segura para transformar o prototipo estatico do PALMACOR em um
CRM multiempresa. O frontend deixa de executar CRUD diretamente no Supabase:
ele autentica o usuario e chama esta API com o access token.

## O que ja esta implementado

- Flask com application factory e blueprints.
- Verificacao do access token no Supabase Auth.
- Autorizacao por empresa (`organization_id`) em toda rota de dados.
- Papeis `owner`, `admin` e `member`.
- CRUD inicial de leads, com `DELETE` convertido em arquivamento recuperavel.
- Etapas permitidas por allowlist e historico automatico de mudancas.
- Validacao de corpo, campos desconhecidos, datas, e-mail e valores.
- CORS limitado a origens configuradas, limite de payload e headers defensivos.
- Respostas de erro sem detalhes internos do banco.
- Testes de autenticacao, permissao, validacao e metodos HTTP.

## Regra de seguranca central

O frontend nao decide se uma acao e permitida. Mesmo que alguem altere o HTML,
habilite um botao pelo DevTools ou escreva a chamada manualmente, o backend exige:

1. token de sessao valido;
2. participacao ativa na empresa solicitada;
3. papel suficiente para a acao;
4. identificadores da empresa aplicados pelo servidor, nunca confiados ao JSON.

`SUPABASE_SERVICE_ROLE_KEY` existe apenas no ambiente do backend. Nunca deve ser
enviada ao navegador, gravada no repositorio ou configurada no deploy do frontend.

## Rotas do primeiro corte

| Metodo | Rota | Permissao |
|---|---|---|
| `GET` | `/health` | Publica |
| `GET` | `/api/v1/me` | Usuario autenticado |
| `GET` | `/api/v1/organizations` | Usuario autenticado |
| `GET` | `/api/v1/organizations/:org/leads` | Membro da empresa |
| `POST` | `/api/v1/organizations/:org/leads` | Membro da empresa |
| `GET` | `/api/v1/organizations/:org/leads/:id` | Membro da empresa |
| `PATCH` | `/api/v1/organizations/:org/leads/:id` | Membro da empresa |
| `POST` | `/api/v1/organizations/:org/leads/:id/stage` | Membro da empresa |
| `DELETE` | `/api/v1/organizations/:org/leads/:id` | Owner ou admin |

Outros metodos recebem `405 Method Not Allowed` automaticamente. Isso organiza a
API, mas a protecao real e a autenticacao e autorizacao executada dentro das rotas.

## Preparacao do Supabase

Use um projeto novo para o MVP. No SQL Editor, execute [`sql/schema.sql`](sql/schema.sql).
Depois:

1. crie o primeiro usuario em **Authentication > Users**;
2. copie o UUID desse usuario;
3. execute as duas instrucoes comentadas no fim do schema para criar a empresa e
   registrar o usuario como `owner`;
4. copie `.env.example` para `.env` e preencha as tres variaveis do Supabase.

O schema revoga acesso das tabelas para `anon` e `authenticated`. Apenas o backend,
com `service_role`, acessa os dados. O login continua sendo feito pelo Supabase Auth.

## Executar localmente

Requer Python 3.10 ou superior.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
flask --app wsgi run --port 5000
```

Teste publico:

```bash
curl http://127.0.0.1:5000/health
```

## Integracao Twilio e n8n

Depois de aplicar **sql/migration_002_messaging_foundation.sql** e
**sql/migration_003_database_security_hardening.sql**, importe
**n8n/workflows/23e-inbound-sms-intake.json**. As instrucoes de credenciais,
variaveis e publicacao estao em **n8n/README.md**.

Teste autenticado, usando o access token retornado no login do Supabase:

```bash
curl http://127.0.0.1:5000/api/v1/organizations \
  -H "Authorization: Bearer SEU_ACCESS_TOKEN"
```

## Testes

```bash
pytest -q
```

Os testes nao precisam de uma conta Supabase: autenticacao e repositorio sao
substituidos por doubles controlados.

## Como ligar ao PALMACOR atual

Nao altere o frontend inteiro de uma vez. A migracao segura e:

1. adicionar uma tela de login com Supabase Auth;
2. criar um modulo `api.js` que envie `Authorization: Bearer <access_token>`;
3. trocar primeiro apenas a listagem de leads;
4. trocar cadastro, edicao, movimento do Kanban e arquivamento;
5. remover o CRUD direto pelo SDK Supabase e apagar a configuracao por `localStorage`;
6. desativar a antiga policy publica `Acesso Total Publico para Anon`.

O JSON do atendente WhatsApp ainda nao deve ser conectado ao banco. Primeiro ele
deve chamar um webhook autenticado do backend, com assinatura e idempotencia. Esse
sera um segundo corte depois que o CRUD autenticado estiver integrado ao frontend.

## Antes de producao

- hospedar com Gunicorn ou plataforma WSGI, nunca com o servidor de desenvolvimento;
- manter frontend e API em HTTPS;
- usar origens CORS exatas;
- adicionar rate limiting compartilhado (por exemplo, Redis) nos endpoints publicos;
- criar testes de isolamento entre duas empresas reais no Supabase;
- configurar logs e alertas sem registrar tokens ou dados sensiveis;
- definir backup, retencao e politica de privacidade;
- adicionar webhook WhatsApp assinado, deduplicacao e fila de processamento;
- rotacionar qualquer chave que tenha sido exposta em repositorio ou navegador.

