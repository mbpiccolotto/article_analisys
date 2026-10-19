# Triagem de artigos para revisão sistemática

Aplicação local para apoiar a fase inicial de revisões sistemáticas, sem tema ou área de estudo pré-definidos. Recebe exportações bibliográficas (RIS, BibTeX, CSV, PubMed ou EndNote) e classifica os registros com critérios configuráveis por projeto. A análise e o PRISMA são feitos em Python; a interface é um único `index.html` com o JavaScript. Não há nada a instalar além do Python.

## Como executar

Requisito: Python 3.10 ou superior já instalado no computador. Dê duplo clique em `launch.bat`: ele usa o Python do sistema, inicia o servidor local e abre o navegador. Não há dependências externas, ambiente virtual ou instalação. Se algo falhar, a janela mostra o erro e espera uma tecla; nenhum arquivo de relatório ou `__pycache__` é criado.

- **O servidor roda na janela do CMD, que fica aberta (minimizada) enquanto você usa o site.** Para desligá-lo, volte a essa janela e pressione `Ctrl+C` (responda `S` se o Windows perguntar se deseja terminar o arquivo em lotes). Fechar a janela também encerra o servidor.
- Se uma instância atualizada já estiver aberta na porta 5000 (em outra janela), ela é reutilizada e só o navegador abre; se estiver rodando uma versão antiga do código, um novo servidor é iniciado em outra porta. Para trocar a porta padrão, defina `TRIAGEM_PORT`.
- Sem Flask, sem compilador e sem build: o servidor usa só a biblioteca padrão do Python.

## Uso

1. Escolha um ou mais arquivos de referências (ou uma pasta). Formatos aceitos: **RIS**, **BibTeX** (`.bib`), **CSV** (Scopus, Web of Science, IEEE Xplore, PubMed), **PubMed/MEDLINE** (`.nbib`) e **EndNote** (`.enw`); um `.txt` é identificado pelo conteúdo. Tudo que não é RIS é convertido automaticamente.
2. Adicione os filtros do projeto: nome, termos, peso e se o critério é obrigatório.
3. Defina o limiar de inclusão e clique em **Analisar artigos**.
4. Revise os cartões, que mostram metadados, resumo, pontuação e justificativa da decisão.
5. Exporte a planilha Excel com abas separadas para estudos incluídos e excluídos, o arquivo `.ris` somente com os registros incluídos (inclusive os vindos de outros formatos, já convertidos), o fluxograma PRISMA em SVG ou a planilha PRISMA já preenchida com as contagens automáticas.

**Conversor para RIS:** o botão **Converter para RIS**, na tela inicial, gera um único `referencias_convertidas.ris` com os registros de todos os arquivos escolhidos, sem analisar e sem precisar de filtros. Se algum arquivo não tiver registros válidos, os demais são convertidos e o aviso aparece na tela.

| Formato | Campos aproveitados |
|---|---|
| BibTeX | tipo, título, autores, ano, periódico/anais, volume, número, páginas, DOI, resumo, palavras-chave, URL, ISSN/ISBN, editora (resolve `@string` e acentos LaTeX) |
| CSV | colunas reconhecidas pelo nome (Title, Authors / Author full names, Year, Source title, DOI, Abstract, Author Keywords, Document Type…); delimitador vírgula, ponto e vírgula ou tabulação |
| PubMed (.nbib) | PMID, título, resumo, autores (nome completo), data, periódico, volume, número, páginas, DOI, palavras-chave/MeSH, idioma |
| EndNote (.enw) | tipo, título, autores, ano, periódico, volume, número, páginas, DOI, resumo, palavras-chave, URL, ISSN, editora |

No PRISMA, os excluídos são separados por filtro não atendido: cada excluído entra em um único grupo (o primeiro filtro obrigatório não atendido; sem obrigatório, o filtro de maior peso; arquivos inválidos têm grupo próprio), e a caixa "Reports excluded" lista `Nome do filtro (n = X)` com a soma dos n igual ao total de excluídos. Acima de 8 grupos, os menores são reunidos em "Outros filtros". A planilha PRISMA traz as mesmas linhas e a coluna "Grupo de exclusão (PRISMA)".

O fluxograma usa o arquivo `prisma.svg` como modelo visual, se existir (na pasta do projeto ou nos caminhos definidos em `PRISMA_TEMPLATE_PATHS`, em `scripts/base.py`); caso contrário, desenha um fluxograma padrão. Para usar outro modelo completo, substitua esse arquivo mantendo os identificadores dos textos PRISMA.

A cada análise, os filtros e o limiar são gravados no servidor local, em `cache/last_session.json`, substituindo a sessão anterior. O botão **Restaurar critérios anteriores** lê esse arquivo, que não depende do navegador. Somente os filtros são guardados: os arquivos enviados são processados em memória e descartados depois da resposta. Para apagar a sessão guardada, exclua o arquivo (ou defina `TRIAGEM_DADOS` para usar outra pasta).

## Como a pré-triagem funciona

Os termos são buscados no título, resumo, palavras-chave e periódico de cada registro. Um estudo é incluído quando alcança o limiar e atende aos filtros obrigatórios. Antes de apresentar os resultados, referências com o mesmo DOI (prioridade) ou título normalizado idêntico são removidas automaticamente, mantendo uma aba de auditoria no export PRISMA. A origem é inferida pelo nome do arquivo (e da pasta) e pelos metadados do registro para Scopus, IEEE Xplore, Web of Science ou Outras fontes. O exemplo da tela é apenas ilustrativo e não é aplicado automaticamente.

## Limitações

- A ferramenta faz pré-triagem por metadados; não substitui a leitura crítica do texto completo nem a avaliação de risco de viés. Não lê PDFs.
- Registros devem ser confirmados no texto completo antes da inclusão final.
- A conversão cobre os campos bibliográficos comuns; campos específicos de cada base (por exemplo, o formato de texto simples etiquetado do Web of Science) não são lidos. Prefira exportar em RIS, BibTeX ou CSV.
- Termos ausentes, sinônimos ou menções em contexto inadequado podem afetar a classificação.
- O fluxograma e a planilha PRISMA são preenchidos automaticamente com as contagens da pré-triagem; trazem uma observação destacada de que a confirmação de elegibilidade e inclusão final exige análise humana criteriosa do texto completo.

## Estrutura

```text
launch.bat               único ponto de entrada (duplo clique): usa o Python do sistema, inicia o servidor neste
                         console (Ctrl+C desliga) e abre o navegador; o inicializador em Python vai embutido no fim

scripts/                 backend Python, em cinco etapas na ordem do fluxo (cada uma só importa das anteriores)
  base.py                  configuração, modelo de dados e utilitários de texto
  input.py                 leitura de RIS e conversão de BibTeX, CSV, PubMed e EndNote para RIS
  analisys.py              filtros, pontuação, deduplicação e contagens do PRISMA
  output.py                escritor de .xlsx, planilha Excel, RIS dos incluídos e PRISMA (planilha e SVG)
  server.py                filtros da última sessão (cache/last_session.json) e servidor HTTP/API (biblioteca padrão)

interface/               interface
  index.html               o único HTML: carrega o estilo e o script
  app.js                   telas (envio e resultados), tema, filtros, conversão e exportações
  style.css                estilos, com tema claro/escuro por variáveis

cache/                   última sessão (criada ao analisar; fora do Git)
```
