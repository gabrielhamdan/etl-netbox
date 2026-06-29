import os
import mysql.connector
import pynetbox
import re
import unicodedata
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

MYSQL_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASS'),
    'database': os.getenv('DB_NAME')
}

NETBOX_URL = os.getenv('NB_URL')
NETBOX_TOKEN = os.getenv('NB_TOKEN')

nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)

def formatar_slug(texto):
    if not texto:
        return ""
    texto = str(texto)
    texto = unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8')
    slug = texto.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')

def main():
    print("Iniciando ETL...")

    # ==========================================
    # 1. EXTRAÇÃO (MySQL)
    # ==========================================
    try:
        conexao = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conexao.cursor(dictionary=True)
        
        query = """
            SELECT 
                u.unidade_sigla,
                u.unidade_nome,
                c.nome AS contato_nome,
                c.email AS contato_email,
                c.telefone AS contato_telefone,
                c.tecnico,
                c.seguranca,
                c.administrativo
            FROM 
                unidade u
            JOIN 
                contato_unidade c ON u.id_unidade = c.id_unidade
            WHERE c.nome IS NOT NULL;
        """
        cursor.execute(query)
        contatos_mysql = cursor.fetchall()
        
        if not contatos_mysql:
            print("❌ Nenhum contacto encontrado.")
            return
            
    except mysql.connector.Error as err:
        print(f"❌ Erro MySQL: {err}")
        return
    finally:
        if 'conexao' in locals() and conexao.is_connected():
            cursor.close()
            conexao.close()

    # ==========================================
    # 2. AGRUPAR POR UNIDADE
    # ==========================================
    contatos_por_unidade = defaultdict(list)
    for linha in contatos_mysql:
        chave = linha['unidade_sigla'].strip()
        contatos_por_unidade[chave].append(linha)

    # ==========================================
    # 3. ITERAR POR UNIDADE → SITE → CONTACTOS
    # ==========================================
    for sigla_bruta, contatos_da_unidade in contatos_por_unidade.items():
        linha_base = contatos_da_unidade[0]

        site_name_curto = sigla_bruta.capitalize()
        site_slug_esperado = formatar_slug(sigla_bruta).lower()
        grupo_slug = site_slug_esperado.split('-')[0]
        grupo_nome = grupo_slug.capitalize()

        print(f"\n{'='*50}")
        print(f"🏢 Unidade: {sigla_bruta} ({linha_base['unidade_nome']})")

        # UPSERT: SITE
        site = None
        sites_candidatos = nb.dcim.sites.filter(slug__ic=site_slug_esperado)

        if sites_candidatos:
            for s in sites_candidatos:
                if str(s.slug).lower().strip() == site_slug_esperado:
                    site = s
                    break

        if not site:
            grupo_obj = nb.dcim.site_groups.get(slug=grupo_slug)
            if not grupo_obj:
                grupo_obj = nb.dcim.site_groups.create(name=grupo_nome, slug=grupo_slug)

            try:
                site = nb.dcim.sites.create(
                    name=site_name_curto,
                    slug=site_slug_esperado,
                    status='active',
                    group=grupo_obj.id,
                    description=linha_base['unidade_nome'].strip()
                )
                print(f"🏗️ Novo Site '{site_name_curto}' criado com sucesso.")
            except pynetbox.core.query.RequestError as e:
                print(f"❌ Erro ao criar o Site: {e.error}")
                continue
        else:
            print(f"📍 Site '{site.name}' já existente.")

        # UPSERT: CONTACTOS E CAMPOS PERSONALIZADOS
        print("Iniciando processamento dos contactos...")

        for linha in contatos_da_unidade:
            contato_name = linha['contato_nome'].strip()
            print(f"\n👤 Processando: {contato_name}")

            email_bruto = str(linha.get('contato_email') or '').strip()
            telefone_bruto = str(linha.get('contato_telefone') or '').strip()

            lista_emails = [e.strip() for e in email_bruto.split(';') if e.strip()]
            lista_telefones = [t.strip() for t in telefone_bruto.split(';') if t.strip()]

            email_principal = ""
            emails_restantes = []
            for e in lista_emails:
                if "@" in e and not email_principal:
                    email_principal = e
                else:
                    emails_restantes.append(e)

            telefone_principal = ""
            telefones_restantes = []
            if lista_telefones:
                telefone_principal = lista_telefones[0]
                telefones_restantes = lista_telefones[1:]

            custom_fields = {}
            if emails_restantes:
                custom_fields['Email_Alternativo'] = "; ".join(emails_restantes)
            if telefones_restantes:
                custom_fields['Telefone_Alternativo'] = "; ".join(telefones_restantes)

            responsabilidades = []
            if linha.get('tecnico') == 1: responsabilidades.append('Técnico')
            if linha.get('seguranca') == 1: responsabilidades.append('Segurança')
            if linha.get('administrativo') == 1: responsabilidades.append('Administrativo')

            if responsabilidades:
                custom_fields['funcao_de_contatos'] = responsabilidades

            dados_contato = {"name": contato_name}

            if custom_fields:
                dados_contato["custom_fields"] = custom_fields

            if email_principal: dados_contato["email"] = email_principal
            if telefone_principal: dados_contato["phone"] = telefone_principal

            resultados = list(nb.tenancy.contacts.filter(name=contato_name))
            contato = resultados[0] if resultados else None

            if not contato:
                try:
                    contato = nb.tenancy.contacts.create(**dados_contato)
                    print(f"   ➕ Contacto criado.")
                except pynetbox.core.query.RequestError as e:
                    print(f"   ❌ Erro ao criar: {e.error}")
                    continue
            else:
                try:
                    contato.update(dados_contato)
                    print(f"   ✔️ Contacto atualizado.")
                except pynetbox.core.query.RequestError as e:
                    print(f"   ❌ Erro ao atualizar: {e.error}")

            # LIGAÇÃO AO SITE
            role_name_generica = "Colaborador da Unidade"
            role_slug_generica = "colaborador-da-unidade"

            role_obj = nb.tenancy.contact_roles.get(slug=role_slug_generica)
            if not role_obj:
                role_obj = nb.tenancy.contact_roles.create(name=role_name_generica, slug=role_slug_generica)

            try:
                atribuicao_existente = nb.tenancy.contact_assignments.filter(
                    object_type='dcim.site',
                    object_id=site.id,
                    contact_id=contato.id,
                    role_id=role_obj.id
                )

                if not atribuicao_existente:
                    nb.tenancy.contact_assignments.create(
                        object_type='dcim.site',
                        object_id=site.id,
                        contact=contato.id,
                        role=role_obj.id
                    )
                    print(f"   🔗 Ligado ao site '{site.name}'.")
                else:
                    print(f"   ⚠️ Ligação já existia.")

            except pynetbox.core.query.RequestError as e:
                print(f"   ❌ Erro ao criar ligação: {e.error}")

    print("\n🚀 FIM DO PROCESSO!")

if __name__ == "__main__":
    main()