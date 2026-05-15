import os
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from datetime import datetime

from lxml import etree

import streamlit as st
import streamlit.components.v1 as components
from pypdf import PdfReader
from openai import OpenAI

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

# ==================================================
# CONFIGURAÇÃO DE CAMINHOS
# ==================================================
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR

# Pastas possíveis para o corpus de referência.
# O GitHub/Streamlit exige que o nome da pasta seja exatamente igual.
# Aqui o app aceita variações comuns para evitar erro por diferença de nome.
POSSIVEIS_SUPORTE_DIRS = [
    ROOT_DIR / "00. Suporte ao aplicativo",
    ROOT_DIR / "00. Suporte ao APP",
    ROOT_DIR / "00. Suporte ao app",
    ROOT_DIR / "00. SUPORTE AO APLICATIVO",
    BASE_DIR / "00. Suporte ao aplicativo",
    BASE_DIR / "00. Suporte ao APP",
]

SUPORTE_DIR = next((p for p in POSSIVEIS_SUPORTE_DIRS if p.exists()), POSSIVEIS_SUPORTE_DIRS[0])

# Pasta de imagens/layout
POSSIVEIS_IMAGENS_DIRS = [
    ROOT_DIR / "02. Figuras e Layout",
    ROOT_DIR / "02. Figuras e layout",
    ROOT_DIR / "02. FIGURAS E LAYOUT",
    BASE_DIR / "02. Figuras e Layout",
]
IMAGENS_DIR = next((p for p in POSSIVEIS_IMAGENS_DIRS if p.exists()), POSSIVEIS_IMAGENS_DIRS[0])

# Usa o novo logo HFACS LOGO2; se não encontrar, tenta o antigo
HFACS_LOGO = None
for nome_arquivo in [
    "HFACS LOGO2.png",
    "HFACS LOGO2.jpg",
    "HFACS LOGO2.jpeg",
    "HFACS LOGO.png",
    "HFACS LOGO.jpg",
]:
    caminho = IMAGENS_DIR / nome_arquivo
    if caminho.exists():
        HFACS_LOGO = caminho
        break

PARTE_SUPERIOR = IMAGENS_DIR / "PARTE SUPERIOR.png"
PEA_LOGO = IMAGENS_DIR / "PEA LOGO.png"
UFRJ_LOGO = IMAGENS_DIR / "UFRJ LOGO.png"

# Modelo Word usado apenas para exportação do relatório final
MODELO_WORD_NOME = "MODELO_WORD2_caixas_texto(1).docx"
MODELO_WORD_NOME_ALTERNATIVO = "MODELO_WORD2_caixas_texto(1)(1).docx"
MODELO_WORD_NOME_ATUAL = "MODELO_WORD2_caixas_texto(1)(3).docx"
POSSIVEIS_MODELOS_WORD = [
    BASE_DIR / MODELO_WORD_NOME_ATUAL,
    ROOT_DIR / MODELO_WORD_NOME_ATUAL,
    Path.cwd() / MODELO_WORD_NOME_ATUAL,
    BASE_DIR / MODELO_WORD_NOME,
    ROOT_DIR / MODELO_WORD_NOME,
    Path.cwd() / MODELO_WORD_NOME,
    BASE_DIR / MODELO_WORD_NOME_ALTERNATIVO,
    ROOT_DIR / MODELO_WORD_NOME_ALTERNATIVO,
    Path.cwd() / MODELO_WORD_NOME_ALTERNATIVO,
]



# ==================================================
# LEITURA DOS PDFs DE REFERÊNCIA (00. Suporte ao APP)
# ==================================================
@st.cache_data(show_spinner=True)
def carregar_corpus_pdf(
    max_chars_total: int = 1000000,
    max_chars_por_pdf: int = 100000,
):
    """
    Lê TODOS os PDFs de SUPORTE_DIR e monta um corpus de referência.
    """
    if not SUPORTE_DIR.exists():
        return "", 0, 0

    partes = []
    n_pdfs = 0

    for pdf_path in sorted(SUPORTE_DIR.rglob("*.pdf")):
        try:
            reader = PdfReader(str(pdf_path))
            texto_paginas = []
            for page in reader.pages[:50]:
                texto_paginas.append(page.extract_text() or "")
            texto_pdf = "\n".join(texto_paginas).strip()
            if not texto_pdf:
                continue

            if len(texto_pdf) > max_chars_por_pdf:
                texto_pdf = texto_pdf[:max_chars_por_pdf]

            partes.append(f"[Fonte: {pdf_path.name}]\n{texto_pdf}")
            n_pdfs += 1

        except Exception as e:
            st.warning(f"Falha ao ler {pdf_path.name}: {e}")

    corpus = "\n\n".join(partes)
    if len(corpus) > max_chars_total:
        corpus = corpus[:max_chars_total]

    return corpus, n_pdfs, len(corpus)


# ==================================================
# LEITURA DO PDF ENVIADO PELO USUÁRIO (ARQUIVO DO ACIDENTE)
# ==================================================
def extrair_textos_pdfs_upload(uploaded_files, max_chars_total: int = 4000000):
    """
    Extrai texto de vários PDFs enviados pelo usuário e retorna:
    - texto consolidado dos PDFs
    - total de caracteres extraídos antes do corte
    - total de caracteres efetivamente enviados para a IA
    - total de páginas lidas
    - quantidade de PDFs lidos com sucesso
    - lista de avisos/erros por arquivo
    """

    if not uploaded_files:
        return "", 0, 0, 0, 0, []

    partes = []
    total_caracteres_extraidos = 0
    total_paginas = 0
    total_pdfs_lidos = 0
    avisos = []

    for uploaded_file in uploaded_files:
        try:
            reader = PdfReader(uploaded_file)

            texto_paginas = []
            for page in reader.pages:
                texto_paginas.append(page.extract_text() or "")

            texto_completo = "\n".join(texto_paginas).strip()
            caracteres_pdf = len(texto_completo)
            paginas_pdf = len(reader.pages)

            total_caracteres_extraidos += caracteres_pdf
            total_paginas += paginas_pdf

            if texto_completo:
                partes.append(
                    f"\n\n===== ARQUIVO DO ACIDENTE: {uploaded_file.name} =====\n"
                    f"Páginas: {paginas_pdf}\n"
                    f"Caracteres extraídos deste arquivo: {caracteres_pdf}\n\n"
                    f"{texto_completo}"
                )
                total_pdfs_lidos += 1
            else:
                avisos.append(
                    f"O arquivo '{uploaded_file.name}' foi carregado, mas nenhum texto pôde ser extraído. "
                    "Isso pode ocorrer quando o PDF é escaneado como imagem."
                )

        except Exception as e:
            avisos.append(f"Falha ao ler o PDF '{uploaded_file.name}': {e}")

    texto_consolidado = "\n".join(partes).strip()

    if len(texto_consolidado) > max_chars_total:
        texto_limitado = texto_consolidado[:max_chars_total]
    else:
        texto_limitado = texto_consolidado

    caracteres_enviados = len(texto_limitado)

    return (
        texto_limitado,
        total_caracteres_extraidos,
        caracteres_enviados,
        total_paginas,
        total_pdfs_lidos,
        avisos,
    )


# ==================================================
# OPENAI
# ==================================================
def obter_cliente_openai():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY não definida como variável de ambiente."
    try:
        client = OpenAI(api_key=api_key)
        return client, None
    except Exception as e:
        return None, f"Erro ao inicializar cliente OpenAI: {e}"


# ==================================================
# MONTAGEM DO CONTEXTO DO ACIDENTE
# ==================================================
def montar_contexto_acidente(
    dados_analista,
    dados_basicos,
    descricao_detalhada,
    atividade,
    horas_extras,
    nivel1_comentarios,
    nivel1_respostas,
    nivel2_comentarios,
    nivel2_respostas,
    nivel3_comentarios,
    nivel3_respostas,
    nivel4_comentarios,
    nivel4_respostas,
    nivel5_comentarios,
    nivel5_respostas,
):
    partes = []

    partes.append("=== DADOS DO ANALISTA ===")
    for k, v in dados_analista.items():
        partes.append(f"{k}: {v or 'não informado'}")

    partes.append("\n=== DADOS BÁSICOS DO ACIDENTE ===")
    for k, v in dados_basicos.items():
        partes.append(f"{k}: {v or 'não informado'}")

    partes.append("\n=== DESCRIÇÃO DETALHADA DO ACIDENTE ===")
    partes.append(descricao_detalhada or "não informada")

    partes.append("\n=== ATIVIDADE NO MOMENTO DO ACIDENTE ===")
    partes.append(atividade or "não informada")
    partes.append(f"O colaborador estava em hora extra? {horas_extras or 'não informado'}")

    def bloco_nivel(titulo, comentarios, respostas_dict):
        linhas = [f"\n=== {titulo} ==="]
        linhas.append(f"Comentários principais do analista: {comentarios or 'não informado'}")
        if respostas_dict:
            linhas.append(
                "Detalhamento adicional (respostas guiadas; podem conter classificações iniciais incorretas):"
            )
            for chave, texto in respostas_dict.items():
                if texto and str(texto).strip():
                    linhas.append(f"- {chave.replace('_', ' ')}: {str(texto).strip()}")
        return "\n".join(linhas)

    partes.append(bloco_nivel("NÍVEL 5 – Fatores externos", nivel5_comentarios, nivel5_respostas))
    partes.append(bloco_nivel("NÍVEL 4 – Influências organizacionais", nivel4_comentarios, nivel4_respostas))
    partes.append(bloco_nivel("NÍVEL 3 – Supervisão inadequada", nivel3_comentarios, nivel3_respostas))
    partes.append(bloco_nivel("NÍVEL 2 – Condições precursoras", nivel2_comentarios, nivel2_respostas))
    partes.append(bloco_nivel("NÍVEL 1 – Atos inseguros", nivel1_comentarios, nivel1_respostas))

    return "\n".join(partes)


# ==================================================
# CHAMADA À IA – RELATÓRIO COMPLETO + RESUMO + RECOMENDAÇÕES
# ==================================================
def chamar_ia_gerar_relatorios(client, contexto_acidente: str, corpus_referencia: str):
    """
    Retorna:
      - relatorio_completo (texto)
      - resumo_conciso (texto)
      - recomendacoes (texto)
      - hfacs_caixas (dict)
      - erro (string ou None)
    """

    system_prompt = """
Você é um co-analista sistêmico especializado em HFACS, AcciMap e STAMP, apoiando investigações de acidentes
em sistemas sociotecnicos complexos.

SUAS RESPONSABILIDADES:

1) REINTERPRETAR e CLASSIFICAR as informações do acidente nos níveis corretos do HFACS
   (Fatores externos, Influências organizacionais, Supervisão inadequada, Condições precursoras, Atos inseguros),
   mesmo que o analista humano tenha alocado itens em níveis inadequados.

2) REDIGIR os textos EM PORTUGUÊS BRASILEIRO CORRETO, com linguagem técnica clara e concisa, adequada a
   relatórios acadêmicos e de investigação de acidentes.

3) PRODUZIR TRÊS RESULTADOS, em JSON:
   (a) "relatorio_completo": um texto integrado, descrevendo o acidente e o encadeamento causal, com análise
       por nível HFACS, evitando culpabilização simplista (MESMO NO NIVEL DO ATO INSEGURO, NÃO CULPABILIZAR A VITIMA).
   (b) "resumo_conciso": síntese destacando principais fatores por nível HFACS, começando por fatores externos e terminando em atos inseguros, e palavras-chave relevantes, em
       frases curtas para uso em relatorio tecnico.
   (c) "recomendacoes": conjunto de recomendações sistêmicas focadas em reduzir a probabilidade de recorrência.

   A ordem de apresentação dos níveis nos resultados deve ser SEMPRE:
   Fatores externos → Influências organizacionais → Supervisão inadequada → Condições precursoras → Atos inseguros.

4) TRATAR ERROS DE CLASSIFICAÇÃO:
   - Se fatores estiverem descritos em níveis errados (por exemplo, fator organizacional em Fatores externos),
     reorganize-os na análise, sem perder informação.

5) ESTILO:
   - Evite linguagem coloquial.
   - Mantenha terminologia consistente: "atos inseguros", "condições precursoras", "supervisão inadequada",
     "influências organizacionais", "fatores externos".
   - Foque em explicações orientadas à prevenção, não à culpa (NUNCA COLOQUE A CULPA NA VÍTIMA).

ORIENTAÇÃO ADICIONAL – ENFOQUE SISTÊMICO EMERGENTE:

Leia o Corpus de Referência para identificar os termos técnicos e responder de forma correta.

Considera os TODOS os anexos com as informações do acidente e os dados digitados na interface da ferramenta

Em Influências Organizacionais busque falhas latentes como exemplos, mas não limitados: 
Recursos Humanos (Seleção, treinamento, ritmo de trabalho e fadiga
Recursos Monetários/Orçamentários: Falta de verbas para segurança.
Equipamentos/Instalações: Manutenção inadequada, ferramentas incorretas ou ambiente de trabalho inadequado
Estrutura: Cadeia de comando, delegação de autoridade.
Políticas e Cultura: Normas de segurança (ou falta delas), ênfase na produção acima da segurança, comunicação ineficiente.
Procedimentos: Procedimentos operacionais padrão (SOPs) incorretos ou inexistentes.
Falhas na liderança de alto nível, objetivos de missão/trabalho irreais.
Alta Exigencia

Em Fatores externos busque nas informações enviadas pelo analista
Fatores Regulatórios e Políticos: leis nacionais e internacionais, normas de agências reguladoras (como a ANAC na aviação ou o Ministério do Trabalho), e a fiscalização governamental.
Fatores Econômicos e Sociais: Pressões do mercado financeiro, crises econômicas que reduzem investimentos, cultura de segurança da sociedade e até a influência de sindicatos ou grupos de interesse
Fatores Ambientais: chuva, calor, ruído ou tecnológico (design de painéis, automação) que afeta o operador no momento da tarefa
Questões sistêmicas de mercado ou legislação que moldam como a empresa inteira funciona
Indique Possíveis lacunas entre o trabalho real e os requisitos normativos.
falhas de orientação por órgãos reguladores
tolerância setorial a práticas inseguras
ausência de atualização normativa
contratos que pressionam prazo e produção
conflitos entre norma e prática real

NA classificação dos ATOS INSEGUROS ao descrever as causas, explique o contexto através das falhas latentes Não atribua culpa individual, erro humano isolado ou negligência pessoal
Na classificação dos ATOS INSEGUROS Sempre que identificar atribuição direta de culpa, reestruture a análise explicando as influências sistêmicas.
Na classificação dos ATOS INSEGUROS Sempre que uma ação humana inadequada for identificada, explique por que essa ação fazia sentido localmente

Analise o evento como um acidente sistêmico emergente, resultante de interações não lineares entre
fatores técnicos, humanos, organizacionais, regulatórios e culturais.
Não atribua culpa individual, erro humano isolado ou negligência pessoal (mesmo no nivel de atos inseguros, Reinterprete qualquer menção a erro humano como consequência de condições latentes, variabilidade operacional).
Trate ações humanas como adaptações racionais a restrições do sistema.
Busque falhas de controle, feedback inadequado, pressões organizacionais, decisões históricas e lacunas de governança.

Reinterprete qualquer menção a erro humano como consequência de condições latentes, variabilidade operacional
e pressões sistêmicas. Mostre como a decisão humana foi moldada pelo contexto.

Identifique pressões (produção, tempo, clima, manutenção atrasada, metas, cultura) que moldaram o comportamento
dos agentes humanos, tecnológicos e organizacionais.

Sempre que identificar atribuição direta de culpa, reestruture a análise explicando as influências sistêmicas.

Sempre que uma ação humana inadequada for identificada, explique por que essa ação fazia sentido localmente
para o operador no momento do evento, considerando:
– objetivos conflitantes
– pressão de tempo ou produção
– informação incompleta
– regras impraticáveis
– normalização do desvio
Nunca classifique a ação como causa raiz.

ORGANIZE AS CAUSAS, FATORES QUE LEVAM AO ACIDENTE EM TOPICOS 
EXEMPLO:

ATO INSEGURO
- 
- 
-
-

DETALHAMENTO DAS EXPLICAÇÕES
Explique cada nível de foram detalhada, mencionando e explorando cada informação.
Explique e avalie em profundidade cada um dos níves na ordem: fatores externos, influências organizacionais, supervisão insegura, condições precursoras e atos inseguros


CONSIDERAÇÕES FINAIS
O ACIDENTE JÁ CLASSIFICADO E RECLASSIFICADO, ESTA ETAPA DEVE INFORMAR OS DETALHES DA INVESTIGAÇÃO DE FORMA PROFUNDA!!
APROFUNDE EM DETALHES A INVESTIGAÇÃO - FAÇA UMA ANÁLISE PROFUNDA, INFORMANDO EM DETALHES, COM TERMOS TECNICOS E COM INFORMAÇÕES DETALHADAS DO ARQUIVO ANEXADO OU INFORMAÇÕES DA INTERFACE
Nas considerações finais, faça uma pequena explicação de como os fatores sistemicos e como TODAS latentes levaram aos atos inseguros e consequentemente aos acidentes. SÓ MNECIONE OS ATOS INSEGUROS NO FINAL DA FRASE
SÓ MENCIONE OS ATOS INSEGURO DEPOIS DE MENCIONAR TODOS OS FATORES LATENTES, sem colocar a culpa no fator humano
nesta etapa de considerações finais Reinterprete qualquer menção a erro humano como consequência de condições latentes, variabilidade operacional
e pressões sistêmicas. Mostre como a decisão humana foi moldada pelo contexto. NUNCA INDIQUE QUE OS ATOS INSEGUROS FORAM A CAUSA DO ACIDENTE, MAS DEMONSTRE COMO OS FATORES LATENTES LEVARAM AO ACIDENTE

RECOMENDAÇÕES:

Gere como resultado as "recomendações".
Cada recomendação deve:
- RECOMENDAÇÕES EPECÍFICAS PARA O ACIDENTE 
- EM CADA RECOMENDAÇÃO CITAR A RECOMDNAÇÃO E A FALHA QUE MOTIVOU ESSA RECOMENDAÇÃO
– explicitar qual limitação sistêmica ela corrige
– indicar qual interação do sistema ela modifica
– explicar por que reduz a probabilidade de recorrência
– evitar soluções genéricas ou abstratas.

INÍCIO OBRIGATÓRIO DO RELATÓRIO COMPLETO:
- O campo "relatorio_completo" DEVE começar exatamente com a frase:

  "Com base no relatório detalhado do acidente e considerando o modelos que são a base desta ferramenta, segue a análise e classificação das causas do acidente:"

  (sem aspas, respeitando maiúsculas, acentuação e redação). LOgo em seguida coloque os dados básicos do acidente (tipo de acidente, local do acidente, data, como ocorreu, vítimas)

CLASSIFICAÇÃO PARA PREENCHIMENTO DO MODELO WORD/PDF:
Além dos textos do relatório, gere o campo "hfacs_caixas" como um objeto JSON.
Cada chave abaixo deve conter uma lista com no máximo 3 frases curtas.
Se houver menos de 3 fatores identificados, deixe os itens restantes como string vazia.
Não invente fatores. Use apenas fatores coerentes com o acidente analisado.

Chaves obrigatórias do campo "hfacs_caixas":
- governo_orgaos_reguladores
- influencias_politicas_economicas
- fisico_social_cultural
- mercado_clientes
- gerenciamento_recursos
- clima_organizacional
- processo_operacional
- supervisao_inadequada
- planejamento_inadequado_operacoes
- falha_resolver_problemas
- violacao_supervisao
- ambiente_fisico
- ambiente_tecnico
- estado_mental_adverso
- estado_fisico_adverso
- limitacoes_fisicas_mentais
- gerenciamento_equipe_recursos
- execucao_pessoal
- erros_decisao
- erros_baseados_habilidade
- erros_percepcao
- rotina
- excepcional

IMPORTANTE: se houver atos inseguros no relatório textual, as caixas do nível 1 NÃO podem ficar vazias.
Preencha obrigatoriamente as chaves erros_decisao, erros_baseados_habilidade, erros_percepcao, rotina ou excepcional, conforme o caso.

PADRONIZAÇÃO OBRIGATÓRIA DA CLASSIFICAÇÃO HFACS PARA O MODELO WORD/PDF:

O campo "hfacs_caixas" será usado para preencher a página de classificação visual do relatório.
Por isso, ele deve ser tratado como uma etapa analítica independente e obrigatória, não como resumo superficial.

Para cada uma das 23 chaves de "hfacs_caixas":
- Leia o relatório do acidente, os dados preenchidos na interface e o corpus de referência.
- Preencha até 3 frases curtas, específicas e objetivas, com 5 a 14 palavras cada.
- Só deixe uma posição vazia quando realmente não houver evidência relacionada no acidente.
- Não use frases genéricas como "falha organizacional" sem especificar a falha.
- Não repita a mesma frase em categorias diferentes.
- Não copie frases longas do relatório; sintetize em linguagem curta para caber nas caixas.
- Priorize termos concretos do acidente: equipamento, área, procedimento, supervisão, comunicação, permissão, risco, contratados, detector, rotulagem, pressão produtiva, norma, etc.

Critério mínimo de robustez:
- Para acidentes complexos com morte, exposição química, explosão, incêndio, queda, ruptura, soterramento ou vazamento, procure preencher pelo menos 1 item em cada categoria aplicável dos cinco níveis.
- Se o texto do acidente trouxer evidências suficientes, preencha 2 ou 3 itens por categoria.
- Os níveis Fatores externos, Influências organizacionais, Supervisão inadequada, Condições precursoras e Atos inseguros devem aparecer de forma consistente tanto no texto quanto em "hfacs_caixas".

RELATÓRIO COMPLETO:
- Em cada nível HFACS, apresente primeiro uma lista de fatores e depois um parágrafo "Explicação:".
- Não entregue apenas um resumo curto. A análise deve ser suficientemente detalhada para sustentar a classificação das caixas.

FORMATO DE SAÍDA:
Retorne SEMPRE um JSON válido, por exemplo:

{
  "relatorio_completo": "...",
  "resumo_conciso": "...",
  "recomendacoes": "...",
  "hfacs_caixas": {
    "governo_orgaos_reguladores": ["", "", ""],
    "influencias_politicas_economicas": ["", "", ""],
    "fisico_social_cultural": ["", "", ""],
    "mercado_clientes": ["", "", ""],
    "gerenciamento_recursos": ["", "", ""],
    "clima_organizacional": ["", "", ""],
    "processo_operacional": ["", "", ""],
    "supervisao_inadequada": ["", "", ""],
    "planejamento_inadequado_operacoes": ["", "", ""],
    "falha_resolver_problemas": ["", "", ""],
    "violacao_supervisao": ["", "", ""],
    "ambiente_fisico": ["", "", ""],
    "ambiente_tecnico": ["", "", ""],
    "estado_mental_adverso": ["", "", ""],
    "estado_fisico_adverso": ["", "", ""],
    "limitacoes_fisicas_mentais": ["", "", ""],
    "gerenciamento_equipe_recursos": ["", "", ""],
    "execucao_pessoal": ["", "", ""],
    "erros_decisao": ["", "", ""],
    "erros_baseados_habilidade": ["", "", ""],
    "erros_percepcao": ["", "", ""],
    "rotina": ["", "", ""],
    "excepcional": ["", "", ""]
  }
}
"""

    user_prompt = f"""
A seguir está um excerto de CORPUS DE REFERÊNCIA (artigos/manuais HFACS/AcciMap/STAMP):

\"\"\"{corpus_referencia}\"\"\"

Em seguida, apresento o CONTEXTO DO ACIDENTE, tal como preenchido por um analista humano.
As classificações por nível podem conter erros. Sua tarefa é reclassificar corretamente e
gerar os relatórios e recomendações solicitados.

=== CONTEXTO DO ACIDENTE ===
{contexto_acidente}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        conteudo = response.choices[0].message.content

        try:
            dados = json.loads(conteudo)
            relatorio_completo = dados.get("relatorio_completo", "").strip()
            resumo_conciso = dados.get("resumo_conciso", "").strip()
            recomendacoes_raw = dados.get("recomendacoes", "")
            hfacs_caixas = normalizar_hfacs_caixas(dados.get("hfacs_caixas", {}))

            if isinstance(recomendacoes_raw, list):
                recomendacoes_formatadas = []

                for i, item in enumerate(recomendacoes_raw, start=1):
                    if isinstance(item, dict):
                        recomendacao = item.get("recomendacao", "")
                        falha = item.get("falha_motivadora", "")
                        limitacao = item.get("limitacao_sistematica_corrigida", "")
                        interacao = item.get("interacao_sistema_modificada", "")
                        reducao = item.get("reduz_probabilidade", "")

                        texto_item = f"""
{i}. Recomendação: {recomendacao}

   Falha que motivou a recomendação: {falha}

   Limitação sistêmica corrigida: {limitacao}

   Interação do sistema modificada: {interacao}

   Como reduz a probabilidade de recorrência: {reducao}
"""
                        recomendacoes_formatadas.append(texto_item.strip())

                    else:
                        recomendacoes_formatadas.append(f"{i}. {str(item).strip()}")

                recomendacoes = "\n\n".join(recomendacoes_formatadas)

            elif isinstance(recomendacoes_raw, dict):
                recomendacao = recomendacoes_raw.get("recomendacao", "")
                falha = recomendacoes_raw.get("falha_motivadora", "")
                limitacao = recomendacoes_raw.get("limitacao_sistematica_corrigida", "")
                interacao = recomendacoes_raw.get("interacao_sistema_modificada", "")
                reducao = recomendacoes_raw.get("reduz_probabilidade", "")

                recomendacoes = f"""
1. Recomendação: {recomendacao}

   Falha que motivou a recomendação: {falha}

   Limitação sistêmica corrigida: {limitacao}

   Interação do sistema modificada: {interacao}

   Como reduz a probabilidade de recorrência: {reducao}
""".strip()

            else:
                recomendacoes = str(recomendacoes_raw).strip()

        except json.JSONDecodeError:
            relatorio_completo = conteudo.strip()
            resumo_conciso = (
                "Resumo não pôde ser extraído automaticamente; ajuste o prompt ou gere manualmente."
            )
            recomendacoes = (
                "Recomendações não puderam ser extraídas automaticamente; ajuste o prompt ou gere manualmente."
            )
            hfacs_caixas = HFACS_CAIXAS_VAZIAS.copy()

        texto_apoio_caixas = "\n".join([resumo_conciso, recomendacoes, contexto_acidente])
        hfacs_caixas = completar_caixas_hfacs_por_texto(hfacs_caixas, relatorio_completo, texto_apoio_caixas)

        return relatorio_completo, resumo_conciso, recomendacoes, hfacs_caixas, None

    except Exception as e:
        return "", "", "", HFACS_CAIXAS_VAZIAS.copy(), f"Erro ao chamar a IA: {e}"



# ==================================================
# EXPORTAÇÃO WORD/PDF COM MODELO
# ==================================================
HFACS_CAIXAS_ORDEM = [
    "governo_orgaos_reguladores",
    "influencias_politicas_economicas",
    "fisico_social_cultural",
    "mercado_clientes",
    "gerenciamento_recursos",
    "clima_organizacional",
    "processo_operacional",
    "supervisao_inadequada",
    "planejamento_inadequado_operacoes",
    "falha_resolver_problemas",
    "violacao_supervisao",
    "ambiente_fisico",
    "ambiente_tecnico",
    "estado_mental_adverso",
    "estado_fisico_adverso",
    "limitacoes_fisicas_mentais",
    "gerenciamento_equipe_recursos",
    "execucao_pessoal",
    "erros_decisao",
    "erros_baseados_habilidade",
    "erros_percepcao",
    "rotina",
    "excepcional",
]

HFACS_CAIXAS_VAZIAS = {chave: ["", "", ""] for chave in HFACS_CAIXAS_ORDEM}


def localizar_modelo_word():
    for caminho in POSSIVEIS_MODELOS_WORD:
        if caminho.exists():
            return caminho

    # Aceita pequenas variações do nome geradas pelo Windows/navegador, sem exigir alteração manual do código.
    for pasta in [BASE_DIR, ROOT_DIR, Path.cwd()]:
        for caminho in sorted(pasta.glob("MODELO_WORD2_caixas_texto*.docx")):
            if caminho.exists():
                return caminho
    return None


def limitar_texto(texto, limite=95):
    texto = re.sub(r"\s+", " ", str(texto or "")).strip()
    if len(texto) <= limite:
        return texto
    return texto[: limite - 3].rstrip() + "..."


def primeiro_valor(*valores, padrao="não informado"):
    for valor in valores:
        if valor is not None and str(valor).strip():
            return str(valor).strip()
    return padrao


def limpar_item_caixa(texto):
    texto = re.sub(r"^[\s\-•–—\d\.)]+", "", str(texto or "")).strip()
    return limitar_texto(texto, 90)


def normalizar_chave_hfacs(chave):
    texto = str(chave or "").strip().lower()
    texto = texto.replace("ç", "c").replace("ã", "a").replace("á", "a").replace("à", "a")
    texto = texto.replace("â", "a").replace("é", "e").replace("ê", "e").replace("í", "i")
    texto = texto.replace("ó", "o").replace("ô", "o").replace("õ", "o").replace("ú", "u")
    texto = re.sub(r"[^a-z0-9]+", "_", texto).strip("_")
    return texto


def normalizar_hfacs_caixas(hfacs_caixas):
    resultado = {chave: ["", "", ""] for chave in HFACS_CAIXAS_ORDEM}
    if not isinstance(hfacs_caixas, dict):
        return resultado

    aliases = {
        "governo_orgaos_reguladores": ["governo", "orgaos_reguladores", "governo_e_orgaos_reguladores"],
        "influencias_politicas_economicas": ["influencias_politicas", "influencias_economicas", "politicas_economicas"],
        "fisico_social_cultural": ["fisico_social", "ambiente_social_cultural", "fatores_fisicos_sociais_culturais"],
        "mercado_clientes": ["mercado", "clientes", "mercado_e_clientes"],
        "gerenciamento_recursos": ["gestao_recursos", "gerenciamento_de_recursos", "recursos"],
        "clima_organizacional": ["cultura_organizacional", "clima_e_cultura_organizacional"],
        "processo_operacional": ["processos_operacionais", "procedimentos_operacionais", "processo"],
        "supervisao_inadequada": ["supervisao", "supervisao_insegura"],
        "planejamento_inadequado_operacoes": ["planejamento_inadequado", "planejamento_das_operacoes", "planejamento_inadequado_das_operacoes"],
        "falha_resolver_problemas": ["falha_em_resolver_problemas", "falha_para_resolver_problemas", "problemas_nao_resolvidos"],
        "violacao_supervisao": ["violacoes_de_supervisao", "violacao_de_supervisao", "violacoes_supervisao"],
        "ambiente_fisico": ["ambiente_fisico_de_trabalho", "condicoes_do_ambiente_fisico"],
        "ambiente_tecnico": ["ambiente_tecnologico", "ambiente_tecnico_operacional"],
        "estado_mental_adverso": ["estado_mental", "condicao_mental_adversa"],
        "estado_fisico_adverso": ["estado_fisico", "condicao_fisica_adversa"],
        "limitacoes_fisicas_mentais": ["limitacoes_fisicas_e_mentais", "limitacoes_fisicas", "limitacoes_mentais"],
        "gerenciamento_equipe_recursos": ["gerenciamento_da_equipe", "gestao_da_equipe", "gerenciamento_de_equipe_e_recursos", "crm"],
        "execucao_pessoal": ["prontidao_pessoal", "execucao_individual", "fatores_pessoais"],
        "erros_decisao": ["erro_decisao", "erros_de_decisao", "decisao", "decisoes_inadequadas"],
        "erros_baseados_habilidade": ["erro_baseado_habilidade", "erros_baseados_em_habilidade", "erros_de_habilidade", "habilidade"],
        "erros_percepcao": ["erro_percepcao", "erros_de_percepcao", "percepcao", "erros_perceptivos"],
        "rotina": ["violacao_rotina", "violacoes_de_rotina", "violacoes_rotineiras", "violacao_de_rotina"],
        "excepcional": ["violacao_excepcional", "violacoes_excepcionais", "violacao_excepcional"],
    }

    mapa_normalizado = {}
    for chave_original, valores in hfacs_caixas.items():
        mapa_normalizado[normalizar_chave_hfacs(chave_original)] = valores

    for chave in HFACS_CAIXAS_ORDEM:
        nomes_possiveis = [chave] + aliases.get(chave, [])
        valores = []
        for nome in nomes_possiveis:
            nome_norm = normalizar_chave_hfacs(nome)
            if nome_norm in mapa_normalizado:
                valores = mapa_normalizado[nome_norm]
                break
        if isinstance(valores, str):
            valores = [valores]
        if isinstance(valores, dict):
            valores = list(valores.values())
        if not isinstance(valores, list):
            valores = []
        valores_limpos = [limpar_item_caixa(v) for v in valores if str(v or "").strip()]
        resultado[chave] = (valores_limpos + ["", "", ""])[:3]

    # Alguns modelos de resposta da IA podem devolver os atos inseguros em uma chave geral.
    # Quando isso acontecer, distribui as frases curtas nas caixas finais, sem inventar conteúdo.
    atos_gerais = []
    for nome_geral in ["atos_inseguros", "nivel_1_atos_inseguros", "acoes_inseguras", "unsafe_acts"]:
        valores = mapa_normalizado.get(normalizar_chave_hfacs(nome_geral), [])
        if isinstance(valores, str):
            valores = [valores]
        if isinstance(valores, dict):
            valores = list(valores.values())
        if isinstance(valores, list):
            atos_gerais.extend([limpar_item_caixa(v) for v in valores if str(v or "").strip()])

    chaves_atos = ["erros_decisao", "erros_baseados_habilidade", "erros_percepcao", "rotina", "excepcional"]
    if atos_gerais and not any(any(resultado[chave]) for chave in chaves_atos):
        for chave, valor in zip(chaves_atos, atos_gerais[:len(chaves_atos)]):
            resultado[chave][0] = valor

    return resultado


def extrair_itens_secao(texto, termos_inicio, termos_fim=None, max_itens=15):
    texto = str(texto or "")
    if not texto.strip():
        return []
    termos_fim = termos_fim or []
    padrao_inicio = r"(" + "|".join(re.escape(t) for t in termos_inicio) + r")"
    achado = re.search(padrao_inicio, texto, flags=re.IGNORECASE)
    if not achado:
        return []
    trecho = texto[achado.end():]
    if termos_fim:
        padrao_fim = r"\n\s*(" + "|".join(re.escape(t) for t in termos_fim) + r")"
        fim = re.search(padrao_fim, trecho, flags=re.IGNORECASE)
        if fim:
            trecho = trecho[:fim.start()]

    candidatos = []
    for linha in trecho.splitlines():
        linha = re.sub(r"^[\s\-•–—\d\.)]+", "", linha).strip()
        if not linha:
            continue
        if len(linha) > 180:
            partes = re.split(r"(?<=[.;:])\s+", linha)
            candidatos.extend([p.strip() for p in partes if p.strip()])
        else:
            candidatos.append(linha)

    itens = []
    for item in candidatos:
        item_norm = limpar_item_caixa(item)
        if item_norm and item_norm.lower() not in {i.lower() for i in itens}:
            itens.append(item_norm)
        if len(itens) >= max_itens:
            break
    return itens


def completar_caixas_hfacs_por_texto(hfacs_caixas, texto_final, texto_apoio=""):
    """
    Padroniza e complementa as caixas HFACS usando somente textos já disponíveis
    (resposta da IA + resumo + contexto do acidente). Não cria fatos novos.

    Motivo: a IA pode retornar o JSON hfacs_caixas mais pobre em uma execução e mais rico em outra.
    Esta função reduz essa variação, extraindo frases curtas das seções textuais já geradas/fornecidas.
    """
    resultado = normalizar_hfacs_caixas(hfacs_caixas)
    texto_base = (str(texto_final or "") + "\n" + str(texto_apoio or "")).strip()

    if not texto_base:
        return resultado

    def adicionar(chave, candidatos):
        existentes = [v.strip().lower() for v in resultado.get(chave, ["", "", ""]) if str(v or "").strip()]
        for candidato in candidatos:
            item = limpar_item_caixa(candidato)
            if not item:
                continue
            item_norm = item.lower()
            if item_norm in existentes:
                continue
            for i in range(3):
                if not resultado[chave][i]:
                    resultado[chave][i] = item
                    existentes.append(item_norm)
                    break
            if all(resultado[chave]):
                break

    secoes = {
        "fatores_externos": extrair_itens_secao(
            texto_base,
            termos_inicio=["FATORES EXTERNOS", "Fatores externos", "Nível 5", "Nivel 5"],
            termos_fim=["INFLUÊNCIAS ORGANIZACIONAIS", "Influências organizacionais", "Nível 4", "Nivel 4", "SUPERVISÃO INADEQUADA"],
            max_itens=30,
        ),
        "influencias_organizacionais": extrair_itens_secao(
            texto_base,
            termos_inicio=["INFLUÊNCIAS ORGANIZACIONAIS", "Influências organizacionais", "Nível 4", "Nivel 4"],
            termos_fim=["SUPERVISÃO INADEQUADA", "Supervisão inadequada", "Nível 3", "Nivel 3", "CONDIÇÕES PRECURSORAS"],
            max_itens=35,
        ),
        "supervisao": extrair_itens_secao(
            texto_base,
            termos_inicio=["SUPERVISÃO INADEQUADA", "Supervisão inadequada", "Nível 3", "Nivel 3"],
            termos_fim=["CONDIÇÕES PRECURSORAS", "Condições precursoras", "Nível 2", "Nivel 2", "ATOS INSEGUROS"],
            max_itens=30,
        ),
        "precondicoes": extrair_itens_secao(
            texto_base,
            termos_inicio=["CONDIÇÕES PRECURSORAS", "Condições precursoras", "Nível 2", "Nivel 2"],
            termos_fim=["ATOS INSEGUROS", "Atos inseguros", "Nível 1", "Nivel 1", "CONSIDERAÇÕES FINAIS", "Recomendações"],
            max_itens=35,
        ),
        "atos": extrair_itens_secao(
            texto_base,
            termos_inicio=["ATOS INSEGUROS", "Atos inseguros", "Nível 1", "Nivel 1", "Ato inseguro"],
            termos_fim=["CONSIDERAÇÕES FINAIS", "Considerações finais", "Recomendações", "Recomendacoes", "Resumo"],
            max_itens=25,
        ),
    }

    # Complementação direcionada por palavras-chave. Usa apenas frases encontradas no texto.
    regras = {
        "governo_orgaos_reguladores": ("fatores_externos", ["norma", "regulat", "órgão", "orgao", "fiscal", "ansi", "asme", "legis", "padron"]),
        "influencias_politicas_economicas": ("fatores_externos", ["press", "custo", "prazo", "produção", "producao", "turnaround", "contrato", "mercado", "econ"]),
        "fisico_social_cultural": ("fatores_externos", ["cultura", "setor", "prática", "pratica", "ambiente", "toler", "normalização", "normalizacao"]),
        "mercado_clientes": ("fatores_externos", ["cliente", "contrato", "fornecedor", "terceir", "mercado", "prazo", "multa"]),
        "gerenciamento_recursos": ("influencias_organizacionais", ["trein", "recurso", "equipe", "contrat", "pessoal", "detector", "equipamento"]),
        "clima_organizacional": ("influencias_organizacionais", ["cultura", "clima", "desvio", "permiss", "disciplina", "prática", "pratica", "toler"]),
        "processo_operacional": ("influencias_organizacionais", ["proced", "permiss", "work permit", "process", "escopo", "licença", "licenca", "padron"]),
        "supervisao_inadequada": ("supervisao", ["supervis", "presença", "presenca", "operador", "acompan", "campo", "fiscal"]),
        "planejamento_inadequado_operacoes": ("supervisao", ["planej", "mudança", "mudanca", "reatrib", "turnaround", "simop", "operações simult", "operacoes simult"]),
        "falha_resolver_problemas": ("supervisao", ["falha", "não resol", "nao resol", "hold", "ponto de parada", "interven", "corrigir"]),
        "violacao_supervisao": ("supervisao", ["viol", "permit", "permiss", "desvio", "sem presença", "sem presenca", "não ades", "nao ades"]),
        "ambiente_fisico": ("precondicoes", ["ambiente", "tubula", "linha", "flange", "próxim", "proxim", "idêntic", "identic", "layout"]),
        "ambiente_tecnico": ("precondicoes", ["tag", "rotul", "sinal", "marc", "detector", "alarme", "equipamento", "flange-locking"]),
        "estado_mental_adverso": ("precondicoes", ["percep", "consciência", "consciencia", "confusão", "confusao", "crença", "crenca", "falsa segurança", "situacional"]),
        "estado_fisico_adverso": ("precondicoes", ["fadiga", "calor", "ruído", "ruido", "exposição", "exposicao", "respirador", "h2s"]),
        "limitacoes_fisicas_mentais": ("precondicoes", ["limita", "informação incompleta", "informacao incompleta", "visib", "percep", "cognit"]),
        "gerenciamento_equipe_recursos": ("precondicoes", ["comunica", "equipe", "brief", "turno", "contrat", "coordena", "interface"]),
        "execucao_pessoal": ("precondicoes", ["execu", "prontidão", "prontidao", "detector", "respirador", "procedimento", "tarefa"]),
        "erros_decisao": ("atos", ["decisão", "decisao", "seleção", "selecao", "escolh", "flange errada", "linha errada"]),
        "erros_baseados_habilidade": ("atos", ["execu", "remoção", "remocao", "abertura", "blind", "flange", "habilidade"]),
        "erros_percepcao": ("atos", ["percep", "confusão", "confusao", "visual", "identifica", "falsa", "crença", "crenca"]),
        "rotina": ("atos", ["rotina", "prática comum", "pratica comum", "turnaround", "costume", "normal"]),
        "excepcional": ("atos", ["excepcional", "violação", "violacao", "sem operador", "detector", "respirador", "continuação", "continuacao"]),
    }

    for chave, (secao, palavras) in regras.items():
        candidatos = [item for item in secoes.get(secao, []) if any(p in item.lower() for p in palavras)]
        if not candidatos:
            candidatos = secoes.get(secao, [])
        adicionar(chave, candidatos)

    # Se alguma chave crítica ainda ficou vazia, distribui itens do nível correspondente.
    grupos_padrao = {
        "fatores_externos": ["governo_orgaos_reguladores", "influencias_politicas_economicas", "fisico_social_cultural", "mercado_clientes"],
        "influencias_organizacionais": ["gerenciamento_recursos", "clima_organizacional", "processo_operacional"],
        "supervisao": ["supervisao_inadequada", "planejamento_inadequado_operacoes", "falha_resolver_problemas", "violacao_supervisao"],
        "precondicoes": ["ambiente_fisico", "ambiente_tecnico", "estado_mental_adverso", "estado_fisico_adverso", "limitacoes_fisicas_mentais", "gerenciamento_equipe_recursos", "execucao_pessoal"],
        "atos": ["erros_decisao", "erros_baseados_habilidade", "erros_percepcao", "rotina", "excepcional"],
    }
    for secao, chaves in grupos_padrao.items():
        itens = secoes.get(secao, [])
        if not itens:
            continue
        idx = 0
        for chave in chaves:
            if not any(resultado[chave]):
                adicionar(chave, itens[idx:idx+3] or itens)
                idx += 3

    return resultado


def extrair_descricao_curta(descricao_detalhada, texto_final):
    base = primeiro_valor(descricao_detalhada, texto_final, padrao="não informado")
    palavras = re.findall(r"\S+", base)
    if len(palavras) > 90:
        base = " ".join(palavras[:90]) + "..."
    return base


def gerar_titulo_investigacao(dados_basicos, descricao_detalhada="", texto_final=""):
    """Gera um nome curto para a investigação, sem copiar o nome do arquivo anexado.

    O título prioriza o tipo de acidente e o local, por exemplo:
    "Explosão de Caldeira em Seropédica".

    Importante: o texto_final começa com a frase padrão do relatório
    ("Com base no relatório detalhado do acidente e considerando...").
    Essa frase NÃO deve ser usada para formar o título, pois gerava nomes como
    "Relatório de investigação - Acidente e Considerando O Modelos".
    """
    local = str(dados_basicos.get("Local do acidente") or "").strip()
    setor = str(dados_basicos.get("Setor do acidente") or "").strip()
    danos = str(dados_basicos.get("Danos ao patrimônio") or "").strip()

    def limpar_texto_base(texto):
        texto = str(texto or "")
        # Remove a frase obrigatória de abertura do relatório, que não descreve o tipo do acidente.
        texto = re.sub(
            r"Com base no relatório detalhado do acidente e considerando[^:]{0,250}:?",
            " ",
            texto,
            flags=re.IGNORECASE,
        )
        # Remove trechos genéricos que aparecem no relatório e contaminam o título.
        texto = re.sub(r"relat[oó]rio de investiga[cç][aã]o[^.\n]{0,120}", " ", texto, flags=re.IGNORECASE)
        texto = re.sub(r"classifica[cç][aã]o dos fatores contribuintes", " ", texto, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", texto).strip()

    # Prioriza informações digitadas pelo usuário. O relatório final é usado apenas como apoio,
    # já sem a frase padrão de abertura.
    textos_para_busca = [
        limpar_texto_base(descricao_detalhada),
        limpar_texto_base(danos),
        limpar_texto_base(setor),
        limpar_texto_base(local),
        limpar_texto_base(texto_final),
    ]
    base_texto = " ".join([t for t in textos_para_busca if t])
    base_normalizada = re.sub(r"\s+", " ", base_texto.lower()).strip()

    padroes_tipo = [
        (r"explos[aã]o(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Explosão"),
        (r"inc[eê]ndio(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Incêndio"),
        (r"queda(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Queda"),
        (r"soterramento(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Soterramento"),
        (r"desabamento(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Desabamento"),
        (r"colapso(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Colapso"),
        (r"vazamento(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Vazamento"),
        (r"intoxica[cç][aã]o(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Intoxicação"),
        (r"choque el[eé]trico(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Choque elétrico"),
        (r"atropelamento(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Atropelamento"),
        (r"rompimento(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Rompimento"),
        (r"tombamento(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Tombamento"),
        (r"esmagamento(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Esmagamento"),
        (r"amputa[cç][aã]o(?:\s+de|\s+em|\s+no|\s+na)?[^.,;\n]{0,45}", "Amputação"),
    ]

    def formatar_titulo_pt(texto):
        minusculas = {"de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas", "e"}
        palavras = re.sub(r"\s+", " ", str(texto or "")).strip().split()
        saida = []
        for i, palavra in enumerate(palavras):
            palavra = palavra.strip(" -–—.,;:")
            if not palavra:
                continue
            if i > 0 and palavra.lower() in minusculas:
                saida.append(palavra.lower())
            else:
                saida.append(palavra[:1].upper() + palavra[1:])
        return " ".join(saida).strip()

    def limpar_trecho_tipo(trecho):
        trecho = re.sub(r"\s+", " ", str(trecho or "")).strip(" -–—.,;:")
        trecho = re.split(
            r"\b(que|quando|durante|ap[oó]s|depois|no momento|em seguida|considerando|com base|segue|causou|resultou)\b",
            trecho,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" -–—.,;:")
        # Evita que a localização seja repetida dentro do tipo.
        if local:
            trecho = re.sub(rf"\s+(em|no|na)\s+{re.escape(local)}\b.*$", "", trecho, flags=re.IGNORECASE)
        # Limita para manter um nome curto e limpo.
        return " ".join(trecho.split()[:6]).strip()

    tipo = ""
    for padrao, fallback in padroes_tipo:
        achado = re.search(padrao, base_normalizada)
        if achado:
            trecho = limpar_trecho_tipo(achado.group(0))
            tipo = formatar_titulo_pt(trecho) or fallback
            break

    if not tipo:
        if setor and setor.lower() != "não informado":
            tipo = f"Acidente no {formatar_titulo_pt(setor)}"
        else:
            tipo = "Acidente"

    local_titulo = ""
    if local and local.lower() != "não informado":
        local_titulo = formatar_titulo_pt(local)
    elif setor and setor.lower() != "não informado" and not tipo.lower().endswith(formatar_titulo_pt(setor).lower()):
        local_titulo = formatar_titulo_pt(setor)

    if local_titulo:
        return f"{tipo} em {local_titulo}"
    return tipo

def montar_substituicoes_word(dados_analista, dados_basicos, descricao_detalhada, texto_final):
    titulo = gerar_titulo_investigacao(dados_basicos, descricao_detalhada, texto_final)

    vitimas = primeiro_valor(dados_basicos.get("Nome da vítima"), padrao="não informado")
    testemunhas = primeiro_valor(dados_basicos.get("Testemunhas"), padrao="não informado")

    return {
        # Marcador do modelo anterior
        "COLOQUE AQUI O NOME DA INVESTIGAÇÃO – EXEMPLO RELATÓRIO DO ACIDENTE DE SEROPÉDICA DE 14 DE JUNHO DE 2026": titulo,

        # Marcador do modelo novo
        "COLOQUE AQUI UMA NOME ADEQUADO PARA A INVESTIGAÇÃO QUE FAÇA REFERENCIA AO TIPO DE ACIDENTE E AO LOCAL DO ACIDENTE - ": titulo,

        "(Colocar aqui nome do analista que fez a investigação)": primeiro_valor(dados_analista.get("Nome do analista")),
        "(Colocar aqui o cargo do investigador)": primeiro_valor(dados_analista.get("Cargo do analista")),
        "(colocar aqui o setor do investigador)": primeiro_valor(dados_analista.get("Setor do analista")),
        "(Colocar aqui nome)": vitimas,
        "Se não tiver nome da vitima ou testemunha, escrever, não mencionado nos relatórios, ou colocar diversas vitimas, quando forem varias e diversas testemunhas ": "Informações preenchidas conforme dados inseridos na ferramenta; quando ausentes, considerar como não informado.",
        "(Colocar aqui em no máximo 90 palavras a descrição do acidente- com informações doque ocorreu, se houve vitimas e feridos, qual cidade, pais, data, horário, e outras informações importantes": extrair_descricao_curta(descricao_detalhada, texto_final),

        # Marcador do modelo anterior
        "COLCOAR ABAIXO TODO RELATÓRIO ESCRITO QUE A FERRAMENTA JÁ FORNECE (TODO TEXTO DE RESPOSTA DA FERRAMENTA": texto_final,

        # Marcador do modelo novo
        "Classificação dos fatores contribuintes": "Classificação dos fatores contribuintes\n\n" + str(texto_final or ""),
    }


def substituir_texto_em_paragrafo(paragrafo, substituicoes):
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    textos = paragrafo.xpath(".//w:t", namespaces=ns)
    if not textos:
        return

    texto_original = "".join(t.text or "" for t in textos)
    texto_novo = texto_original

    for marcador, valor in substituicoes.items():
        texto_novo = texto_novo.replace(f"#{marcador}#", str(valor or ""))

    # Remove a observação residual do novo marcador do título, quando ela fica fora dos sinais #...#.
    texto_novo = texto_novo.replace(" NÃO COPIAR O NOME DO ARQUIVO ANEXADO#", "")

    # Remove qualquer outro marcador #...# que tenha sobrado no modelo.
    texto_novo = re.sub(r"#[^#]{0,300}#", "", texto_novo)

    if texto_novo == texto_original:
        return

    primeiro_texto = textos[0]
    parent = primeiro_texto.getparent()
    for t in textos[1:]:
        t.text = ""
    primeiro_texto.text = ""

    linhas = str(texto_novo).split("\n")
    primeiro_texto.text = linhas[0] if linhas else ""
    for linha in linhas[1:]:
        br = etree.Element("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}br")
        novo_t = etree.Element("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
        novo_t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        novo_t.text = linha
        parent.append(br)
        parent.append(novo_t)


def preencher_caixas_hfacs(document_xml, hfacs_caixas):
    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    }
    root = etree.fromstring(document_xml)
    conteudos_caixas = root.xpath(".//w:txbxContent", namespaces=ns)

    secoes_visuais = [
        [
            "governo_orgaos_reguladores",
            "influencias_politicas_economicas",
            "fisico_social_cultural",
            "mercado_clientes",
        ],
        [
            "gerenciamento_recursos",
            "clima_organizacional",
            "processo_operacional",
        ],
        [
            "supervisao_inadequada",
            "planejamento_inadequado_operacoes",
            "falha_resolver_problemas",
            "violacao_supervisao",
        ],
        [
            "ambiente_fisico",
            "ambiente_tecnico",
            "estado_mental_adverso",
            "estado_fisico_adverso",
            "limitacoes_fisicas_mentais",
            "gerenciamento_equipe_recursos",
            "execucao_pessoal",
        ],
        [
            "erros_decisao",
            "erros_baseados_habilidade",
            "erros_percepcao",
            "rotina",
            "excepcional",
        ],
    ]

    valores = []
    for secao in secoes_visuais:
        for linha in range(3):
            for chave in secao:
                valores.append(hfacs_caixas.get(chave, ["", "", ""])[linha])

    def limpar_textos_caixa(caixa, valor):
        textos = caixa.xpath(".//w:t", namespaces=ns)
        if textos:
            textos[0].text = str(valor or "")
            for t in textos[1:]:
                t.text = ""

    def coordenadas_caixa(caixa):
        anchor = caixa.xpath("ancestor::wp:anchor[1]", namespaces=ns)
        if not anchor:
            return None
        x = anchor[0].xpath("./wp:positionH/wp:posOffset/text()", namespaces=ns)
        y = anchor[0].xpath("./wp:positionV/wp:posOffset/text()", namespaces=ns)
        if not x or not y:
            return None
        try:
            return int(y[0]), int(x[0])
        except ValueError:
            return None

    # No modelo Word, cada retângulo aparece em duas versões internas:
    # DrawingML (par) e VML (ímpar). A ordem do XML não é a ordem visual do diagrama.
    # Por isso, ordenamos as caixas pela coordenada visual (de cima para baixo e da esquerda para a direita)
    # e só depois aplicamos os valores. Isso impede que a primeira informação caia na segunda caixa.
    pares_por_posicao = []
    for indice, caixa in enumerate(conteudos_caixas):
        coords = coordenadas_caixa(caixa)
        if coords is None:
            continue
        par_vml = conteudos_caixas[indice + 1] if indice + 1 < len(conteudos_caixas) else None
        pares_por_posicao.append((coords[0], coords[1], caixa, par_vml))

    if len(pares_por_posicao) >= 69:
        # Agrupa coordenadas de Y próximas para formar a mesma linha visual.
        # O Word pode salvar caixas da mesma linha com pequenas diferenças de Y;
        # ordenar apenas por (Y, X) desloca valores para a coluna errada.
        linhas = []
        tolerancia_y = 100000
        for item in sorted(pares_por_posicao, key=lambda item: item[0]):
            if not linhas or abs(item[0] - linhas[-1]["y_medio"]) > tolerancia_y:
                linhas.append({"y_medio": item[0], "itens": [item]})
            else:
                linha = linhas[-1]
                linha["itens"].append(item)
                linha["y_medio"] = sum(i[0] for i in linha["itens"]) / len(linha["itens"])

        caixas_ordenadas = []
        for linha in linhas:
            caixas_ordenadas.extend(sorted(linha["itens"], key=lambda item: item[1]))
        caixas_ordenadas = caixas_ordenadas[:69]

        for (_, _, caixa_drawing, caixa_vml), valor in zip(caixas_ordenadas, valores):
            limpar_textos_caixa(caixa_drawing, valor)
            if caixa_vml is not None:
                limpar_textos_caixa(caixa_vml, valor)
    elif len(conteudos_caixas) >= 69:
        # Fallback para modelos antigos sem coordenadas: preenche as últimas 69 caixas em ordem.
        for caixa, valor in zip(conteudos_caixas[-69:], valores):
            limpar_textos_caixa(caixa, valor)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")

def gerar_docx_relatorio(modelo_path, dados_analista, dados_basicos, descricao_detalhada, texto_final, hfacs_caixas):
    substituicoes = montar_substituicoes_word(
        dados_analista,
        dados_basicos,
        descricao_detalhada,
        texto_final,
    )
    hfacs_caixas = completar_caixas_hfacs_por_texto(hfacs_caixas, texto_final)

    buffer_saida = BytesIO()
    with zipfile.ZipFile(modelo_path, "r") as zin, zipfile.ZipFile(buffer_saida, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            conteudo = zin.read(item.filename)
            if item.filename == "word/document.xml":
                root = etree.fromstring(conteudo)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                for paragrafo in root.xpath(".//w:p", namespaces=ns):
                    substituir_texto_em_paragrafo(paragrafo, substituicoes)
                conteudo = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")
                conteudo = preencher_caixas_hfacs(conteudo, hfacs_caixas)
            zout.writestr(item, conteudo)

    buffer_saida.seek(0)
    return buffer_saida.getvalue()


def gerar_pdf_relatorio_direto(dados_analista, dados_basicos, descricao_detalhada, texto_final, resumo_conciso, recomendacoes, hfacs_caixas):
    """
    Gera o PDF diretamente pelo Python, sem usar Word, LibreOffice ou qualquer programa externo.
    Observação: o PDF é montado de forma independente do modelo DOCX. O DOCX continua usando o modelo Word.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TituloCentral", parent=styles["Title"], alignment=1, fontSize=14, leading=18, spaceAfter=10))
    styles.add(ParagraphStyle(name="Subtitulo", parent=styles["Heading2"], fontSize=11, leading=14, spaceBefore=8, spaceAfter=6))
    styles.add(ParagraphStyle(name="Texto", parent=styles["BodyText"], fontSize=9, leading=12, spaceAfter=5))
    styles.add(ParagraphStyle(name="Caixa", parent=styles["BodyText"], fontSize=6.5, leading=7.5, alignment=1))

    def esc(texto):
        texto = str(texto or "")
        return (
            texto.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )

    def ptxt(texto, estilo="Texto"):
        return Paragraph(esc(texto), styles[estilo])

    hfacs_caixas = completar_caixas_hfacs_por_texto(hfacs_caixas, texto_final)
    historia = []

    titulo = gerar_titulo_investigacao(dados_basicos, descricao_detalhada, texto_final)

    historia.append(ptxt("RELATÓRIO DA FERRAMENTA COMPUTACIONAL DE INVESTIGAÇÃO DE ACIDENTES EM SISTEMAS SOCIOTÉCNICOS COMPLEXOS", "TituloCentral"))
    historia.append(ptxt(titulo, "Subtitulo"))

    historia.append(ptxt("Dados do investigador responsável", "Subtitulo"))
    dados_investigador = [
        ["Investigador responsável", primeiro_valor(dados_analista.get("Nome do analista"))],
        ["Cargo do investigador", primeiro_valor(dados_analista.get("Cargo do analista"))],
        ["Setor do investigador", primeiro_valor(dados_analista.get("Setor do analista"))],
    ]
    tabela = Table([[ptxt(a), ptxt(b)] for a, b in dados_investigador], colWidths=[5.5 * cm, 10.5 * cm])
    tabela.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
    ]))
    historia.append(tabela)
    historia.append(Spacer(1, 0.25 * cm))

    historia.append(ptxt("Dados das vítimas e testemunhas", "Subtitulo"))
    dados_vitimas = [
        ["Nome da vítima", primeiro_valor(dados_basicos.get("Nome da vítima"))],
        ["Função/cargo da vítima", primeiro_valor(dados_basicos.get("Função/cargo da vítima"))],
        ["Testemunhas", primeiro_valor(dados_basicos.get("Testemunhas"))],
        ["Data do acidente", primeiro_valor(dados_basicos.get("Data do acidente"))],
        ["Hora do acidente", primeiro_valor(dados_basicos.get("Hora do acidente"))],
        ["Local do acidente", primeiro_valor(dados_basicos.get("Local do acidente"))],
        ["Setor do acidente", primeiro_valor(dados_basicos.get("Setor do acidente"))],
        ["Danos ao patrimônio", primeiro_valor(dados_basicos.get("Danos ao patrimônio"))],
    ]
    tabela = Table([[ptxt(a), ptxt(b)] for a, b in dados_vitimas], colWidths=[5.5 * cm, 10.5 * cm])
    tabela.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
    ]))
    historia.append(tabela)

    historia.append(ptxt("Descrição do acidente", "Subtitulo"))
    historia.append(ptxt(extrair_descricao_curta(descricao_detalhada, texto_final)))

    historia.append(PageBreak())

    historia.append(ptxt("Classificação HFACS — preenchimento automático das caixas", "TituloCentral"))

    grupos = [
        ("Fatores externos", [
            ("Governo / órgãos reguladores", "governo_orgaos_reguladores"),
            ("Influências políticas/econômicas", "influencias_politicas_economicas"),
            ("Físico/social/cultural", "fisico_social_cultural"),
            ("Mercado/clientes", "mercado_clientes"),
        ]),
        ("Influências organizacionais", [
            ("Gerenciamento de recursos", "gerenciamento_recursos"),
            ("Clima organizacional", "clima_organizacional"),
            ("Processo operacional", "processo_operacional"),
        ]),
        ("Supervisão inadequada", [
            ("Supervisão inadequada", "supervisao_inadequada"),
            ("Planejamento inadequado", "planejamento_inadequado_operacoes"),
            ("Falha em resolver problemas", "falha_resolver_problemas"),
            ("Violação de supervisão", "violacao_supervisao"),
        ]),
        ("Condições precursoras", [
            ("Ambiente físico", "ambiente_fisico"),
            ("Ambiente técnico", "ambiente_tecnico"),
            ("Estado mental adverso", "estado_mental_adverso"),
            ("Estado físico adverso", "estado_fisico_adverso"),
            ("Limitações físicas/mentais", "limitacoes_fisicas_mentais"),
            ("Gerenciamento equipe/recursos", "gerenciamento_equipe_recursos"),
            ("Execução pessoal", "execucao_pessoal"),
        ]),
        ("Atos inseguros", [
            ("Erros de decisão", "erros_decisao"),
            ("Erros baseados em habilidade", "erros_baseados_habilidade"),
            ("Erros de percepção", "erros_percepcao"),
            ("Rotina", "rotina"),
            ("Excepcional", "excepcional"),
        ]),
    ]

    for nome_grupo, itens in grupos:
        historia.append(ptxt(nome_grupo, "Subtitulo"))
        cabecalho = [ptxt("Tópico", "Caixa"), ptxt("Caixa 1", "Caixa"), ptxt("Caixa 2", "Caixa"), ptxt("Caixa 3", "Caixa")]
        dados_tabela = [cabecalho]
        for rotulo, chave in itens:
            caixas = hfacs_caixas.get(chave, ["", "", ""])
            dados_tabela.append([ptxt(rotulo, "Caixa"), ptxt(caixas[0], "Caixa"), ptxt(caixas[1], "Caixa"), ptxt(caixas[2], "Caixa")])
        tabela = Table(dados_tabela, colWidths=[4.1 * cm, 4.0 * cm, 4.0 * cm, 4.0 * cm], repeatRows=1)
        tabela.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("MINROWHEIGHT", (0, 1), (-1, -1), 0.9 * cm),
        ]))
        historia.append(tabela)
        historia.append(Spacer(1, 0.25 * cm))

    historia.append(PageBreak())
    historia.append(ptxt("Classificação dos fatores contribuintes", "Subtitulo"))
    historia.append(ptxt(texto_final))

    if resumo_conciso:
        historia.append(ptxt("Resumo — classificações e palavras-chave", "Subtitulo"))
        historia.append(ptxt(resumo_conciso))

    if recomendacoes:
        historia.append(ptxt("Recomendações sistêmicas", "Subtitulo"))
        historia.append(ptxt(recomendacoes))

    doc.build(historia)
    buffer.seek(0)
    return buffer.getvalue()

# ==================================================
# CONFIG DA PÁGINA STREAMLIT
# ==================================================
st.set_page_config(
    page_title="CO-SAFE AI (HFACS-MAP)",
    page_icon="🧀",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 0.6rem;
        padding-bottom: 1.5rem;
    }
    .section-title {
        font-size: 1.2rem;
        font-weight: 600;
        margin-top: 1.2rem;
        margin-bottom: 0.4rem;
    }
    .nivel-title {
        font-size: 1.05rem;
        font-weight: 600;
        margin-top: 1.0rem;
        margin-bottom: 0.3rem;
    }
    .small-note {
        font-size: 0.85rem;
        color: #666;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ==================================================
# ROLAGEM AUTOMÁTICA PARA MENSAGENS E RESULTADOS
# ==================================================
def rolar_para_elemento(elemento_id: str):
    components.html(
        f"""
        <script>
        const elemento = window.parent.document.getElementById("{elemento_id}");
        if (elemento) {{
            elemento.scrollIntoView({{behavior: "smooth", block: "start"}});
        }}
        </script>
        """,
        height=0,
    )

# ==================================================
# FAIXA SUPERIOR – CENTRALIZADA
# ==================================================
if PARTE_SUPERIOR.exists():
    st.markdown("<br>", unsafe_allow_html=True)
    col_a, col_b, col_c = st.columns([1.5, 4, 1.5])
    with col_b:
        st.image(str(PARTE_SUPERIOR), width=900)

# ==================================================
# SIDEBAR – LOGOS + ANALISTA
# ==================================================
with st.sidebar:
    if PEA_LOGO.exists():
        st.image(str(PEA_LOGO), width=140)
    if UFRJ_LOGO.exists():
        st.image(str(UFRJ_LOGO), width=115)

    st.markdown("---")
    nome_analista = st.text_input("Nome do analista")
    cargo_analista = st.text_input("Cargo do analista")
    setor_analista = st.text_input("Setor do analista")

    mensagem_processamento = st.empty()
    barra_processamento_placeholder = st.empty()

    col_botao_gerar, col_botao_nova = st.columns(2)
    with col_botao_gerar:
        submitted = st.button("Gerar relatório", key="botao_gerar_relatorio")
    with col_botao_nova:
        iniciar_outra_investigacao = st.button(
            "Iniciar outra investigação",
            key="botao_iniciar_outra_investigacao_sidebar",
        )

    if iniciar_outra_investigacao:
        st.session_state.clear()
        st.rerun()

# ==================================================
# CABEÇALHO CENTRAL
# ==================================================
st.markdown(
    """
    <div style="text-align:center;">
    <h2>CO-SAFE AI (HFACS-MAP)</h2>
    <p><em>Um co-analista sistêmico, que não substitui, mas apoia equipes multidisciplinares de investigação de acidentes.</em></p>
    </div>
    """,
    unsafe_allow_html=True,
)

# LOGO HFACS – CENTRALIZADO
if HFACS_LOGO and HFACS_LOGO.exists():
    c1, c2, c3 = st.columns([3, 2, 3])
    with c2:
        st.image(str(HFACS_LOGO))

st.markdown("---")

# ==================================================
# CAMPOS PRINCIPAIS – DADOS DO ACIDENTE
# ==================================================
st.markdown("<div class='section-title'>Dados do acidente</div>", unsafe_allow_html=True)

arquivos_acidente = st.file_uploader(
    "Arquivos com dados do acidente (vários PDFs)",
    type=["pdf"],
    accept_multiple_files=True,
)

arquivos_nomes = (
    ", ".join([arquivo.name for arquivo in arquivos_acidente])
    if arquivos_acidente
    else None
)

col1, col2, col3 = st.columns([1.5, 1.5, 1.2])
with col1:
    nome_vitima = st.text_input("Nome da vítima")
with col2:
    funcao_vitima = st.text_input("Função/cargo da vítima")
with col3:
    horario_trabalho = st.text_input("Horário de trabalho do colaborador (ex.: 08h00–17h00)")

col4, col5, col6 = st.columns([1.8, 1.0, 1.0])
with col4:
    testemunhas = st.text_input("Nome das testemunhas (se houver)")
with col5:
    data_acidente = st.date_input(
        "Data do acidente",
        value=None,
        format="DD/MM/YYYY",
        key="data_acidente",
    )

with col6:
    hora_acidente = st.time_input(
        "Hora do acidente",
        value=None,
        key="hora_acidente",
    )

col7, col8 = st.columns([1.5, 1.5])
with col7:
    local_acidente = st.text_input("Local do acidente (fábrica, comércio, campo, etc.)")
    setor_acidente = st.text_input("Setor do acidente (linha, unidade, posto, etc.)")
with col8:
    danos_patrimonio = st.text_area(
        "Danos ao patrimônio",
        placeholder="Descreva máquinas, estruturas, equipamentos e materiais danificados.",
    )

descricao_detalhada = st.text_area(
    "Descrição detalhada do acidente",
    placeholder="Descreva de forma narrativa a sequência de eventos, condições envolvidas e consequências.",
    height=160,
)

atividade = st.text_area(
    "Qual atividade o colaborador desempenhava no momento do acidente? (descreva em detalhes)",
    height=140,
)

# IA inferirá hora extra pelo horário x hora do acidente
horas_extras = ""

st.markdown("---")
st.markdown(
    "<div class='section-title'>Apoio à classificação do acidente – HFACS</div>",
    unsafe_allow_html=True,
)
st.markdown(
    "<span class='small-note'>Primeiro, registre sua síntese em cada nível. "
    "Em seguida, utilize as perguntas guiadas logo abaixo de cada nível.</span>",
    unsafe_allow_html=True,
)

# ==================================================
# NÍVEL 5
# ==================================================
st.markdown(
    "<div class='nivel-title'>Nível 5 – Fatores externos</div>",
    unsafe_allow_html=True,
)
nivel5_comentarios = st.text_area(
    "Comentários do analista – Nível 5",
    placeholder="Registrar fatores externos: normas, fiscalização, contratos, políticas públicas, mercado, tecnologia, etc.",
    height=120,
)

nivel5_respostas = {}
with st.expander("Perguntas guiadas – Nível 5 (Fatores externos)"):
    st.markdown("🔹 **Normas e regulamentações**")
    nivel5_respostas["existencia_normas"] = st.text_area(
        "Existiam normas aplicáveis à atividade? Elas eram claras, atualizadas e exequíveis?",
        key="n5_q1",
    )
    nivel5_respostas["conflitos_normativos"] = st.text_area(
        "Existiam conflitos entre diferentes normas aplicáveis? Alguma norma foi copiada de outro contexto sem adaptação local?",
        key="n5_q2",
    )
    nivel5_respostas["viabilidade_normas"] = st.text_area(
        "As normas eram tecnicamente viáveis na prática operacional? O cumprimento integral das normas era compatível com os prazos exigidos?",
        key="n5_q3",
    )
    nivel5_respostas["mudancas_normativas_recentes"] = st.text_area(
        "Houve mudanças normativas recentes sem tempo adequado de adaptação?",
        key="n5_q4",
    )
    nivel5_respostas["interpretacoes_divergentes"] = st.text_area(
        "Havia interpretações divergentes da mesma norma?",
        key="n5_q5",
    )

    st.markdown("🔹 **Fiscalização**")
    nivel5_respostas["fiscalizacao_recente"] = st.text_area(
        "Houve fiscalização recente relacionada à atividade? Qual foi o foco (documental ou operacional)?",
        key="n5_q6",
    )
    nivel5_respostas["fiscalizacao_trabalho_real_ou_registros"] = st.text_area(
        "A fiscalização avaliava o trabalho real ou apenas registros?",
        key="n5_q7",
    )
    nivel5_respostas["penalidades_influencia_decisoes"] = st.text_area(
        "Penalidades aplicadas anteriormente influenciaram decisões locais? Havia temor de autuação que levou a decisões arriscadas?",
        key="n5_q8",
    )
    nivel5_respostas["orientacao_orgao_fiscalizador"] = st.text_area(
        "Existia orientação técnica por parte do órgão fiscalizador? A fiscalização incentivava melhoria ou apenas punição?",
        key="n5_q9",
    )

    st.markdown("🔹 **Contratos e mercado**")
    nivel5_respostas["contratos_prazos_multas"] = st.text_area(
        "O contrato impunha prazos agressivos ou multas severas? Havia cláusulas conflitantes com requisitos normativos?",
        key="n5_q10",
    )
    nivel5_respostas["modelo_contratacao_custos"] = st.text_area(
        "Houve redução de custos exigida por clientes ou controladores? O modelo de contratação favorecia menor custo em detrimento da segurança?",
        key="n5_q11",
    )
    nivel5_respostas["terceirizacoes"] = st.text_area(
        "Terceirizações afetaram controle e treinamento? A empresa tinha autonomia para interromper a operação?",
        key="n5_q12",
    )
    nivel5_respostas["descumprimento_vs_risco"] = st.text_area(
        "O descumprimento contratual era mais punido que o risco à segurança?",
        key="n5_q13",
    )

    st.markdown("🔹 **Políticas públicas e setor**")
    nivel5_respostas["politicas_publicas_setor"] = st.text_area(
        "Existiam políticas públicas específicas para o setor? Elas priorizavam produção, custo ou segurança?",
        key="n5_q14",
    )
    nivel5_respostas["mudancas_politicas"] = st.text_area(
        "Houve mudanças políticas recentes que impactaram a operação? Cortes orçamentários afetaram fiscalização ou capacitação?",
        key="n5_q15",
    )
    nivel5_respostas["zona_cinza_regulatoria"] = st.text_area(
        "O setor operava em 'zona cinzenta' regulatória? O risco era socialmente normalizado no setor?",
        key="n5_q16",
    )

    st.markdown("🔹 **Cadeia de suprimentos e tecnologia**")
    nivel5_respostas["fornecedores_requisitos_tecnicos"] = st.text_area(
        "Fornecedores atendiam plenamente aos requisitos técnicos? Havia dependência de fornecedores únicos ou falhas na cadeia de suprimentos?",
        key="n5_q17",
    )
    nivel5_respostas["mercado_praticas_inseguras"] = st.text_area(
        "O mercado aceitava práticas inseguras como padrão? Havia competição desleal baseada em redução de custos de segurança?",
        key="n5_q18",
    )
    nivel5_respostas["tecnologia_padroes"] = st.text_area(
        "A tecnologia utilizada seguia padrões reconhecidos? Havia obsolescência tecnológica tolerada? Interfaces homem–máquina atendiam normas ergonômicas?",
        key="n5_q19",
    )
    nivel5_respostas["softwares_alertas_setoriais"] = st.text_area(
        "Softwares eram certificados ou auditados? A indústria possuía alertas ou boletins de segurança aplicáveis?",
        key="n5_q20",
    )
    nivel5_respostas["adocao_tecnologia_treinamento"] = st.text_area(
        "Houve adoção de tecnologia sem treinamento adequado? A tecnologia foi projetada para outro contexto operacional? Existiam limitações conhecidas da tecnologia?",
        key="n5_q21",
    )

# ==================================================
# NÍVEL 4
# ==================================================
st.markdown(
    "<div class='nivel-title'>Nível 4 – Influências organizacionais</div>",
    unsafe_allow_html=True,
)
nivel4_comentarios = st.text_area(
    "Comentários do analista – Nível 4",
    placeholder="Registrar fatores de cultura de segurança, gestão de recursos e processos organizacionais.",
    height=120,
)

nivel4_respostas = {}
with st.expander("Perguntas guiadas – Nível 4 (Influências organizacionais)"):
    nivel4_respostas["procedimentos_claros_atualizados"] = st.text_area(
        "A empresa possuía procedimentos claros e atualizados?",
        key="n4_q1",
    )
    nivel4_respostas["recursos_suficientes"] = st.text_area(
        "Recursos (pessoas, tempo, ferramentas) eram suficientes?",
        key="n4_q2",
    )
    nivel4_respostas["cultura_tolerava_atalhos"] = st.text_area(
        "A cultura organizacional tolerava 'atalhos'?",
        key="n4_q3",
    )
    nivel4_respostas["historico_incidentes_similares"] = st.text_area(
        "Havia histórico de incidentes similares?",
        key="n4_q4",
    )
    nivel4_respostas["peso_seguranca_vs_producao"] = st.text_area(
        "A segurança tinha o mesmo peso que produção e custo?",
        key="n4_q5",
    )

# ==================================================
# NÍVEL 3
# ==================================================
st.markdown(
    "<div class='nivel-title'>Nível 3 – Supervisão inadequada</div>",
    unsafe_allow_html=True,
)
nivel3_comentarios = st.text_area(
    "Comentários do analista – Nível 3",
    placeholder="Registrar falhas de supervisão, planejamento de operações, correção de desvios, etc.",
    height=120,
)

nivel3_respostas = {}
with st.expander("Perguntas guiadas – Nível 3 (Supervisão inadequada)"):
    nivel3_respostas["supervisao_presente"] = st.text_area(
        "A supervisão estava presente ou acessível no momento?",
        key="n3_q1",
    )
    nivel3_respostas["conflito_metas_seguranca"] = st.text_area(
        "As metas de produção conflitavam com segurança?",
        key="n3_q2",
    )
    nivel3_respostas["supervisor_conhecia_riscos"] = st.text_area(
        "O supervisor conhecia os riscos da tarefa?",
        key="n3_q3",
    )
    nivel3_respostas["atividade_autorizada_com_desvios"] = st.text_area(
        "A atividade foi autorizada mesmo com desvios conhecidos?",
        key="n3_q4",
    )
    nivel3_respostas["falhas_correcao_problemas"] = st.text_area(
        "Houve falha em corrigir problemas já identificados anteriormente?",
        key="n3_q5",
    )

# ==================================================
# NÍVEL 2
# ==================================================
st.markdown(
    "<div class='nivel-title'>Nível 2 – Condições precursoras</div>",
    unsafe_allow_html=True,
)
nivel2_comentarios = st.text_area(
    "Comentários do analista – Nível 2",
    placeholder="Registrar condições de trabalho, fatores do operador, ambiente, planejamento, etc.",
    height=120,
)

nivel2_respostas = {}
with st.expander("Perguntas guiadas – Nível 2 (Condições precursoras)"):
    nivel2_respostas["ambiente_fisico"] = st.text_area(
        "O ambiente estava ruidoso, escuro, quente, apertado ou com visibilidade reduzida?",
        key="n2_q1",
    )
    nivel2_respostas["equipamentos_degradados"] = st.text_area(
        "Algum equipamento estava em condição degradada?",
        key="n2_q2",
    )
    nivel2_respostas["interferencias_externas"] = st.text_area(
        "Houve interferência externa (clima, vibração, layout)?",
        key="n2_q3",
    )
    nivel2_respostas["fadiga_estresse_jornada"] = st.text_area(
        "A pessoa estava cansada, estressada ou sob jornada estendida?",
        key="n2_q4",
    )
    nivel2_respostas["treinamento_recente"] = st.text_area(
        "Havia treinamento recente para essa atividade?",
        key="n2_q5",
    )
    nivel2_respostas["tarefa_familiar_ou_rara"] = st.text_area(
        "A tarefa era familiar ou rara?",
        key="n2_q6",
    )
    nivel2_respostas["falhas_comunicacao"] = st.text_area(
        "Houve falhas de comunicação entre turnos ou equipes?",
        key="n2_q7",
    )

# ==================================================
# NÍVEL 1 – Comentário + Perguntas Guiadas
# ==================================================
st.markdown(
    "<div class='nivel-title'>Nível 1 – Atos inseguros (erros e violações identificadas)</div>",
    unsafe_allow_html=True,
)
nivel1_comentarios = st.text_area(
    "Comentários do analista – Nível 1",
    placeholder="Registre aqui os principais atos inseguros, erros e violações identificadas (visão do analista).",
    height=120,
)

nivel1_respostas = {}
with st.expander("Perguntas guiadas – Nível 1 (Atos inseguros)"):
    nivel1_respostas["o_que_tentava_fazer"] = st.text_area(
        "O que a pessoa estava tentando fazer ou fazendo no momento do acidente?",
        key="n1_q1",
    )
    nivel1_respostas["decisoes_pressao_tempo"] = st.text_area(
        "Houve alguma decisão tomada sob pressão de tempo?",
        key="n1_q2",
    )
    nivel1_respostas["procedimentos_adaptados_ou_ignorados"] = st.text_area(
        "Algum procedimento foi adaptado, encurtado ou ignorado? Por quê?",
        key="n1_q3",
    )
    nivel1_respostas["multiplas_atividades"] = st.text_area(
        "A tarefa exigia atenção simultânea a múltiplas atividades?",
        key="n1_q4",
    )
    nivel1_respostas["percepcao_previa_do_risco"] = st.text_area(
        "A pessoa percebeu o risco antes do evento?",
        key="n1_q5",
    )
    nivel1_respostas["ambiguidades_instrucao"] = st.text_area(
        "Havia ambiguidades nas instruções recebidas?",
        key="n1_q6",
    )

st.markdown("<div id='mensagens-processamento'></div>", unsafe_allow_html=True)
st.markdown("---")

# ==================================================
# BOTÃO – GERAR RELATÓRIOS
# ==================================================
if submitted:
    rolar_para_elemento("mensagens-processamento")
    mensagem_processamento.info("Gerando relatório preliminar")

    barra_processamento = barra_processamento_placeholder.progress(0)

    for progresso in range(1, 21):
        barra_processamento.progress(progresso * 5)

    dados_analista = {
        "Nome do analista": nome_analista,
        "Cargo do analista": cargo_analista,
        "Setor do analista": setor_analista,
    }

    dados_basicos = {
        "Arquivo-base": arquivos_nomes or "não informado",
        "Nome da vítima": nome_vitima,
        "Função/cargo da vítima": funcao_vitima,
        "Horário de trabalho do colaborador": horario_trabalho,
        "Testemunhas": testemunhas,
        "Data do acidente": data_acidente.isoformat()
        if data_acidente
        else "não informado",
        "Hora do acidente": hora_acidente.strftime("%H:%M")
        if hora_acidente
        else "não informado",
        "Local do acidente": local_acidente,
        "Setor do acidente": setor_acidente,
        "Danos ao patrimônio": danos_patrimonio,
    }

    contexto = montar_contexto_acidente(
        dados_analista,
        dados_basicos,
        descricao_detalhada,
        atividade,
        horas_extras,
        nivel1_comentarios,
        nivel1_respostas,
        nivel2_comentarios,
        nivel2_respostas,
        nivel3_comentarios,
        nivel3_respostas,
        nivel4_comentarios,
        nivel4_respostas,
        nivel5_comentarios,
        nivel5_respostas,
    )

    # >>> NOVO: texto extraído do PDF enviado pelo usuário (se for PDF)
    texto_pdfs_acidente = ""
    caracteres_anexos_extraidos = 0
    caracteres_anexos_enviados = 0
    paginas_anexos = 0
    pdfs_lidos = 0

    if arquivos_acidente:
        (
            texto_pdfs_acidente,
            caracteres_anexos_extraidos,
            caracteres_anexos_enviados,
            paginas_anexos,
            pdfs_lidos,
            avisos_pdfs,
        ) = extrair_textos_pdfs_upload(
            arquivos_acidente,
            max_chars_total=4000000,
        )

        for aviso in avisos_pdfs:
            st.warning(aviso)

        if texto_pdfs_acidente:
            contexto += (
                "\n\n=== TEXTOS EXTRAÍDOS DOS ARQUIVOS DO ACIDENTE (PDFs ENVIADOS) ===\n"
                + texto_pdfs_acidente
            )

            msg_pdf_acidente = (
                f"{pdfs_lidos} PDF(s) do acidente lido(s) com sucesso. "
                f"Total de páginas: {paginas_anexos}. "
                f"Total de caracteres extraídos dos anexos: {caracteres_anexos_extraidos}. "
                f"Total de caracteres enviados para análise: {caracteres_anexos_enviados}."
            )

            st.session_state["msg_pdf_acidente"] = msg_pdf_acidente
            st.success(msg_pdf_acidente)

            if caracteres_anexos_extraidos > caracteres_anexos_enviados:
                st.warning(
                    f"Os anexos possuem {caracteres_anexos_extraidos} caracteres extraídos, "
                    f"mas apenas {caracteres_anexos_enviados} caracteres foram enviados para a IA "
                    f"devido ao limite definido no código."
                )

        else:
            st.warning(
                "Os PDFs foram carregados, mas nenhum texto pôde ser extraído. "
                "Isso pode ocorrer quando os arquivos estão escaneados como imagem."
            )

    with st.spinner("Lendo PDFs de referência em '00. Suporte ao APP'..."):
        corpus_ref, n_pdfs, n_chars = carregar_corpus_pdf()

    msg_corpus = (
        f"Corpus de referência carregado: {n_pdfs} PDF(s), "
        f"aproximadamente {n_chars} caracteres de texto extraído."
    )

    st.session_state["msg_corpus"] = msg_corpus
    st.info(msg_corpus)

    if n_pdfs == 0 or n_chars == 0:
        st.warning(
            "Nenhum texto útil pôde ser extraído dos PDFs. A IA funcionará, mas sem a orientação específica dos artigos/manuais."
        )

    client, erro_client = obter_cliente_openai()
    if erro_client:
        st.error(erro_client)
    else:
        with st.spinner("Gerando relatório preliminar..."):
            relatorio_completo, resumo_conciso, recomendacoes, hfacs_caixas, erro_ia = (
                chamar_ia_gerar_relatorios(client, contexto, corpus_ref)
            )

        if erro_ia:
            st.error(erro_ia)
        else:
            st.session_state["relatorio_editavel"] = relatorio_completo
            st.session_state["relatorio_final"] = relatorio_completo
            st.session_state["resumo_conciso"] = resumo_conciso
            st.session_state["recomendacoes"] = recomendacoes
            st.session_state["hfacs_caixas"] = hfacs_caixas
            st.session_state["dados_analista"] = dados_analista
            st.session_state["dados_basicos"] = dados_basicos
            st.session_state["descricao_detalhada"] = descricao_detalhada
            st.session_state["rolar_para_resultado"] = True

# ==================================================
# EXIBIÇÃO DOS RESULTADOS
# ==================================================
if "relatorio_editavel" in st.session_state:
    st.markdown("<div id='resultado-investigacao'></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.subheader("Resultado da investigação de acidentes")

    if st.session_state.get("rolar_para_resultado"):
        rolar_para_elemento("resultado-investigacao")
        st.session_state["rolar_para_resultado"] = False

    st.markdown("#### 1. Relatório de investigação (editável pelo analista)")
    texto_editavel = st.text_area(
        "Revise e edite o texto conforme necessário antes de consolidar o relatório final.",
        value=st.session_state["relatorio_editavel"],
        key="campo_relatorio_editavel",
        height=380,
    )

    if st.button("Salvar alterações do relatório"):
        st.session_state["relatorio_final"] = texto_editavel
        st.success("Relatório final atualizado com as alterações do analista.")

    st.markdown("#### 2. Relatório final (a partir da versão editada)")
    texto_final = st.session_state.get(
        "relatorio_final", st.session_state["relatorio_editavel"]
    )
    st.write(texto_final)

    st.markdown("#### 3. Resumo – classificações e palavras-chave")
    st.write(st.session_state.get("resumo_conciso", ""))

    st.markdown("#### 4. Recomendações sistêmicas")
    st.write(st.session_state.get("recomendacoes", ""))

    st.markdown("#### Download dos documentos")
    modelo_word = localizar_modelo_word()

    if not modelo_word:
        st.warning(
            f"Modelo Word '{MODELO_WORD_NOME}' não encontrado. "
            "Coloque o arquivo do modelo na mesma pasta do app.py ou na pasta raiz do projeto."
        )
    else:
        try:
            docx_bytes = gerar_docx_relatorio(
                modelo_word,
                st.session_state.get("dados_analista", {}),
                st.session_state.get("dados_basicos", {}),
                st.session_state.get("descricao_detalhada", ""),
                texto_final,
                st.session_state.get("hfacs_caixas", {}),
            )
            pdf_bytes = gerar_pdf_relatorio_direto(
                st.session_state.get("dados_analista", {}),
                st.session_state.get("dados_basicos", {}),
                st.session_state.get("descricao_detalhada", ""),
                texto_final,
                st.session_state.get("resumo_conciso", ""),
                st.session_state.get("recomendacoes", ""),
                st.session_state.get("hfacs_caixas", {}),
            )

            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                st.download_button(
                    "Baixar relatório em Word (.docx)",
                    data=docx_bytes,
                    file_name="relatorio_investigacao_hfacs.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            with col_dl2:
                st.download_button(
                    "Baixar relatório em PDF (.pdf)",
                    data=pdf_bytes,
                    file_name="relatorio_investigacao_hfacs.pdf",
                    mime="application/pdf",
                )
        except Exception as e:
            st.error(f"Não foi possível gerar os arquivos Word/PDF: {e}")

    st.markdown("---")

