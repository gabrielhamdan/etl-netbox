# ETL MySQL → NetBox

Script de sincronização que extrai dados de contatos de unidades a partir de um banco MySQL e os carrega no NetBox via API, criando ou atualizando Sites, Contatos e suas associações.

## Pré-requisitos

| Requisito | Versão recomendada |
|---|---|
| Python | 3.9+ |
| MySQL Server | 5.7+ ou 8.x |
| NetBox | 3.x (com API habilitada) |

Bibliotecas Python necessárias:

```
mysql-connector-python
pynetbox
python-dotenv
```

## Quick Start

**1. Clone o repositório**

```bash
git clone <URL_DO_REPOSITORIO>
cd <PASTA_DO_PROJETO>
```

**2. Crie e ative um ambiente virtual** _(recomendado)_

```bash
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
```

**3. Instale as dependências**

```bash
pip install -r requirements.txt
```

**4. Configure as variáveis de ambiente**

Copie o arquivo de exemplo e preencha com os valores reais:

```bash
cp .env.example .env
```

Edite o `.env` com as credenciais do seu ambiente (veja a seção abaixo).

**5. Execute o script**

```bash
python etl.py
```

## Configuração de Ambiente

Crie um arquivo `.env` na raiz do projeto com base no `.env.example`:

```env
# Banco de dados MySQL
DB_HOST=localhost
DB_USER=seu_usuario
DB_PASS=sua_senha
DB_NAME=nome_do_banco

# NetBox
NB_URL=https://netbox.sua-empresa.com
NB_TOKEN=seu_token_de_api_aqui
```

## O que o script faz

O pipeline segue três etapas principais:

```
MySQL ──► Extração ──► Upsert NetBox (Site + Grupo) ──► Upsert Contatos + Vínculos
```

**1. Extração (MySQL)**
Consulta a tabela `unidade` junto com `contato_unidade`.

**2. Upsert de Site**
Cria ou reutiliza um Site no NetBox com base no slug derivado da sigla da unidade. O grupo do site é criado automaticamente se não existir.

**3. Upsert de Contatos**
Para cada contato retornado:
- Cria ou atualiza nome, e-mail e telefone principais.
- Distribui e-mails e telefones extras nos campos personalizados `Email_Alternativo` e `Telefone_Alternativo`.
- Preenche o campo customizado `funcao_de_contatos` com base nas colunas booleanas `tecnico`, `seguranca` e `administrativo`.
- Vincula o contato ao Site com o papel _"Colaborador da Unidade"_.

## Campos Personalizados Necessários no NetBox

Antes de executar, certifique-se de que os seguintes **Custom Fields** estão criados no NetBox para o objeto `Contact`:

| Campo | Tipo | Descrição |
|---|---|---|
| `Email_Alternativo` | Text | E-mails secundários separados por `;` |
| `Telefone_Alternativo` | Text | Telefones secundários separados por `;` |
| `funcao_de_contatos` | Multi-select | Valores: `Técnico`, `Segurança`, `Administrativo` |

## Observações Técnicas

- A lógica de upsert é baseada em **slug** para Sites e **nome exato** para Contatos, evitando duplicatas em re-execuções.
- O campo `description` do Site recebe o nome longo da unidade; o `name` exibe a sigla capitalizada (ex: `Embrapa-snt`).