# Auditoria inicial do prototipo PALMACOR

Esta revisao considera os arquivos recebidos do PALMACOR e do fluxo n8n. Ela nao
e um teste de invasao do site de terceiros citado na conversa.

## A observacao pelo DevTools

Alterar texto, HTML, CSS ou JavaScript pelo F12 modifica a copia carregada no
navegador do proprio visitante. Isso e comportamento normal da web e nao prova,
isoladamente, acesso ao servidor ou aos dados de outros usuarios.

A vulnerabilidade existe quando uma alteracao local permite executar uma operacao
que o servidor deveria negar: consultar dados de outra empresa, criar ou apagar
registros sem sessao, mudar permissao, obter segredos ou adulterar valores aceitos.
Por isso, a interface nunca e uma fronteira de seguranca.

## Achados nos arquivos atuais

### Critico — acesso publico total no Supabase

O schema antigo cria uma policy `FOR ALL` para `anon` e `authenticated`, com
`USING (true)` e `WITH CHECK (true)`. Qualquer pessoa com a URL e a chave publica
do projeto pode ler, criar, modificar e apagar leads pela Data API.

A chave anon ser visivel no navegador e normal; a policy publica e que torna essa
visibilidade perigosa. O novo schema revoga acesso direto e desloca o CRUD para o
backend autenticado.

### Alto — servidor estatico pode expor arquivos do projeto

O `server.js` antigo transforma a URL solicitada em caminho de arquivo sem limitar
o resultado a uma pasta publica dedicada. Se um `.env` real estiver no mesmo
diretorio, ele pode ser servido; caminhos com `..` tambem nao sao rejeitados.

Esse servidor deve ser aposentado. Em producao, o frontend deve conter apenas
arquivos publicos, e a API Flask deve rodar como servico separado.

### Alto — ausencia de autenticacao e isolamento por empresa

O frontend atual acessa a tabela diretamente e nao associa cada registro a uma
empresa. Nao existe garantia de quem executou a acao nem separacao segura entre
clientes. O novo modelo inclui `organization_id`, membros e papeis.

### Medio — configuracao persistida no navegador

URL e chave anon podem ser salvas no `localStorage`. Embora uma chave publica nao
seja segredo, essa tela facilita apontar a aplicacao para projetos arbitrarios e
confunde configuracao de infraestrutura com preferencia do usuario. Ela deve ser
removida durante a migracao.

### Medio — exclusao definitiva e falta de trilha

O prototipo permite CRUD sem historico confiavel. O backend inicial usa exclusao
logica e registra mudancas de etapa por trigger, incluindo o usuario responsavel.

### Medio — fluxo WhatsApp ainda e material de aula

O JSON n8n esta inativo e contem nos incompletos, expressoes de exemplo e
referencias a credenciais/instancia, sem apresentar as chaves em texto puro. Antes
de uso real, o webhook precisa de assinatura, deduplicacao, limites, validacao de
payload e uma identidade de integracao restrita.

## Credenciais encontradas

Os exemplos de ambiente recebidos nao possuem valores secretos preenchidos. O
workflow contem identificadores de configuracao, mas nao uma chave de API legivel.
Mesmo assim, ao publicar o projeto, mantenha `.env` fora do Git e rotacione qualquer
segredo que tenha sido usado em um arquivo, print, aula ou deploy anterior.

## Ordem de correcao

1. Criar um projeto Supabase de desenvolvimento separado.
2. Aplicar o novo schema e cadastrar o primeiro owner.
3. Executar e testar a API Flask localmente.
4. Adicionar login ao frontend.
5. Migrar a leitura dos leads para a API.
6. Migrar criacao, edicao, Kanban e arquivamento.
7. Remover SDK CRUD direto, `localStorage` de configuracao e policy publica.
8. Somente depois integrar WhatsApp/n8n por webhook assinado.

