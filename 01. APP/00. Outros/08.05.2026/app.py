import os
import json
from pathlib import Path
from datetime import datetime

import streamlit as st
from pypdf import PdfReader
from openai import OpenAI

# ==================================================
# CONFIGURAÇÃO DE CAMINHOS
# ==================================================
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

SUPORTE_DIR = ROOT_DIR / "00. Suporte ao APP"
IMAGENS_DIR = ROOT_DIR / "02. Figuras e Layout"

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


# ==================================================
# LEITURA DOS PDFs DE REFERÊNCIA (00. Suporte ao APP)
# ==================================================
@st.cache_data(show_spinner=True)
def carregar_corpus_pdf(
    max_chars_total: int = 900000,
    max_chars_por_pdf: int = 90000,
):
    """
    Lê TODOS os PDFs de SUPORTE_DIR e monta um corpus de referência.
    """
    if not SUPORTE_DIR.exists():
        return "", 0, 0

    partes = []
    n_pdfs = 0

    for pdf_path in sorted(SUPORTE_DIR.glob("*.pdf")):
        try:
            reader = PdfReader(str(pdf_path))
            texto_paginas = []
            for page in reader.pages[:10]:
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
def extrair_texto_pdf_upload(uploaded_file, max_chars: int = 15000):
    """
    Extrai texto do PDF enviado pelo usuário e retorna:
    - texto extraído limitado
    - total de caracteres extraídos antes do corte
    - total de caracteres efetivamente enviados para a IA
    - número de páginas lidas
    """
    if uploaded_file is None:
        return "", 0, 0, 0

    try:
        reader = PdfReader(uploaded_file)
        texto_paginas = []

        for page in reader.pages:
            texto_paginas.append(page.extract_text() or "")

        texto_completo = "\n".join(texto_paginas).strip()
        caracteres_extraidos = len(texto_completo)
        numero_paginas = len(reader.pages)

        texto_limitado = texto_completo
        if len(texto_limitado) > max_chars:
            texto_limitado = texto_limitado[:max_chars]

        caracteres_enviados = len(texto_limitado)

        return texto_limitado, caracteres_extraidos, caracteres_enviados, numero_paginas

    except Exception as e:
        st.warning(f"Falha ao ler o PDF enviado do acidente: {e}")
        return "", 0, 0, 0


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

    partes.append(bloco_nivel("NÍVEL 1 – Atos inseguros", nivel1_comentarios, nivel1_respostas))
    partes.append(bloco_nivel("NÍVEL 2 – Condições precursoras", nivel2_comentarios, nivel2_respostas))
    partes.append(bloco_nivel("NÍVEL 3 – Supervisão inadequada", nivel3_comentarios, nivel3_respostas))
    partes.append(bloco_nivel("NÍVEL 4 – Influências organizacionais", nivel4_comentarios, nivel4_respostas))
    partes.append(bloco_nivel("NÍVEL 5 – Fatores externos", nivel5_comentarios, nivel5_respostas))

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
      - erro (string ou None)
    """

    system_prompt = """
Você é um co-analista sistêmico especializado em HFACS, AcciMap e STAMP, apoiando investigações de acidentes
em sistemas sociotecnicos complexos.

SUAS RESPONSABILIDADES:

1) REINTERPRETAR e CLASSIFICAR as informações do acidente nos níveis corretos do HFACS
   (Atos inseguros, Condições precursoras, Supervisão inadequada, Influências organizacionais, Fatores externos),
   mesmo que o analista humano tenha alocado itens em níveis inadequados.

2) REDIGIR os textos EM PORTUGUÊS BRASILEIRO CORRETO, com linguagem técnica clara e concisa, adequada a
   relatórios acadêmicos e de investigação de acidentes.

3) PRODUZIR TRÊS RESULTADOS, em JSON:
   (a) "relatorio_completo": um texto integrado, descrevendo o acidente e o encadeamento causal, com análise
       por nível HFACS, evitando culpabilização simplista (MESMO NO NIVEL DO ATO INSEGURO, NÃO CULPABILIZAR A VITIMA).
   (b) "resumo_conciso": síntese destacando principais fatores por nível HFACS e palavras-chave relevantes, em
       frases curtas para uso em relatorio tecnico.
   (c) "recomendacoes": conjunto de recomendações sistêmicas focadas em reduzir a probabilidade de recorrência.

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

CONSIDERAÇÕES FINAIS

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

FORMATO DE SAÍDA:
Retorne SEMPRE um JSON válido, por exemplo:

{
  "relatorio_completo": "...",
  "resumo_conciso": "...",
  "recomendacoes": "..."
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
            temperature=0.15,
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

            if isinstance(recomendacoes_raw, list):
                recomendacoes = "\n".join(str(item) for item in recomendacoes_raw)
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

        return relatorio_completo, resumo_conciso, recomendacoes, None

    except Exception as e:
        return "", "", "", f"Erro ao chamar a IA: {e}"


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

# ==================================================
# CABEÇALHO CENTRAL
# ==================================================
st.markdown(
    """
    <div style="text-align:center;">
    <h2>CO-SAFE AI (HFACS-MAP)</h2>
    <p><em>Um co-analista sistêmico para apoiar equipes multidisciplinares de investigação de acidentes.</em></p>
    <p class="small-note">
    Versão protótipo – integrando análise HFACS com base em artigos e manuais armazenados em
    '00. Suporte ao APP'.
    </p>
    <p><strong>Ferramenta de apoio à investigação de acidentes.</strong></p>
    <p>Uma ferramenta que não substitui o analista.</p>
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

arquivo_acidente = st.file_uploader(
    "Arquivo com dados do acidente (PDF, Word ou Excel)",
    type=["pdf", "doc", "docx", "xls", "xlsx"],
)
arquivo_nome = arquivo_acidente.name if arquivo_acidente is not None else None

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

st.markdown("---")

# ==================================================
# BOTÃO – GERAR RELATÓRIOS
# ==================================================
submitted = st.button("Gerar relatório")

if submitted:
    dados_analista = {
        "Nome do analista": nome_analista,
        "Cargo do analista": cargo_analista,
        "Setor do analista": setor_analista,
    }

    dados_basicos = {
        "Arquivo-base": arquivo_nome or "não informado",
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
    texto_pdf_acidente = ""
    caracteres_anexo_extraidos = 0
    caracteres_anexo_enviados = 0
    paginas_anexo = 0

    if arquivo_acidente is not None and arquivo_acidente.name.lower().endswith(".pdf"):
        (
            texto_pdf_acidente,
            caracteres_anexo_extraidos,
            caracteres_anexo_enviados,
            paginas_anexo,
        ) = extrair_texto_pdf_upload(arquivo_acidente, max_chars=40000000)

        if texto_pdf_acidente:
            contexto += (
                "\n\n=== TEXTO EXTRAÍDO DO ARQUIVO DO ACIDENTE (PDF ENVIADO) ===\n"
                + texto_pdf_acidente
            )

            st.success(
                f"Arquivo do acidente lido com sucesso: {paginas_anexo} página(s), "
                f"{caracteres_anexo_extraidos} caracteres extraídos do PDF. "
                f"{caracteres_anexo_enviados} caracteres serão enviados para análise."
            )

            if caracteres_anexo_extraidos > caracteres_anexo_enviados:
                st.warning(
                    f"O PDF possui {caracteres_anexo_extraidos} caracteres, "
                    f"mas apenas os primeiros {caracteres_anexo_enviados} caracteres "
                    f"foram enviados para a IA devido ao limite definido no código."
                )

        else:
            st.warning(
                "O PDF do acidente foi carregado, mas nenhum texto pôde ser extraído. "
                "Isso pode ocorrer quando o PDF é escaneado como imagem."
            )

    elif arquivo_acidente is not None:
        st.warning(
            "O arquivo do acidente foi carregado, mas a extração automática de texto "
            "está implementada apenas para PDF neste momento."
        )

    with st.spinner("Lendo PDFs de referência em '00. Suporte ao APP'..."):
        corpus_ref, n_pdfs, n_chars = carregar_corpus_pdf()

    st.info(
        f"Corpus de referência carregado: {n_pdfs} PDF(s), aproximadamente {n_chars} caracteres de texto extraído."
    )
    if n_pdfs == 0 or n_chars == 0:
        st.warning(
            "Nenhum texto útil pôde ser extraído dos PDFs. A IA funcionará, mas sem a orientação específica dos artigos/manuais."
        )

    client, erro_client = obter_cliente_openai()
    if erro_client:
        st.error(erro_client)
    else:
        with st.spinner("Gerando relatório preliminar..."):
            relatorio_completo, resumo_conciso, recomendacoes, erro_ia = (
                chamar_ia_gerar_relatorios(client, contexto, corpus_ref)
            )

        if erro_ia:
            st.error(erro_ia)
        else:
            st.session_state["relatorio_editavel"] = relatorio_completo
            st.session_state["relatorio_final"] = relatorio_completo
            st.session_state["resumo_conciso"] = resumo_conciso
            st.session_state["recomendacoes"] = recomendacoes

# ==================================================
# EXIBIÇÃO DOS RESULTADOS
# ==================================================
if "relatorio_editavel" in st.session_state:
    st.markdown("---")
    st.subheader("Resultado da investigação de acidentes")

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
    col_dl1, col_dl2, col_dl3 = st.columns(3)
    with col_dl1:
        st.download_button(
            "Baixar relatório final (.txt)",
            data=texto_final,
            file_name="relatorio_final_hfacs.txt",
            mime="text/plain",
        )
    with col_dl2:
        st.download_button(
            "Baixar resumo (.txt)",
            data=st.session_state.get("resumo_conciso", ""),
            file_name="resumo_hfacs.txt",
            mime="text/plain",
        )
    with col_dl3:
        st.download_button(
            "Baixar recomendações (.txt)",
            data=st.session_state.get("recomendacoes", ""),
            file_name="recomendacoes_hfacs.txt",
            mime="text/plain",
        )

    st.markdown("---")
    if st.button("Iniciar outra investigação"):
        for chave in [
            "relatorio_editavel",
            "relatorio_final",
            "resumo_conciso",
            "recomendacoes",
        ]:
            st.session_state.pop(chave, None)
        st.rerun()
