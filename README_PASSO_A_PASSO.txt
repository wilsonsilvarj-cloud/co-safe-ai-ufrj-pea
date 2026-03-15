CO-SAFE AI - PASSO A PASSO BEM DETALHADO

O QUE TEM NESTA PASTA
1. app.py -> o aplicativo principal
2. assets -> logos e imagens
3. support_pdfs -> os PDFs de apoio que a IA lê
4. requirements.txt -> bibliotecas que o Streamlit instala
5. runtime.txt -> versão do Python
6. .streamlit/config.toml -> configuração do Streamlit
7. .streamlit/secrets.toml.exemplo -> modelo para colocar sua chave da OpenAI

ANTES DE COMEÇAR
Você precisa de 2 contas:
1. GitHub
2. Streamlit Community Cloud

PARTE 1 - COLOCAR OS ARQUIVOS NO GITHUB
1. Baixe este ZIP no seu computador.
2. Clique com o botão direito no ZIP.
3. Clique em "Extrair tudo".
4. Abra a pasta extraída.
5. Entre no GitHub.
6. Clique em "New repository".
7. Dê um nome, por exemplo: co-safe-ai
8. Deixe como Public.
9. Clique em "Create repository".

AGORA O MAIS IMPORTANTE:
10. Na tela do repositório vazio, clique em "uploading an existing file" ou em Add file > Upload files.
11. Abra no seu computador a pasta extraída deste projeto.
12. Selecione TUDO dentro dela:
   - app.py
   - pasta assets
   - pasta support_pdfs
   - pasta .streamlit
   - requirements.txt
   - runtime.txt
   - .gitignore
13. Arraste tudo para a área de upload do GitHub.
14. Espere terminar.
15. Em "Commit changes", escreva:
   primeiro envio do app
16. Clique em "Commit changes".

IMPORTANTE:
- Não envie um ZIP.
- Envie os arquivos e as pastas extraídos.
- O GitHub aceita que você arraste vários arquivos e pastas ao mesmo tempo.

PARTE 2 - PUBLICAR NO STREAMLIT
1. Entre em https://share.streamlit.io
2. Faça login com a mesma conta do GitHub.
3. Clique em "New app".
4. Em Repository, escolha o repositório que você criou.
5. Em Branch, deixe main.
6. Em Main file path, escreva:
   app.py
7. Clique em Deploy.

PARTE 3 - COLOCAR A CHAVE DA OPENAI
Depois do deploy, o app vai abrir.
Agora faça assim:
1. No Streamlit Cloud, clique nos 3 pontinhos do app.
2. Clique em Settings.
3. Clique em Secrets.
4. Cole exatamente isto:

OPENAI_API_KEY = "SUA_CHAVE_AQUI"

5. Troque SUA_CHAVE_AQUI pela sua chave real.
6. Clique em Save.
7. Depois clique em Reboot app, se aparecer essa opção.

PARTE 4 - TESTAR
1. Abra o link público do seu app.
2. Veja se as logos aparecem.
3. Faça um teste com um PDF.
4. Depois faça um teste com DOCX e XLSX.

SE DER ERRO NAS IMAGENS
Nesta versão eu já corrigi os caminhos das imagens.
Elas ficam na pasta assets e o app procura por elas automaticamente.

SE DER ERRO NA CHAVE DA OPENAI
Verifique se você salvou em Settings > Secrets.
Não coloque a chave dentro do código.

SE QUISER ATUALIZAR O APP DEPOIS
1. Apague no GitHub o arquivo antigo que quer substituir, se necessário.
2. Faça upload do novo arquivo.
3. Clique em Commit changes.
4. O Streamlit geralmente atualiza sozinho em poucos minutos.

O QUE EU JÁ CORRIGI NESTA VERSÃO
1. Corrigi o caminho das imagens e logos.
2. Organizei as pastas para o Streamlit Cloud.
3. Corrigi a leitura da chave OPENAI_API_KEY pelo Secrets do Streamlit.
4. Mantive a leitura dos PDFs de apoio.
5. Adicionei leitura de DOCX e Excel do arquivo enviado pelo usuário.
6. Removi arquivos desnecessários como vídeo de teste e cache.

ESTRUTURA FINAL ESPERADA
app.py
assets/
support_pdfs/
.streamlit/
requirements.txt
runtime.txt
.gitignore
